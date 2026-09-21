"""Agents that do more than one thing.

A recipe answers one question about some pages. A flow is a short list of
steps that pass their work along, so one agent can read, then think about
what it read, then do something with the result.

Three kinds of step, and only the first one costs a read:

    Read     pull the pages through Lyrenth into the bag, once per run
    Think    run a model over what is already in the bag, reading nothing
    Act      do something outside this engine: write a file, and later
             post a message, open a pull request, send a draft

THE BAG. Every step writes its result into the bag under its own name, and
every later step can use it. The sources are in the bag too, with the
numbers the first step gave them, so a citation written in step two still
points at the right page when step four writes it into a file.

WHAT A LATER STEP IS SENT. A Think step names what it uses. Asking for
"sources" sends the page text itself. Asking for an earlier step's name
sends what that step wrote. Either way the step is also given the compact
list of numbered sources, so it can cite without being handed the pages
again: sending 60,000 tokens of article to every step of a four step flow
would be money burned for nothing.

WHERE AN ACTION IS ALLOWED TO PUT THINGS. Never anywhere a model said.
A page this agent read can contain any sentence at all, including one
addressed to the model, so the destination of an action (the path, and
later the channel, the address, the repository) comes only from the flow
or from the command line. The model writes what goes in the message. It
never writes where the message goes. This is enforced here, in the
runner, rather than left to each action to remember.

NOTHING HAPPENS UNLESS IT IS ASKED FOR. An Act step is dry by default: it
says what it would do and stops. `confirm=True` (`--yes` on the command
line) performs it. A command someone pasted off our website never sends,
pushes or posts on its own.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from lyrenth import Lyrenth

from .engine import (
    CITATION_RULE,
    DEFAULT_TOKEN_BUDGET,
    Skipped,
    Source,
    build_sources_block,
    call_model,
    check_citations,
    dedupe_urls,
    gather,
    model_is_configured,
)

__all__ = [
    "Act",
    "ACTIONS",
    "Flow",
    "FlowError",
    "FlowResult",
    "Read",
    "StepResult",
    "Think",
    "build_source_index",
    "build_step_messages",
    "flow_for_recipe",
    "run_flow",
]


class FlowError(ValueError):
    """A flow that cannot run as written, caught before anything is read."""


# ------------------------------------------------------------------ the steps


@dataclass
class Read:
    """Read the pages the caller gave, into the bag under `name`."""

    name: str = "sources"


@dataclass
class Think:
    """Ask a model about what is already in the bag. Reads nothing."""

    name: str
    prompt: str
    output_hint: str
    # Bag keys this step is given. "sources" means the pages themselves;
    # anything else is an earlier step's result.
    uses: Tuple[str, ...] = ("sources",)


@dataclass
class Act:
    """Do something outside this engine with what an earlier step wrote."""

    name: str
    action: str
    uses: str
    # Literal settings from the flow. Never filled in from the bag: see the
    # note at the top of this file.
    config: Dict[str, str] = field(default_factory=dict)


Step = Union[Read, Think, Act]


@dataclass
class Flow:
    """One agent: what it is for, and the steps it runs."""

    slug: str
    name: str
    category: str
    tagline: str
    what_you_give: str
    what_you_get: str
    steps: List[Step]
    example_urls: List[str] = field(default_factory=list)
    url_hint: Optional[str] = None


# ------------------------------------------------------------------ results


@dataclass
class StepResult:
    name: str
    kind: str
    # What the step produced. A Think step's answer, or a line describing
    # what an Act step did or would do.
    text: str = ""
    # A Think step's finished prompt, filled whether or not a model ran, so
    # the one-key path still hands back something usable.
    prompt: str = ""
    model_used: bool = False
    performed: bool = False
    cited: List[int] = field(default_factory=list)
    unknown_citations: List[int] = field(default_factory=list)
    note: str = ""


@dataclass
class FlowResult:
    flow: Flow
    requested_urls: List[str] = field(default_factory=list)
    sources: List[Source] = field(default_factory=list)
    skipped: List[Skipped] = field(default_factory=list)
    steps: List[StepResult] = field(default_factory=list)
    question: Optional[str] = None
    # Set when the flow could not carry on: no model for a Think step, or
    # nothing readable to work from. The steps that did run are still here.
    stopped_at: Optional[str] = None
    stopped_reason: Optional[str] = None

    @property
    def answer(self) -> Optional[str]:
        """What the last thinking step wrote, or None if none of them ran."""
        for step in reversed(self.steps):
            if step.kind == "think" and step.model_used:
                return step.text
        return None

    @property
    def tokens(self) -> int:
        return sum(s.tokens for s in self.sources)

    @property
    def raw_html_tokens(self) -> int:
        return sum(s.raw_html_tokens for s in self.sources)

    def value(self, name: str) -> str:
        for step in self.steps:
            if step.name == name:
                return step.text
        return ""


# ------------------------------------------------------------------ actions

# An action is a pair of functions over (payload, config): one says what it
# would do, the other does it. Both are given only the payload from the bag
# and the literal config, which is what keeps a page from choosing a
# destination.
Describe = Callable[[str, Dict[str, str]], str]
Perform = Callable[[str, Dict[str, str]], str]


@dataclass
class Action:
    describe: Describe
    perform: Perform
    needs: Tuple[str, ...] = ()


def _safe_path(config: Dict[str, str]) -> str:
    path = (config.get("path") or "").strip()
    if not path:
        raise FlowError("this step needs a path to write to")
    if os.path.isabs(path) or ".." in path.split(os.sep):
        raise FlowError(f"refusing to write outside the working directory: {path}")
    return path


def _describe_write(payload: str, config: Dict[str, str]) -> str:
    path = _safe_path(config)
    lines = len(payload.splitlines())
    return f"write {path} ({len(payload):,} bytes, {lines} lines)"


def _perform_write(payload: str, config: Dict[str, str]) -> str:
    path = _safe_path(config)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(payload if payload.endswith("\n") else payload + "\n")
    return f"wrote {path} ({len(payload):,} bytes)"


ACTIONS: Dict[str, Action] = {
    "write_file": Action(describe=_describe_write, perform=_perform_write, needs=("path",)),
}


# ------------------------------------------------------------------ prompts


def build_source_index(sources: Sequence[Source]) -> str:
    """The numbered sources without their text, so a citation still resolves."""
    if not sources:
        return "No sources were read."
    lines = [f"[{i}] {s.title or s.url}  {s.url}" for i, s in enumerate(sources, 1)]
    return "The numbered sources behind any citation in the text above:\n" + "\n".join(lines)


def build_step_messages(
    step: Think,
    bag: Dict[str, str],
    sources: Sequence[Source],
    question: Optional[str] = None,
) -> list:
    """What one thinking step is sent: its instructions, its inputs, its hint."""
    parts = []
    if question and question.strip():
        parts.append(f"Question: {question.strip()}")
    wants_pages = "sources" in step.uses
    for key in step.uses:
        if key == "sources":
            continue
        parts.append(f"### {key}\n\n{bag.get(key, '').strip()}")
    if wants_pages:
        parts.append(f"Sources:\n\n{build_sources_block(sources)}")
    else:
        parts.append(build_source_index(sources))
    parts.append(step.output_hint)
    return [
        {"role": "system", "content": f"{step.prompt}\n\n{CITATION_RULE}"},
        {"role": "user", "content": "\n\n".join(p for p in parts if p.strip())},
    ]


# ------------------------------------------------------------------ the runner


def validate(flow: Flow) -> None:
    """Refuse a flow that cannot work, before anything is read or paid for."""
    if not flow.steps:
        raise FlowError(f"flow {flow.slug!r} has no steps")
    reads = [s for s in flow.steps if isinstance(s, Read)]
    if len(reads) > 1:
        raise FlowError(f"flow {flow.slug!r} reads twice; a run reads its pages once")
    if reads and not isinstance(flow.steps[0], Read):
        raise FlowError(f"flow {flow.slug!r} reads after another step; reading comes first")
    seen = {"sources"} if reads else set()
    for step in flow.steps:
        if isinstance(step, Read):
            seen.add(step.name)
            continue
        if isinstance(step, Think):
            for key in step.uses:
                if key not in seen:
                    raise FlowError(
                        f"step {step.name!r} uses {key!r}, which no earlier step produced"
                    )
        if isinstance(step, Act):
            if step.action not in ACTIONS:
                raise FlowError(f"step {step.name!r} names an unknown action {step.action!r}")
            if step.uses not in seen:
                raise FlowError(
                    f"step {step.name!r} uses {step.uses!r}, which no earlier step produced"
                )
            for key in ACTIONS[step.action].needs:
                if not (step.config.get(key) or "").strip():
                    raise FlowError(f"step {step.name!r} needs {key!r} in its config")
        if step.name in seen:
            raise FlowError(f"flow {flow.slug!r} has two steps called {step.name!r}")
        seen.add(step.name)


def run_flow(
    flow: Flow,
    urls: Iterable[str],
    client: Optional[Lyrenth] = None,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    fresh: bool = False,
    question: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    use_model: bool = True,
    confirm: bool = False,
    overrides: Optional[Dict[str, Dict[str, str]]] = None,
    on_step: Optional[Callable[["StepResult"], None]] = None,
) -> FlowResult:
    """Run every step in order, carrying one bag of values through them.

    `overrides` is how the command line changes an action's settings, by step
    name. It is the only way config is changed at run time, and it never
    comes from the bag.

    `on_step` is called as each step finishes, so a long flow can say where
    it is instead of going quiet for a minute.
    """
    def done(step_result: "StepResult") -> "StepResult":
        result.steps.append(step_result)
        if on_step:
            on_step(step_result)
        return step_result

    validate(flow)
    urls = dedupe_urls(urls)
    result = FlowResult(flow=flow, requested_urls=list(urls), question=question)
    bag: Dict[str, str] = {}
    has_model = use_model and model_is_configured(base_url, model)

    for step in flow.steps:
        if isinstance(step, Read):
            gathered = gather(urls, client=client, token_budget=token_budget, fresh=fresh)
            result.sources = gathered.sources
            result.skipped = gathered.skipped
            detail = f"{len(gathered.sources)} pages read"
            done(StepResult(name=step.name, kind="read", note=detail))
            if not gathered.sources:
                result.stopped_at = step.name
                result.stopped_reason = (
                    "None of the pages could be read, so there is nothing to work from."
                )
                return result
            continue

        if isinstance(step, Think):
            messages = build_step_messages(step, bag, result.sources, question)
            prompt = f"{messages[0]['content']}\n\n{messages[1]['content']}"
            if not has_model:
                done(StepResult(name=step.name, kind="think", prompt=prompt))
                result.stopped_at = step.name
                result.stopped_reason = (
                    "No model is configured, so the flow stopped here and printed the "
                    "prompt for this step. Set LLM_BASE_URL and LLM_MODEL to run it "
                    "through."
                )
                return result
            text = call_model(messages, base_url=base_url, model=model, api_key=api_key)
            cited, unknown = check_citations(text, len(result.sources))
            bag[step.name] = text
            done(
                StepResult(
                    name=step.name,
                    kind="think",
                    text=text,
                    prompt=prompt,
                    model_used=True,
                    cited=cited,
                    unknown_citations=unknown,
                )
            )
            continue

        # Act. The payload is what an earlier step wrote; the settings are the
        # flow's own, plus anything the command line overrode by step name.
        payload = bag.get(step.uses, "")
        config = dict(step.config)
        config.update((overrides or {}).get(step.name, {}))
        action = ACTIONS[step.action]
        if not payload.strip():
            done(
                StepResult(
                    name=step.name,
                    kind="act",
                    note=f"nothing to {step.action}: {step.uses} is empty",
                )
            )
            continue
        line = action.describe(payload, config)
        if not confirm:
            done(StepResult(name=step.name, kind="act", text=f"would {line}", note="dry run"))
            continue
        performed_line = action.perform(payload, config)
        done(StepResult(name=step.name, kind="act", text=performed_line, performed=True))

    return result


def flow_for_recipe(recipe) -> Flow:
    """The old one-question recipe, as a flow: read the pages, answer once.

    Every recipe in the library is still exactly this, which is why nothing
    on the website changed when flows arrived.
    """
    return Flow(
        slug=recipe.slug,
        name=recipe.name,
        category=recipe.category,
        tagline=recipe.tagline,
        what_you_give=recipe.what_you_give,
        what_you_get=recipe.what_you_get,
        example_urls=list(recipe.example_urls),
        url_hint=recipe.url_hint,
        steps=[
            Read(),
            Think(
                name="answer",
                prompt=recipe.system_prompt,
                output_hint=recipe.output_hint,
                uses=("sources",),
            ),
        ],
    )
