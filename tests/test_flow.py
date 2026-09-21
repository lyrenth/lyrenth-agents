"""Tests for flows: agents with more than one step. No network, no keys.

    python3 tests/test_flow.py
    pytest tests/

Reading is tested against a fake Lyrenth client. The model is a function
this file swaps in, because what matters here is not the HTTP protocol
(tested in test_agents.py) but what each step is sent and what happens to
what it returns.
"""

import os
import sys
import tempfile

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "src"))
sdk = os.path.join(HERE, "..", "..", "lyrenth-python", "src")
if os.path.isdir(sdk):
    sys.path.insert(0, sdk)

from lyrenth import AIDocument, BatchResult  # noqa: E402

import lyrenth_agents.flow as flow_module  # noqa: E402
from lyrenth_agents.flow import (  # noqa: E402
    Act,
    Flow,
    FlowError,
    Read,
    Think,
    flow_for_recipe,
    run_flow,
)
from lyrenth_agents.recipes import all_recipes  # noqa: E402

A = "https://example.com/a"
B = "https://example.com/b"
MODEL = {"base_url": "http://model.test/v1", "model": "test-model"}


def doc(url, title, text, tokens, raw=0):
    return AIDocument(
        url=url,
        title=title,
        markdown=text,
        raw={
            "source": {"url": url, "canonical_url": url, "fetched_at": "2026-09-21T12:00:00Z"},
            "economics": {"output_tokens_approx": tokens, "raw_html_tokens_approx": raw},
        },
    )


class FakeClient:
    def __init__(self, pages=None):
        self.pages = pages if pages is not None else {
            A: doc(A, "Page A", "Alpha text.", 3000, 25000),
            B: doc(B, "Page B", "Beta text.", 4000, 30000),
        }
        self.calls = []

    def read_batch(self, urls, fresh=False, max_tokens=None):
        self.calls.append(list(urls))
        out = []
        for u in urls:
            v = self.pages.get(u, "upstream_not_found")
            if isinstance(v, str):
                out.append(BatchResult(url=u, ok=False, error=v))
            else:
                out.append(BatchResult(url=u, ok=True, document=v))
        return out


class FakeModel:
    """Records every call and answers from a list of replies."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, messages, base_url=None, model=None, api_key=None, timeout=180.0):
        self.calls.append(messages)
        return self.replies[len(self.calls) - 1] if len(self.calls) <= len(self.replies) else "ok"


def with_model(fake):
    """Swap the model call out for the duration of one test."""
    real = flow_module.call_model
    flow_module.call_model = fake
    return real


def restore(real):
    flow_module.call_model = real


def three_step(path="out/report.md"):
    return Flow(
        slug="report",
        name="Report",
        category="data",
        tagline="Read, think, write.",
        what_you_give="Two pages.",
        what_you_get="A file.",
        example_urls=[A, B],
        steps=[
            Read(),
            Think(name="facts", prompt="List the facts.", output_hint="A list.", uses=("sources",)),
            Think(
                name="memo",
                prompt="Write a memo from the facts.",
                output_hint="A memo.",
                uses=("facts",),
            ),
            Act(name="file", action="write_file", uses="memo", config={"path": path}),
        ],
    )


# ---------------------------------------------------------------- the bag


def test_a_flow_reads_once_and_carries_the_work_forward():
    # The whole point: the second thinking step works from what the first
    # one wrote, and nothing is read a second time to get it.
    client = FakeClient()
    fake = FakeModel("FACTS: alpha and beta [1][2].", "MEMO built on the facts.")
    real = with_model(fake)
    try:
        r = run_flow(three_step(), [A, B], client=client, **MODEL)
    finally:
        restore(real)

    assert len(client.calls) == 1, client.calls
    assert [s.kind for s in r.steps] == ["read", "think", "think", "act"]
    assert r.value("facts") == "FACTS: alpha and beta [1][2]."
    assert r.answer == "MEMO built on the facts."
    # the memo step was handed the facts, and was not handed the pages again
    memo_user = fake.calls[1][1]["content"]
    assert "FACTS: alpha and beta" in memo_user
    assert "Alpha text." not in memo_user
    assert r.stopped_at is None


def test_a_later_step_still_gets_the_numbers_behind_the_citations():
    # A step that does not need the pages still needs to know what [1] is,
    # or the citations it copies forward point at nothing.
    client = FakeClient()
    fake = FakeModel("Alpha is true [1].", "The memo, citing [1].")
    real = with_model(fake)
    try:
        run_flow(three_step(), [A, B], client=client, **MODEL)
    finally:
        restore(real)
    memo_user = fake.calls[1][1]["content"]
    assert "[1] Page A  https://example.com/a" in memo_user
    assert "[2] Page B  https://example.com/b" in memo_user


# ---------------------------------------------------------------- acting


def test_an_action_is_dry_until_it_is_confirmed():
    client = FakeClient()
    # Two runs in this test, two thinking steps each.
    fake = FakeModel("facts", "the memo", "facts", "the memo")
    real = with_model(fake)
    with tempfile.TemporaryDirectory() as tmp:
        here = os.getcwd()
        os.chdir(tmp)
        try:
            r = run_flow(three_step(), [A, B], client=client, **MODEL)
            act = r.steps[-1]
            assert act.performed is False
            assert act.text.startswith("would write out/report.md")
            assert not os.path.exists("out/report.md"), "a dry run wrote a file"

            r = run_flow(three_step(), [A, B], client=client, confirm=True, **MODEL)
            act = r.steps[-1]
            assert act.performed is True
            assert open("out/report.md").read().strip() == "the memo"
        finally:
            os.chdir(here)
            restore(real)


def test_an_action_writes_where_the_flow_says_not_where_the_model_says():
    # A page an agent reads can say anything, including a path. The model
    # writes what goes in the file. It never writes where the file goes.
    client = FakeClient()
    fake = FakeModel("facts", "path: /etc/passwd\n../../elsewhere.md\nthe memo")
    real = with_model(fake)
    with tempfile.TemporaryDirectory() as tmp:
        here = os.getcwd()
        os.chdir(tmp)
        try:
            r = run_flow(three_step(), [A, B], client=client, confirm=True, **MODEL)
            assert r.steps[-1].performed is True
            assert os.path.exists("out/report.md")
            assert not os.path.exists("elsewhere.md")
            assert "/etc/passwd" in open("out/report.md").read(), "the text itself is untouched"
        finally:
            os.chdir(here)
            restore(real)


def test_an_action_refuses_to_write_outside_the_working_directory():
    for path in ("/tmp/escape.md", "../escape.md"):
        client = FakeClient()
        fake = FakeModel("facts", "the memo")
        real = with_model(fake)
        try:
            raised = None
            try:
                run_flow(three_step(path), [A, B], client=client, confirm=True, **MODEL)
            except FlowError as e:
                raised = e
            assert raised is not None, f"{path} was allowed"
            assert "outside the working directory" in str(raised)
        finally:
            restore(real)


def test_the_command_line_can_change_where_an_action_writes():
    client = FakeClient()
    fake = FakeModel("facts", "the memo")
    real = with_model(fake)
    with tempfile.TemporaryDirectory() as tmp:
        here = os.getcwd()
        os.chdir(tmp)
        try:
            r = run_flow(
                three_step(),
                [A, B],
                client=client,
                confirm=True,
                overrides={"file": {"path": "mine.md"}},
                **MODEL,
            )
            assert r.steps[-1].performed is True
            assert os.path.exists("mine.md") and not os.path.exists("out/report.md")
        finally:
            os.chdir(here)
            restore(real)


# ---------------------------------------------------------------- stopping


def test_no_model_stops_at_the_first_thinking_step_and_hands_back_the_prompt():
    client = FakeClient()
    r = run_flow(three_step(), [A, B], client=client)
    assert r.stopped_at == "facts"
    assert "no model is configured" in (r.stopped_reason or "").lower()
    assert "List the facts." in r.steps[-1].prompt
    assert "Alpha text." in r.steps[-1].prompt
    assert r.answer is None


def test_nothing_readable_stops_before_any_thinking():
    client = FakeClient(pages={})
    fake = FakeModel("should not be called")
    real = with_model(fake)
    try:
        r = run_flow(three_step(), [A, B], client=client, **MODEL)
    finally:
        restore(real)
    assert [s.kind for s in r.steps] == ["read"]
    assert r.stopped_at == "sources"
    assert fake.calls == [], "a model was called with nothing to work from"


def test_a_flow_that_cannot_work_is_refused_before_anything_is_read():
    client = FakeClient()
    broken = Flow(
        slug="broken",
        name="Broken",
        category="data",
        tagline="x",
        what_you_give="x",
        what_you_get="x",
        steps=[Read(), Act(name="file", action="write_file", uses="nothing", config={"path": "x.md"})],
    )
    raised = None
    try:
        run_flow(broken, [A], client=client, **MODEL)
    except FlowError as e:
        raised = e
    assert raised is not None and "no earlier step produced" in str(raised)
    assert client.calls == [], "a broken flow still paid for reads"


# ---------------------------------------------------------------- the library


def test_every_shipped_recipe_is_a_one_step_flow_that_still_runs():
    client = FakeClient()
    fake = FakeModel(*["the answer [1]"] * 40)
    real = with_model(fake)
    try:
        for recipe in [r for r in all_recipes() if getattr(r, "steps", None) is None]:
            f = flow_for_recipe(recipe)
            assert [type(s).__name__ for s in f.steps] == ["Read", "Think"], recipe.slug
            r = run_flow(f, [A], client=client, **MODEL)
            assert r.answer == "the answer [1]", recipe.slug
            assert r.steps[-1].cited == [1]
    finally:
        restore(real)


# ---------------------------------------------------------------- the command line


def run_cli(argv, client, fake_model):
    """Run the command line against a fake reader and a fake model."""
    import io
    from contextlib import redirect_stderr, redirect_stdout

    import lyrenth_agents.cli as cli

    real_client, real_model = cli.Lyrenth, flow_module.call_model
    cli.Lyrenth = lambda: client
    flow_module.call_model = fake_model
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(argv)
    finally:
        cli.Lyrenth, flow_module.call_model = real_client, real_model
    return code, out.getvalue(), err.getvalue()


def installed(flow):
    """Put one flow in the registry for the length of a test."""
    from contextlib import contextmanager

    import lyrenth_agents.recipes as recipes_module

    @contextmanager
    def _ctx():
        before = dict(recipes_module.REGISTRY)
        recipes_module.REGISTRY[flow.slug] = flow
        try:
            yield
        finally:
            recipes_module.REGISTRY.clear()
            recipes_module.REGISTRY.update(before)

    return _ctx()


def test_the_command_line_runs_a_flow_and_reports_every_step():
    flow = three_step()
    client = FakeClient()
    fake = FakeModel("the facts [1]", "the memo [1]")
    with tempfile.TemporaryDirectory() as tmp:
        here = os.getcwd()
        os.chdir(tmp)
        try:
            with installed(flow):
                code, out, err = run_cli(
                    ["report", A, B, "--model-url", MODEL["base_url"], "--model", MODEL["model"]],
                    client,
                    fake,
                )
        finally:
            os.chdir(here)
    assert code == 0, err
    assert "recipe   report: Report" in err
    assert "step     facts:" in err and "step     memo:" in err
    assert "would write out/report.md" in err
    assert "add --yes" in err
    assert out.startswith("the memo [1]")
    assert "[1] Page A" in out


def test_the_command_line_performs_the_action_with_yes_and_can_move_it():
    flow = three_step()
    client = FakeClient()
    fake = FakeModel("the facts [1]", "the memo [1]")
    with tempfile.TemporaryDirectory() as tmp:
        here = os.getcwd()
        os.chdir(tmp)
        try:
            with installed(flow):
                code, out, err = run_cli(
                    [
                        "report", A, B,
                        "--model-url", MODEL["base_url"], "--model", MODEL["model"],
                        "--yes", "--set", "file.path=notes/mine.md",
                    ],
                    client,
                    fake,
                )
            assert code == 0, err
            assert os.path.exists("notes/mine.md")
            assert open("notes/mine.md").read().strip() == "the memo [1]"
            assert "add --yes" not in err
        finally:
            os.chdir(here)


def test_the_command_line_hands_back_the_prompt_when_no_model_is_set():
    flow = three_step()
    client = FakeClient()
    fake = FakeModel("never called")
    with installed(flow):
        code, out, err = run_cli(["report", A, B], client, fake)
    assert code == 0, err
    assert "List the facts." in out
    assert "no model is configured" in err.lower()
    assert fake.calls == []


def test_a_bad_set_is_refused_before_anything_is_read():
    flow = three_step()
    client = FakeClient()
    fake = FakeModel("x")
    with installed(flow):
        code, out, err = run_cli(["report", A, "--set", "nonsense"], client, fake)
    assert code == 2
    assert "--set wants STEP.KEY=VALUE" in err
    assert client.calls == []


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} passed")
