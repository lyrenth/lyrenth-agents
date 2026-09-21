"""The one engine every recipe runs on.

Three steps, in order:

1. `gather` reads the URLs through Lyrenth. Each page comes back as a clean
   AIDocument with its canonical URL and a measured token count, so the engine
   can read each page once, stay inside a token budget, and say out loud which
   pages it could not read.
2. `build_prompt` turns the recipe and those pages into one finished prompt:
   the recipe's instructions, the sources numbered so they can be cited, and
   the recipe's output hint at the end.
3. `run` sends that prompt to a model if one is configured. If none is, it
   stops after step 2 and hands the prompt back. That is the whole point of
   the one-key first run: with a Lyrenth key and nothing else, the person
   still ends up with something they can use.

The reading step started as a copy of the research agent's
`lyrenth_research.sources`, kept as a copy rather than an import so this
package depends on the SDK alone. Dedupe and the wording of a failure are
still the same in both.

The budget rule changed in both on 2026-09-21: every page gets a share, and
a page that is still too long is trimmed and marked rather than dropped.
Before that the first pages took whatever was left, which is what made
`compare` answer with one product filled in and the other column reading
"not stated on the pages given" all the way down. The same day both also
learned to send the request again without `temperature` when an endpoint
refuses the field. Keep the two in step.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence

from lyrenth import Lyrenth

from .recipes import Recipe

__all__ = [
    "AgentResult",
    "Gathered",
    "ModelError",
    "Skipped",
    "Source",
    "answer_into",
    "build_messages",
    "build_prompt",
    "build_sources_block",
    "call_model",
    "check_citations",
    "dedupe_urls",
    "gather",
    "model_is_configured",
    "read_for",
    "run",
]

# The batch endpoint takes up to 20 URLs per call.
BATCH_SIZE = 20

# Raised from 30,000 on 2026-09-21, after the recipes' own example pages
# (Wikipedia articles of 20,000 to 63,000 tokens) blew straight through it and
# a first run came back with nothing read. Every model a person is likely to
# point this at holds far more than this, and a source that still does not fit
# is trimmed rather than dropped.
DEFAULT_TOKEN_BUDGET = 60_000

# A trimmed source is only worth carrying if enough of it survives to say
# something. Below this the page is skipped as it was before.
MIN_USEFUL_TOKENS = 1_500

# Added to every recipe's own instructions. Citations are what makes an answer
# checkable, so no recipe gets to leave them out.
CITATION_RULE = (
    "Use only the numbered sources given below. Cite every claim with the "
    "number of the source it comes from, like [1] or [2][3]. If the sources "
    "do not contain what is asked for, say so plainly instead of guessing."
)


@dataclass
class Source:
    """One page the agent read, with everything a citation needs."""

    url: str
    title: str
    text: str
    fetched_at: str = ""
    tokens: int = 0
    raw_html_tokens: int = 0
    # True when the page was longer than the budget left and only its opening
    # survived. The prompt says so, so nothing reads a partial page as whole.
    trimmed: bool = False


@dataclass
class Skipped:
    """A URL that did not make it into the sources, and why."""

    url: str
    reason: str


@dataclass
class Gathered:
    sources: List[Source] = field(default_factory=list)
    skipped: List[Skipped] = field(default_factory=list)
    tokens: int = 0

    @property
    def raw_html_tokens(self) -> int:
        return sum(s.raw_html_tokens for s in self.sources)


@dataclass
class AgentResult:
    """What one run produced.

    `prompt` is always filled, whether or not a model was called, so the
    caller can show it, save it, or paste it somewhere else. `answer` is None
    when no model was configured.
    """

    recipe: Recipe
    prompt: str
    requested_urls: List[str] = field(default_factory=list)
    sources: List[Source] = field(default_factory=list)
    skipped: List[Skipped] = field(default_factory=list)
    answer: Optional[str] = None
    model_used: bool = False
    cited: List[int] = field(default_factory=list)
    unknown_citations: List[int] = field(default_factory=list)
    tokens: int = 0
    raw_html_tokens: int = 0
    # Set when every requested page failed. Kept out of `answer` so that
    # nothing reads our own explanation as a model's reply.
    no_sources_reason: Optional[str] = None
    # What the person asked, for the recipes that need a question. Kept on the
    # result so the prompt that is printed and the messages that are sent are
    # built from the same value.
    question: Optional[str] = None


class ModelError(RuntimeError):
    """The model endpoint was unreachable, or answered in a shape we cannot read."""


# ------------------------------------------------------------------ reading


def _estimate_tokens(text: str) -> int:
    # Only used when a response carries no economics block. Four characters
    # per token is the usual rough figure for English text.
    return max(1, len(text) // 4)


def _to_source(doc) -> Source:
    raw = doc.raw or {}
    economics = raw.get("economics") or {}
    source = raw.get("source") or {}
    tokens = int(economics.get("output_tokens_approx") or 0) or _estimate_tokens(doc.markdown)
    return Source(
        url=doc.url,
        title=doc.title,
        text=doc.markdown,
        fetched_at=source.get("fetched_at") or "",
        tokens=tokens,
        raw_html_tokens=int(economics.get("raw_html_tokens_approx") or 0),
    )


def dedupe_urls(urls: Iterable[str]) -> List[str]:
    """The URLs as given, trimmed, with exact repeats removed, order kept."""
    seen, out = set(), []
    for u in urls or []:
        u = (u or "").strip()
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _allocate(sizes: Sequence[int], budget: int) -> List[int]:
    """Share `budget` between pages, equally, with the leftovers passed on.

    Every page gets the same allowance to start with. A page shorter than its
    allowance takes only what it needs and its remainder is shared again
    between the pages still over theirs, until nothing more can be handed out.

    Reading the pages in order and giving each one whatever was left was the
    old rule, and it meant the first long page ate the whole budget: the
    compare recipe on its own two example pages came back with one product
    filled in and the other column reading "not stated on the pages given".
    """
    allowances = [0] * len(sizes)
    unsettled = list(range(len(sizes)))
    remaining = budget
    while unsettled:
        share = remaining // len(unsettled)
        settled = [i for i in unsettled if sizes[i] <= share]
        if not settled:
            # Everyone left is over the share, so the share is the answer.
            for i in unsettled:
                allowances[i] = share
            break
        for i in settled:
            allowances[i] = sizes[i]
            remaining -= sizes[i]
            unsettled.remove(i)
    return allowances


def gather(
    urls: Iterable[str],
    client: Optional[Lyrenth] = None,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    fresh: bool = False,
) -> Gathered:
    """Read `urls` and return the sources, each with its share of the budget.

    Every page that can be read gets an equal share, and a page shorter than
    its share gives the rest back to the longer ones. Order still decides who
    is carried at all when there are more pages than the budget can hold: the
    later ones are dropped, and each says so.
    """
    client = client or Lyrenth()
    urls = dedupe_urls(urls)
    out = Gathered()
    seen_canonical = set()
    candidates: List[Source] = []

    for start in range(0, len(urls), BATCH_SIZE):
        batch = urls[start : start + BATCH_SIZE]
        for result in client.read_batch(batch, fresh=fresh):
            if not result.ok or result.document is None:
                # The explanation is the sentence a person can act on, the code
                # is only a label. getattr keeps this working against an older
                # installed SDK whose BatchResult has no message field.
                reason = getattr(result, "message", None) or result.error or "could not be read"
                out.skipped.append(Skipped(result.url, reason))
                continue
            src = _to_source(result.document)
            if not src.text.strip():
                out.skipped.append(Skipped(result.url, "page has no readable text"))
                continue
            if src.url in seen_canonical:
                out.skipped.append(Skipped(result.url, f"duplicate of {src.url}"))
                continue
            seen_canonical.add(src.url)
            candidates.append(src)

    no_room = f"no room left in the {token_budget:,} token budget"

    # A share too small to say anything is worth nothing, so the budget carries
    # a fixed number of pages at most and the ones past it are named as
    # dropped. Without this, twenty pages against a small budget would leave
    # twenty fragments and no usable source.
    room_for = max(1, token_budget // MIN_USEFUL_TOKENS)
    for src in candidates[room_for:]:
        out.skipped.append(Skipped(src.url, no_room))
    candidates = candidates[:room_for]

    for src, allowance in zip(candidates, _allocate([s.tokens for s in candidates], token_budget)):
        if src.tokens > allowance:
            if allowance < MIN_USEFUL_TOKENS:
                out.skipped.append(Skipped(src.url, no_room))
                continue
            # Four characters to a token is the usual rough figure for English
            # prose, and it only has to be close: the cut is a budget guard,
            # not an exact measure. The opening of an article carries its
            # subject, and a trimmed source is marked everywhere it appears.
            src.text = src.text[: allowance * 4].rstrip()
            src.tokens = allowance
            src.trimmed = True
        out.sources.append(src)
        out.tokens += src.tokens
    return out


# ------------------------------------------------------------------ the prompt


def build_sources_block(sources: Sequence[Source]) -> str:
    """Number the sources and keep where and when each was read."""
    parts = []
    for i, s in enumerate(sources, 1):
        header = f"[{i}] {s.title or s.url}\nURL: {s.url}"
        if s.fetched_at:
            header += f"\nRead: {s.fetched_at}"
        if s.trimmed:
            # Said where the text is, not only in a summary line, so a model
            # reading only this block still knows the page continues.
            header += "\nNote: this page was longer than the budget. Only its opening is below."
        parts.append(f"{header}\n\n{s.text}")
    return "\n\n---\n\n".join(parts)


def _instructions(recipe: Recipe, question: Optional[str] = None) -> str:
    # Two recipes (answers, research) are useless without a question, and
    # before this the only way to ask one was to type it above the printed
    # prompt by hand. It sits first, because it is what the reader is being
    # asked to do; the recipe's own instructions shape how it is answered.
    parts = []
    if question and question.strip():
        parts.append(f"Question: {question.strip()}")
    parts.append(recipe.system_prompt.strip())
    parts.append(CITATION_RULE)
    return "\n\n".join(parts)


def _material(recipe: Recipe, sources: Sequence[Source], urls: Optional[Iterable[str]] = None) -> str:
    """The sources, plus an honest note when some pages are missing."""
    parts = []
    asked = len(dedupe_urls(urls)) if urls is not None else len(sources)
    unread = asked - len(sources)
    if unread > 0:
        parts.append(
            f"Note: {unread} of the {asked} pages asked for could not be read, "
            "so what follows is incomplete. Do not fill the gap from memory."
        )
    if sources:
        parts.append("Sources:\n\n" + build_sources_block(sources))
    else:
        parts.append("Sources: none could be read.")
    parts.append(f"What to produce:\n{recipe.output_hint.strip()}")
    return "\n\n".join(parts)


def build_prompt(
    recipe: Recipe,
    sources: Sequence[Source],
    urls: Optional[Iterable[str]] = None,
    question: Optional[str] = None,
) -> str:
    """The whole finished prompt as one block of text, ready to paste."""
    return f"{_instructions(recipe, question)}\n\n{_material(recipe, sources, urls)}"


def build_messages(
    recipe: Recipe,
    sources: Sequence[Source],
    urls: Optional[Iterable[str]] = None,
    question: Optional[str] = None,
) -> list:
    """The same prompt, split the way a chat endpoint wants it.

    Built from the same two pieces as `build_prompt`, so what gets printed and
    what gets sent can never drift apart.
    """
    return [
        {"role": "system", "content": _instructions(recipe, question)},
        {"role": "user", "content": _material(recipe, sources, urls)},
    ]


def check_citations(text: str, n_sources: int):
    """Return (cited, unknown): source numbers used, and numbers that do not exist."""
    found = sorted({int(m) for m in re.findall(r"\[(\d+)\]", text)})
    cited = [n for n in found if 1 <= n <= n_sources]
    unknown = [n for n in found if n < 1 or n > n_sources]
    return cited, unknown


# ------------------------------------------------------------------ the model


def model_is_configured(base_url: Optional[str] = None, model: Optional[str] = None) -> bool:
    """True when there is somewhere to send the prompt.

    The flags win over the environment, which is how the CLI passes its own.
    """
    have_url = (base_url or os.environ.get("LLM_BASE_URL", "")).strip()
    have_model = (model or os.environ.get("LLM_MODEL", "")).strip()
    return bool(have_url and have_model)


def model_half_configured(base_url: Optional[str] = None, model: Optional[str] = None) -> str:
    """The missing half, when exactly one half of the model setup is present.

    Returns "" when both halves are set or neither is. A person who typed
    --model and nothing else was told "no model configured", which reads as
    the tool ignoring what they just typed, so the CLI now says which half
    is missing instead.
    """
    have_url = (base_url or os.environ.get("LLM_BASE_URL", "")).strip()
    have_model = (model or os.environ.get("LLM_MODEL", "")).strip()
    if have_url and not have_model:
        return "a model name: pass --model or set LLM_MODEL"
    if have_model and not have_url:
        return "an endpoint: pass --model-url or set LLM_BASE_URL"
    return ""


def call_model(
    messages: list,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout: float = 180.0,
) -> str:
    """Send the messages to any OpenAI-compatible chat completions endpoint."""
    base_url = (base_url or os.environ.get("LLM_BASE_URL", "")).rstrip("/")
    model = model or os.environ.get("LLM_MODEL", "")
    api_key = api_key if api_key is not None else os.environ.get("LLM_API_KEY", "")
    if not base_url or not model:
        raise ModelError(
            "no model configured: set LLM_BASE_URL and LLM_MODEL, "
            "or pass --model-url and --model"
        )
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    def post(payload_fields: dict):
        req = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=json.dumps(payload_fields).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    # Temperature 0 is what an agent that cites its sources wants: the same
    # pages should give the same answer. Some OpenAI-compatible endpoints
    # refuse the field outright, and the promise on the tin is that this runs
    # against any of them, so a refusal of the field is answered by sending
    # the request again without it rather than by failing the run.
    fields = {"model": model, "messages": messages, "temperature": 0}
    try:
        try:
            payload = post(fields)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code == 400 and "temperature" in detail.lower():
                payload = post({"model": model, "messages": messages})
            else:
                raise ModelError(f"model endpoint returned HTTP {e.code}: {detail}") from None
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise ModelError(f"model endpoint returned HTTP {e.code}: {detail}") from None
    except urllib.error.URLError as e:
        raise ModelError(f"could not reach the model endpoint: {e.reason}") from None
    try:
        return payload["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, AttributeError):
        raise ModelError("model endpoint answered in an unexpected shape") from None


# ------------------------------------------------------------------ the run


def read_for(
    recipe: Recipe,
    urls: Iterable[str],
    client: Optional[Lyrenth] = None,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    fresh: bool = False,
    question: Optional[str] = None,
) -> AgentResult:
    """Steps 1 and 2: read the pages and build the prompt. No model is called.

    This is the half that always works with a Lyrenth key alone, so the caller
    keeps the finished prompt even if the model step later fails.
    """
    urls = dedupe_urls(urls)
    gathered = gather(urls, client=client, token_budget=token_budget, fresh=fresh)
    return AgentResult(
        recipe=recipe,
        prompt=build_prompt(recipe, gathered.sources, urls, question),
        requested_urls=urls,
        sources=gathered.sources,
        skipped=gathered.skipped,
        tokens=gathered.tokens,
        raw_html_tokens=gathered.raw_html_tokens,
        question=question,
    )


def answer_into(
    result: AgentResult,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
) -> AgentResult:
    """Step 3: send the prompt the result already carries, and record the answer.

    Changes `result` in place and returns it. Raises ModelError if the call
    fails, leaving the prompt and the sources untouched.
    """
    if not result.sources:
        # Nothing was read, so there is nothing to work from, and no model is
        # called. answer stays None on purpose: a sentence here would sit in
        # the same field a real answer uses, and anyone reading answer without
        # also reading model_used would take our apology for a model's reply.
        # The reason goes in its own field, and the CLI turns it into a
        # non-zero exit.
        result.answer = None
        result.model_used = False
        result.no_sources_reason = (
            "None of the pages could be read, so there is nothing to work from."
        )
        return result
    text = call_model(
        build_messages(result.recipe, result.sources, result.requested_urls, result.question),
        base_url=base_url,
        model=model,
        api_key=api_key,
    )
    result.answer = text
    result.model_used = True
    result.cited, result.unknown_citations = check_citations(text, len(result.sources))
    return result


def run(
    recipe: Recipe,
    urls: Iterable[str],
    client: Optional[Lyrenth] = None,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    fresh: bool = False,
    question: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    use_model: bool = True,
) -> AgentResult:
    """Read the pages, build the prompt, and answer it if a model is configured.

    Raises ModelError only when a model was configured and the call to it
    failed. Having no model configured is not a failure: the prompt comes back
    and `answer` is None.
    """
    result = read_for(
        recipe, urls, client=client, token_budget=token_budget, fresh=fresh, question=question
    )
    if not use_model or not model_is_configured(base_url, model):
        return result
    return answer_into(result, base_url=base_url, model=model, api_key=api_key)
