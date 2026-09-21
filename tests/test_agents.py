"""Tests for lyrenth-agents. No network and no keys needed.

    python3 tests/test_agents.py      # plain, no pytest needed
    pytest tests/                     # if pytest is installed

Reading is tested against a fake Lyrenth client. The model step is tested
against a real HTTP server on localhost that speaks the OpenAI-compatible chat
completions protocol, so the request the engine sends is checked for real.

The recipes used here are fixtures defined in this file. They are not shipped
in the package: the real recipe text lives in lyrenth_agents.library, and these
tests install their own into the registry and put it back afterwards.
"""

import io
import json
import os
import sys
import threading
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "src"))
# Prefer the SDK from this monorepo when it is next door, else the installed one.
sdk = os.path.join(HERE, "..", "..", "lyrenth-python", "src")
if os.path.isdir(sdk):
    sys.path.insert(0, sdk)

# A model configured in the shell running the tests would change what the CLI
# does, so the tests start from nothing and pass what they need explicitly.
for _var in ("LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY"):
    os.environ.pop(_var, None)

from lyrenth import AIDocument, BatchResult  # noqa: E402

import lyrenth_agents.cli as cli  # noqa: E402
import lyrenth_agents.recipes as recipes_module  # noqa: E402
from lyrenth_agents.engine import build_sources_block  # noqa: E402
from lyrenth_agents import (  # noqa: E402
    Recipe,
    Source,
    UnknownRecipe,
    build_messages,
    build_prompt,
    check_citations,
    gather,
    get,
    model_is_configured,
    run,
)


# ---------------------------------------------------------------- fixtures

SUMMARY = Recipe(
    slug="test-summary",
    name="Test summary",
    category="Reading",
    tagline="Sum up a page in a few lines.",
    what_you_give="One or more pages.",
    what_you_get="A short summary with citations.",
    system_prompt="You summarise pages for a busy reader.",
    output_hint="Three bullet points, no longer.",
    example_urls=["https://example.com/a"],
    url_hint="Articles work better than home pages.",
)

COMPARE = Recipe(
    slug="test-compare",
    name="Test compare",
    category="Analysis",
    tagline="Put two pages side by side.",
    what_you_give="Two pages.",
    what_you_get="A table of differences.",
    system_prompt="You compare two pages.",
    output_hint="A two column table.",
)


@contextmanager
def installed(*items):
    """Swap the registry contents for the duration of one test."""
    saved = dict(recipes_module.REGISTRY)
    recipes_module.REGISTRY.clear()
    for r in items:
        recipes_module.REGISTRY[r.slug] = r
    try:
        yield
    finally:
        recipes_module.REGISTRY.clear()
        recipes_module.REGISTRY.update(saved)


def doc(canonical, title, text, tokens, raw=0, fetched="2026-09-21T12:00:00Z"):
    return AIDocument(
        url=canonical,
        title=title,
        markdown=text,
        raw={
            "source": {"url": canonical, "canonical_url": canonical, "fetched_at": fetched},
            "economics": {"output_tokens_approx": tokens, "raw_html_tokens_approx": raw},
        },
    )


class FakeClient:
    """Answers read_batch from a dict of url -> AIDocument, error string, or an
    (error code, explanation) pair for a failure that carries both."""

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def read_batch(self, urls, fresh=False, max_tokens=None):
        self.calls.append(list(urls))
        out = []
        for u in urls:
            v = self.pages.get(u, "upstream_not_found")
            if isinstance(v, tuple):
                out.append(BatchResult(url=u, ok=False, error=v[0], message=v[1]))
            elif isinstance(v, str):
                out.append(BatchResult(url=u, ok=False, error=v))
            else:
                out.append(BatchResult(url=u, ok=True, document=v))
        return out


A = "https://example.com/a"
A_MOBILE = "https://m.example.com/a"
B = "https://example.com/b"
C = "https://example.com/c"
MISSING = "https://example.com/missing"
FORBIDDEN = "https://example.com/forbidden"
FORBIDDEN_MESSAGE = (
    "example.com returned 403 to our crawler. This is usually bot protection, "
    "geo / consent gating, or a CDN rule, not necessarily a login wall."
)


def pages():
    return {
        A: doc(A, "Page A", "Alpha text.", 3000, 25000),
        A_MOBILE: doc(A, "Page A", "Alpha text.", 3000, 25000),
        B: doc(B, "Page B", "Beta text.", 20000, 80000),
        C: doc(C, "Page C", "Gamma text.", 16000, 40000),
    }


# ---------------------------------------------------------------- reading


def test_gather_dedupes_and_shares_the_budget_between_the_pages():
    # A is 3,000 tokens and takes only what it needs. The 27,000 left is split
    # between B and C, which are both over their share, so both are carried
    # and both are marked trimmed. The total lands exactly on the budget.
    g = gather([A, B, C, MISSING, A_MOBILE, A], client=FakeClient(pages()), token_budget=30000)
    assert [s.url for s in g.sources] == [A, B, C], g.sources
    assert [s.tokens for s in g.sources] == [3000, 13500, 13500]
    assert g.tokens == 30000
    assert [s.trimmed for s in g.sources] == [False, True, True]
    reasons = {s.url: s.reason for s in g.skipped}
    assert reasons[A_MOBILE] == f"duplicate of {A}"
    assert MISSING in reasons
    # The exact same URL given twice is read once, not reported as skipped.
    assert len(g.skipped) == 2


def test_a_failure_is_reported_with_the_message_not_the_code():
    # The code alone ("upstream_forbidden") tells a reader nothing about what
    # to do next, so the sentence wins when the API sends one.
    g = gather([FORBIDDEN], client=FakeClient({FORBIDDEN: ("upstream_forbidden", FORBIDDEN_MESSAGE)}))
    assert g.sources == []
    assert g.skipped[0].reason == FORBIDDEN_MESSAGE, g.skipped


def test_a_failure_without_a_message_falls_back_to_the_code():
    g = gather([MISSING], client=FakeClient({}))
    assert g.skipped[0].reason == "upstream_not_found"


# ---------------------------------------------------------------- the prompt


def test_build_prompt_carries_the_recipe_and_numbers_the_sources():
    prompt = build_prompt(SUMMARY, [Source(A, "Page A", "Alpha.", "2026-09-21T12:00:00Z")], [A])
    assert SUMMARY.system_prompt in prompt
    assert SUMMARY.output_hint in prompt
    assert "Cite every claim with the number of the source" in prompt
    assert "[1] Page A\nURL: https://example.com/a\nRead: 2026-09-21T12:00:00Z\n\nAlpha." in prompt
    # Nothing was missing, so there is no note claiming otherwise.
    assert "could not be read" not in prompt


def test_build_prompt_says_when_pages_are_missing():
    prompt = build_prompt(SUMMARY, [Source(A, "Page A", "Alpha.")], [A, B, MISSING])
    assert "2 of the 3 pages asked for could not be read" in prompt


def test_build_messages_is_the_same_text_split_in_two():
    sources = [Source(A, "Page A", "Alpha.")]
    messages = build_messages(SUMMARY, sources, [A])
    assert messages[0]["role"] == "system"
    assert SUMMARY.system_prompt in messages[0]["content"]
    joined = messages[0]["content"] + "\n\n" + messages[1]["content"]
    assert joined == build_prompt(SUMMARY, sources, [A])


def test_check_citations_flags_numbers_that_do_not_exist():
    cited, unknown = check_citations("Alpha [1]. Beta [2][2]. Nonsense [7]. Zero [0].", 2)
    assert cited == [1, 2] and unknown == [0, 7]


# ---------------------------------------------------------------- the registry


def test_unknown_slug_names_the_available_recipes():
    with installed(SUMMARY, COMPARE):
        try:
            get("nope")
        except UnknownRecipe as e:
            assert "test-compare, test-summary" in str(e), str(e)
        else:
            raise AssertionError("expected UnknownRecipe")


def test_unknown_slug_with_an_empty_registry_says_there_are_none():
    with installed():
        try:
            get("nope")
        except UnknownRecipe as e:
            assert "no recipes are installed at all" in str(e), str(e)
        else:
            raise AssertionError("expected UnknownRecipe")


def test_register_refuses_a_half_written_recipe():
    with installed():
        broken = Recipe(
            slug="broken",
            name="Broken",
            category="Reading",
            tagline="",
            what_you_give="x",
            what_you_get="x",
            system_prompt="x",
            output_hint="x",
        )
        try:
            recipes_module.register(broken)
        except ValueError as e:
            assert "tagline" in str(e)
        else:
            raise AssertionError("expected ValueError")


# ------------------------------------------- the seam the recipe library plugs into


@contextmanager
def library_module(name, body):
    """Write a throwaway recipe library on sys.path and import it by name."""
    import shutil
    import tempfile

    tmp = tempfile.mkdtemp()
    with open(os.path.join(tmp, name + ".py"), "w", encoding="utf-8") as fh:
        fh.write(body)
    sys.path.insert(0, tmp)
    try:
        yield name
    finally:
        sys.path.remove(tmp)
        sys.modules.pop(name, None)
        shutil.rmtree(tmp, ignore_errors=True)


RECIPE_SOURCE = (
    "from lyrenth_agents.recipes import Recipe\n"
    "ONE = Recipe(slug='from-library', name='From library', category='Reading',\n"
    "             tagline='t', what_you_give='g', what_you_get='r',\n"
    "             system_prompt='s', output_hint='o')\n"
)


def test_a_library_of_recipes_loads_as_a_list_or_as_a_dict():
    for tail in ("RECIPES = [ONE]\n", "RECIPES = {'from-library': ONE}\n"):
        with installed():
            with library_module("throwaway_recipes", RECIPE_SOURCE + tail) as name:
                assert recipes_module._load_library(name) is None
                assert get("from-library").name == "From library"


def test_a_library_that_does_not_import_is_reported_not_fatal():
    saved = recipes_module._LOAD_ERROR
    try:
        with installed():
            with library_module("throwaway_recipes", "raise RuntimeError('typo on line 4')") as name:
                problem = recipes_module._load_library(name)
            assert "typo on line 4" in problem, problem
            # The command still runs and explains itself instead of crashing.
            code, out, err = run_cli(["--list"])
            assert code == 0, err
            assert "No recipes are installed yet." in out
            assert "typo on line 4" in out
    finally:
        recipes_module._LOAD_ERROR = saved


def test_a_library_without_a_recipes_list_says_what_is_missing():
    saved = recipes_module._LOAD_ERROR
    try:
        with installed():
            with library_module("throwaway_recipes", "SOMETHING_ELSE = []\n") as name:
                problem = recipes_module._load_library(name)
            assert "does not define RECIPES" in problem, problem
    finally:
        recipes_module._LOAD_ERROR = saved


def test_a_missing_library_is_not_an_error():
    saved = recipes_module._LOAD_ERROR
    try:
        recipes_module._LOAD_ERROR = None
        assert recipes_module._load_library("no_such_recipe_library") is None
        assert recipes_module.load_error() is None
    finally:
        recipes_module._LOAD_ERROR = saved


# ---------------------------------------------------------------- run


def test_run_without_a_model_returns_the_prompt_and_no_answer():
    result = run(SUMMARY, [A, B], client=FakeClient(pages()))
    assert result.answer is None
    assert result.model_used is False
    assert SUMMARY.output_hint in result.prompt
    assert [s.url for s in result.sources] == [A, B]


def test_model_is_configured_needs_both_halves():
    assert model_is_configured("http://x/v1", "m") is True
    assert model_is_configured("http://x/v1", None) is False
    assert model_is_configured(None, "m") is False


# ---------------------------------------------------------------- a real HTTP model endpoint


class _Model(BaseHTTPRequestHandler):
    received = []
    reply = "Alpha says hello [1]."

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Model.received.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
        out = json.dumps({"choices": [{"message": {"role": "assistant", "content": _Model.reply}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


def _serve():
    srv = HTTPServer(("127.0.0.1", 0), _Model)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/v1"


def test_a_configured_model_gets_the_recipe_system_prompt():
    srv, url = _serve()
    try:
        _Model.received.clear()
        _Model.reply = "Alpha says hello [1]. Also [9]."
        result = run(COMPARE, [A, B], client=FakeClient(pages()), base_url=url, model="test-model")
        sent = _Model.received[0]
        assert sent["path"] == "/v1/chat/completions"
        assert sent["body"]["model"] == "test-model" and sent["body"]["temperature"] == 0
        assert COMPARE.system_prompt in sent["body"]["messages"][0]["content"]
        assert COMPARE.output_hint in sent["body"]["messages"][1]["content"]
        assert "[2] Page B" in sent["body"]["messages"][1]["content"]
        assert result.model_used is True
        assert result.cited == [1] and result.unknown_citations == [9]
    finally:
        srv.shutdown()


class _FussyModel(BaseHTTPRequestHandler):
    """An endpoint that refuses the temperature field, as some real ones do."""

    received = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _FussyModel.received.append(body)
        if "temperature" in body:
            out = json.dumps(
                {"error": {"message": "`temperature` is deprecated for this model."}}
            ).encode()
            self.send_response(400)
        else:
            out = json.dumps(
                {"choices": [{"message": {"role": "assistant", "content": "Alpha [1]."}}]}
            ).encode()
            self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


def test_an_endpoint_that_refuses_temperature_still_answers():
    # "Point it at any OpenAI-compatible endpoint" is a promise on the site,
    # and one of the large providers answers 400 to the temperature field.
    # Before this, that was a failed run with an HTTP 400 on the screen.
    srv = HTTPServer(("127.0.0.1", 0), _FussyModel)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/v1"
    try:
        _FussyModel.received.clear()
        result = run(COMPARE, [A, B], client=FakeClient(pages()), base_url=url, model="fussy")
        assert result.answer == "Alpha [1]."
        assert result.model_used is True
        assert len(_FussyModel.received) == 2
        assert "temperature" in _FussyModel.received[0]
        assert "temperature" not in _FussyModel.received[1]
    finally:
        srv.shutdown()


# ---------------------------------------------------------------- the command line


@contextmanager
def fake_reader(client=None):
    real = cli.Lyrenth
    cli.Lyrenth = lambda: client or FakeClient(pages())
    try:
        yield
    finally:
        cli.Lyrenth = real


def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


def test_cli_one_key_path_prints_the_prompt_and_exits_zero():
    # No model configured anywhere: the point of the whole package.
    with installed(SUMMARY), fake_reader():
        code, out, err = run_cli(["test-summary", A, B])
    assert code == 0, err
    assert SUMMARY.system_prompt in out
    assert SUMMARY.output_hint in out
    assert "[1] Page A" in out and "[2] Page B" in out
    # What it produced and what to do with it, on stderr so the prompt pipes clean.
    assert "no model configured" in err
    assert "paste that prompt into the assistant you use" in err
    assert "LLM_BASE_URL" in err
    assert "no model configured" not in out


def test_a_page_with_no_title_prints_its_url_instead_of_a_hole():
    # Not every page has a title. www.rfc-editor.org/rfc/rfc7258.html is one
    # long <pre> block with no head at all, and printing its empty title left
    # "read [1]   16,000 tokens" with a gap where a name should be.
    untitled = doc(A, "", "Alpha text.", 3000)
    with installed(SUMMARY), fake_reader(FakeClient({A: untitled})):
        code, out, err = run_cli(["test-summary", A])
    assert code == 0, err
    assert f"read [1] 3,000 tokens  {A}" in err, err
    assert "[1]   " not in err and "[1]   " not in out

def test_cli_reports_a_page_it_could_not_read_with_the_message():
    client = FakeClient({A: pages()[A], FORBIDDEN: ("upstream_forbidden", FORBIDDEN_MESSAGE)})
    with installed(SUMMARY), fake_reader(client):
        code, out, err = run_cli(["test-summary", A, FORBIDDEN])
    assert code == 0, err
    assert f"skipped  {FORBIDDEN}: {FORBIDDEN_MESSAGE}" in err
    assert "upstream_forbidden" not in err
    # The prompt admits the gap instead of hiding it.
    assert "1 of the 2 pages asked for could not be read" in out


def test_cli_with_a_model_prints_the_answer_and_the_sources():
    srv, url = _serve()
    try:
        _Model.reply = "Alpha is first [1]."
        with installed(SUMMARY), fake_reader():
            code, out, err = run_cli(["test-summary", A, B, "--model-url", url, "--model", "m"])
        assert code == 0, err
        assert "Alpha is first [1]." in out
        assert "[2] Page B  https://example.com/b  (not cited)" in out
    finally:
        srv.shutdown()


def test_cli_list_prints_every_registered_recipe():
    with installed(SUMMARY, COMPARE):
        code, out, err = run_cli(["--list"])
        assert code == 0, err
        for r in (SUMMARY, COMPARE):
            assert r.slug in out and r.tagline in out
        assert "Analysis" in out and "Reading" in out

        code, out, err = run_cli(["--list", "--json"])
        assert code == 0, err
        payload = json.loads(out)
        assert sorted(r["slug"] for r in payload) == ["test-compare", "test-summary"]


def test_cli_list_with_no_recipes_says_so_instead_of_crashing():
    with installed():
        code, out, err = run_cli(["--list"])
    assert code == 0, err
    assert "No recipes are installed yet." in out


def test_cli_unknown_slug_fails_with_a_clear_message():
    with installed(SUMMARY, COMPARE):
        code, out, err = run_cli(["nope", A])
    assert code == 2
    assert "no recipe named 'nope'" in err
    assert "test-compare, test-summary" in err


def test_cli_without_urls_shows_what_the_recipe_needs():
    with installed(SUMMARY):
        code, out, err = run_cli(["test-summary"])
    assert code == 2
    assert SUMMARY.what_you_give in err
    assert SUMMARY.what_you_get in err
    assert SUMMARY.url_hint in err
    assert f"Try: lyrenth-agents test-summary {A}" in err


def test_cli_without_a_recipe_points_at_the_list():
    code, out, err = run_cli([])
    assert code == 2
    assert "--list" in err


def test_cli_sources_only_prints_the_sources_and_no_prompt():
    with installed(SUMMARY), fake_reader():
        code, out, err = run_cli(["test-summary", A, "--sources-only"])
    assert code == 0, err
    assert "[1] Page A" in out
    assert SUMMARY.output_hint not in out

    with installed(SUMMARY), fake_reader():
        code, out, err = run_cli(["test-summary", A, MISSING, "--sources-only", "--json"])
    assert code == 0, err
    payload = json.loads(out)
    assert [s["url"] for s in payload["sources"]] == [A]
    assert payload["skipped"][0]["reason"] == "upstream_not_found"


def test_cli_json_without_a_model_carries_the_prompt_and_a_null_answer():
    with installed(SUMMARY), fake_reader():
        code, out, err = run_cli(["test-summary", A, "--json"])
    assert code == 0, err
    payload = json.loads(out)
    assert payload["answer"] is None
    assert payload["model_used"] is False
    assert SUMMARY.output_hint in payload["prompt"]


def test_cli_keeps_the_prompt_when_a_configured_model_fails():
    # Port 9 refuses connections, which is what an unreachable endpoint looks like.
    with installed(SUMMARY), fake_reader():
        code, out, err = run_cli(["test-summary", A, "--model-url", "http://127.0.0.1:9/v1", "--model", "m"])
    assert code == 1
    assert "could not reach the model endpoint" in err
    assert SUMMARY.output_hint in out



# ------------------------------------------------- defects found in review

def test_half_a_model_setup_is_an_error_not_a_silent_fallback():
    # Typing --model with no endpoint used to print "no model configured",
    # which reads as the tool ignoring what was just typed.
    saved = {k: os.environ.pop(k, None) for k in ("LLM_BASE_URL", "LLM_MODEL")}
    try:
        out, err = io.StringIO(), io.StringIO()
        with fake_reader(), redirect_stdout(out), redirect_stderr(err):
            code = cli.main(["compare", A, B, "--model", "some-model"])
        assert code == 2, (code, err.getvalue())
        assert "endpoint" in err.getvalue(), err.getvalue()
        assert "no model configured" not in err.getvalue().lower()
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def test_every_page_failing_is_a_non_zero_exit():
    # A prompt whose sources read "none" plus exit 0 tells a script the run
    # went fine.
    saved = {k: os.environ.pop(k, None) for k in ("LLM_BASE_URL", "LLM_MODEL")}
    try:
        out, err = io.StringIO(), io.StringIO()
        with fake_reader(FakeClient({})), redirect_stdout(out), redirect_stderr(err):
            code = cli.main(["compare", MISSING])
        assert code == 1, (code, err.getvalue())
        assert "none of the pages could be read" in err.getvalue().lower()
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def test_nothing_read_leaves_answer_null_and_gives_a_reason():
    from lyrenth_agents.engine import AgentResult, answer_into
    from lyrenth_agents.recipes import get

    result = AgentResult(recipe=get("compare"), prompt="p")
    answer_into(result, base_url="http://127.0.0.1:9", model="m")
    assert result.answer is None
    assert result.model_used is False
    assert "could be read" in (result.no_sources_reason or "")

# ------------------------------------------------- the recipes that ship

# The six categories the site can draw. The union lives in
# frontend/src/components/marketing/agent-icon.tsx, and the gallery data in
# frontend/src/lib/agents-data.ts imports it from there, so a seventh invented
# in a recipe would reach the site with no glyph to draw it.
SITE_CATEGORIES = {"research", "comparison", "company", "docs", "content", "data"}

# What makes a recipe worth shipping, rather than merely valid. register() in
# recipes.py already refuses an empty field; these are the thin-recipe checks
# it cannot make on its own.
MIN_PROMPT_CHARS = 200
MIN_EXAMPLE_URLS = 2

# Every field a shipped recipe must carry, including the two the dataclass
# leaves optional because a half-written record should still import.
SHIPPED_TEXT_FIELDS = recipes_module.REQUIRED_TEXT_FIELDS + ("url_hint",)


def shipped():
    """The recipes the package actually installs, read the way the CLI reads them."""
    from lyrenth_agents.library import RECIPES

    items = list(RECIPES.values()) if isinstance(RECIPES, dict) else list(RECIPES)
    assert items, "the shipped recipe library is empty"
    return items


def test_every_shipped_recipe_is_registered_under_its_own_slug():
    assert recipes_module.load_error() is None, recipes_module.load_error()
    for r in shipped():
        assert get(r.slug) is r, r.slug


def test_every_shipped_recipe_has_every_field_filled():
    for r in shipped():
        for f in SHIPPED_TEXT_FIELDS:
            assert str(getattr(r, f, "") or "").strip(), f"{r.slug}: {f} is empty"


def test_every_shipped_prompt_is_long_enough_to_say_something():
    # A one line prompt ("summarise the following") produces output nobody
    # keeps. The length is a floor to catch a thin recipe, not a target.
    for r in shipped():
        length = len(r.system_prompt.strip())
        assert length >= MIN_PROMPT_CHARS, f"{r.slug}: system_prompt is {length} characters"


def test_every_shipped_recipe_carries_example_urls_that_can_be_pasted():
    # The site prints the first two inside a command a visitor is invited to
    # run, so a recipe with one example, or with the same page twice, ships a
    # command that does not show what the recipe does.
    for r in shipped():
        assert len(r.example_urls) >= MIN_EXAMPLE_URLS, f"{r.slug}: {r.example_urls}"
        assert len(set(r.example_urls)) == len(r.example_urls), f"{r.slug}: a repeated example URL"
        for u in r.example_urls:
            assert u.startswith("https://"), f"{r.slug}: {u} is not an absolute https URL"


def test_every_shipped_category_is_one_the_site_can_draw():
    for r in shipped():
        assert r.category in SITE_CATEGORIES, f"{r.slug}: unknown category {r.category!r}"


def test_no_shipped_recipe_text_carries_a_long_dash():
    # House rule for the whole repository: no em-dash and no en-dash anywhere.
    # This text is printed in the terminal and copied onto the site, so the
    # rule is checked here rather than trusted.
    for r in shipped():
        for f in SHIPPED_TEXT_FIELDS:
            text = str(getattr(r, f, "") or "")
            for bad, name in (("—", "em dash"), ("–", "en dash")):
                assert bad not in text, f"{r.slug}: {f} contains an {name}"



def test_a_question_reaches_the_prompt_and_the_model():
    # answers and research are useless without one, and before --question the
    # only way to ask was to type it above the printed prompt by hand.
    out, err = io.StringIO(), io.StringIO()
    saved = {k: os.environ.pop(k, None) for k in ("LLM_BASE_URL", "LLM_MODEL")}
    try:
        with fake_reader(), redirect_stdout(out), redirect_stderr(err):
            code = cli.main(["answers", A, B, "--question", "How do I rotate a key?"])
        assert code == 0, (code, err.getvalue())
        assert "Question: How do I rotate a key?" in out.getvalue(), out.getvalue()[:400]
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v

    # The same question must reach a configured model, or the printed prompt
    # and the sent one would disagree.
    from lyrenth_agents.engine import build_messages, read_for
    from lyrenth_agents.recipes import get

    result = read_for(get("answers"), [A], client=FakeClient(pages()), question="Ask this")
    system = build_messages(result.recipe, result.sources, result.requested_urls, result.question)[0]
    assert "Question: Ask this" in system["content"], system["content"][:200]


def test_no_question_leaves_the_prompt_as_it_was():
    result_prompt = None
    with fake_reader():
        from lyrenth_agents.engine import read_for
        from lyrenth_agents.recipes import get

        result_prompt = read_for(get("compare"), [A], client=FakeClient(pages())).prompt
    assert "Question:" not in result_prompt


def test_a_page_too_long_for_the_budget_is_trimmed_not_dropped():
    # Two long pages used to produce nothing at all, which is the worst
    # possible first run for the compare recipe on its own example URLs.
    from lyrenth_agents.engine import gather

    long_doc = doc(A, "Long A", "x " * 20000, 40000, 120000)
    g = gather([A], client=FakeClient({A: long_doc}), token_budget=10000)
    assert len(g.sources) == 1, g.skipped
    src = g.sources[0]
    assert src.trimmed is True
    assert src.tokens == 10000
    assert len(src.text) <= 40000
    assert "longer than the budget" in build_sources_block(g.sources)


def test_a_page_is_still_skipped_when_the_budget_cannot_carry_it():
    # Five pages against a budget with room for two: the first two are read,
    # and the three that were dropped say why instead of vanishing.
    from lyrenth_agents.engine import gather

    urls = [f"https://example.com/p{i}" for i in range(5)]
    pages_ = {u: doc(u, u, "text " * 100, 9000) for u in urls}
    g = gather(urls, client=FakeClient(pages_), token_budget=4000)
    assert [s.url for s in g.sources] == urls[:2]
    assert [s.tokens for s in g.sources] == [2000, 2000]
    assert [s.reason for s in g.skipped] == ["no room left in the 4,000 token budget"] * 3


def test_two_long_pages_both_make_it_in():
    # The compare recipe's own example pages are two long Wikipedia articles.
    # Giving the first one whatever was left meant the second was skipped and
    # the answer came back as a table with one column saying "not stated on
    # the pages given" all the way down. Both pages now get half the budget.
    from lyrenth_agents.engine import gather

    first = doc(A, "A", "alpha " * 20000, 40000)
    second = doc(B, "B", "beta " * 20000, 35000)
    g = gather([A, B], client=FakeClient({A: first, B: second}), token_budget=20000)
    assert [s.url for s in g.sources] == [A, B], g.skipped
    assert [s.tokens for s in g.sources] == [10000, 10000]
    assert all(s.trimmed for s in g.sources)
    assert g.skipped == []


def test_a_short_page_hands_its_leftover_to_a_long_one():
    # This one passed before the change too: it pins the redistribution rule
    # against a plain equal split, which would have handed each page 10,000
    # and thrown 7,000 of the budget away.
    from lyrenth_agents.engine import gather

    short = doc(A, "A", "alpha " * 100, 3000)
    long_ = doc(B, "B", "beta " * 20000, 40000)
    g = gather([A, B], client=FakeClient({A: short, B: long_}), token_budget=20000)
    assert [s.tokens for s in g.sources] == [3000, 17000]
    assert [s.trimmed for s in g.sources] == [False, True]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} passed")
