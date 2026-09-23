"""Command line: lyrenth-agents <recipe-slug> <url> [url ...]

One key is enough to get something useful. With LYRENTH_API_KEY set and no
model configured, the pages are read and the finished prompt is printed on
standard output, ready to paste into whichever assistant you already use. The
running commentary (which pages were read, which were skipped and why, what to
do next) goes to standard error, so this works:

    lyrenth-agents <slug> <url> | pbcopy

Set LLM_BASE_URL and LLM_MODEL and the same command answers directly instead.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from lyrenth import Lyrenth, LyrenthError

from . import __version__
from .engine import (
    DEFAULT_TOKEN_BUDGET,
    ModelError,
    answer_into,
    build_sources_block,
    model_half_configured,
    model_is_configured,
    read_for,
)
from .flow import FlowError, run_flow
from .recipes import UnknownRecipe, all_recipes, get, load_error


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lyrenth-agents",
        # RawDescriptionHelpFormatter does not re-wrap, so these lines are
        # wrapped by hand to stay readable in a narrow terminal.
        description=(
            "Run one of the agent recipes over the pages you give it. Every page is\n"
            "read through Lyrenth, and every claim in the answer points at the page\n"
            "it came from.\n"
            "\n"
            "With no model configured, the finished prompt is printed instead, so one\n"
            "Lyrenth key is enough to get something you can use."
        ),
        epilog=(
            "examples:\n"
            "  lyrenth-agents --list\n"
            "  lyrenth-agents <recipe-slug> https://example.com/page\n"
            "  lyrenth-agents <recipe-slug> https://example.com/page | pbcopy\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("recipe", nargs="?", help="which recipe to run (see --list)")
    p.add_argument("urls", nargs="*", help="the pages to read, most important first")
    p.add_argument("--list", action="store_true", help="list the recipes and exit")
    p.add_argument(
        "--sources-only",
        action="store_true",
        help="print the numbered sources and stop, without building a prompt or calling a model",
    )
    p.add_argument("--json", action="store_true", help="print the result as JSON")
    p.add_argument(
        "--budget",
        type=int,
        default=DEFAULT_TOKEN_BUDGET,
        help=f"token budget for all sources together (default {DEFAULT_TOKEN_BUDGET})",
    )
    p.add_argument(
        "--fresh",
        action="store_true",
        help="ask Lyrenth for a fresh fetch instead of the stored page",
    )
    p.add_argument(
        "-q",
        "--question",
        help=(
            "what to ask of these pages. The answers and research recipes need "
            "one; the rest ignore it."
        ),
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="perform the steps that act on the world. Without it they say what they would do and stop.",
    )
    p.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="STEP.KEY=VALUE",
        help="change one setting of an acting step, for example --set file.path=notes/pack.md",
    )
    p.add_argument("--model-url", help="OpenAI-compatible base URL (default: LLM_BASE_URL)")
    p.add_argument("--model", help="model name (default: LLM_MODEL)")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


# ------------------------------------------------------------------ listing


def _list_recipes(as_json: bool = False, out=None) -> int:
    out = out or sys.stdout
    recipes = all_recipes()

    if as_json:
        print(json.dumps([asdict(r) for r in recipes], indent=2), file=out)
        return 0

    if not recipes:
        print("No recipes are installed yet.", file=out)
        problem = load_error()
        if problem:
            print(problem, file=out)
        return 0

    print("Recipes you can run:\n", file=out)
    category = None
    for r in recipes:
        if r.category != category:
            category = r.category
            print(f"{category}", file=out)
        print(f"  {r.slug:<24}{r.tagline}", file=out)
    print("\nRun one with: lyrenth-agents <recipe-slug> <url> [url ...]", file=out)
    print("See what a recipe needs with: lyrenth-agents <recipe-slug>", file=out)
    return 0


def _recipe_card(recipe, out=None) -> None:
    """What this recipe wants, shown when someone runs it without any URLs."""
    out = out or sys.stderr
    print(f"{recipe.name} ({recipe.slug})", file=out)
    print(f"  {recipe.tagline}", file=out)
    print(f"  You give it:  {recipe.what_you_give}", file=out)
    print(f"  You get back: {recipe.what_you_get}", file=out)
    if recipe.url_hint:
        print(f"  Good pages:   {recipe.url_hint}", file=out)
    print("", file=out)
    if recipe.example_urls:
        example = " ".join(recipe.example_urls[:2])
        print(f"Try: lyrenth-agents {recipe.slug} {example}", file=out)
    else:
        print(f"Give it at least one URL: lyrenth-agents {recipe.slug} <url>", file=out)


# ------------------------------------------------------------------ reporting


def _flush(stream) -> None:
    """Best effort flush. A StringIO in a test has nothing to flush."""
    try:
        stream.flush()
    except (AttributeError, ValueError):
        pass


def _report(result, out=None) -> None:
    # Looked up at call time, so a caller that redirects stderr captures it.
    out = out or sys.stderr
    print(f"recipe   {result.recipe.slug}: {result.recipe.name}", file=out)
    for s in result.skipped:
        print(f"skipped  {s.url}: {s.reason}", file=out)
    for i, s in enumerate(result.sources, 1):
        # Some pages carry no title at all (an RFC served as one <pre>
        # block is the example). Printing an empty one left a hole in the
        # line, so the URL stands in its place rather than beside it.
        label = f"{s.title}  " if s.title else ""
        print(f"read [{i}] {label}{s.tokens:,} tokens  {s.url}", file=out)
    line = f"context  {result.tokens:,} tokens from {len(result.sources)} sources"
    if result.raw_html_tokens:
        line += f" (raw HTML would be {result.raw_html_tokens:,})"
    print(line, file=out)


def _print_prompt(result, out=None, err=None) -> None:
    """The one-key path: the prompt on stdout, what to do with it on stderr.

    stdout is block buffered when it is piped, so it is flushed before the
    note goes to stderr. Without that, the note lands above the prompt it
    is talking about.
    """
    out = out or sys.stdout
    err = err or sys.stderr
    print(result.prompt, file=out)
    _flush(out)
    print("", file=err)
    print("no model configured, so the finished prompt was printed instead of an answer.", file=err)
    print("next step: paste that prompt into the assistant you use.", file=err)
    print("to get the answer here instead, set LLM_BASE_URL and LLM_MODEL.", file=err)


def _print_answer(result, out=None, err=None) -> None:
    out = out or sys.stdout
    err = err or sys.stderr
    print(result.answer, file=out)
    print("", file=out)
    print("Sources", file=out)
    for i, s in enumerate(result.sources, 1):
        mark = "" if i in result.cited else "  (not cited)"
        label = f"{s.title}  " if s.title else ""
        print(f"  [{i}] {label}{s.url}{mark}", file=out)
    if result.unknown_citations:
        nums = ", ".join(f"[{n}]" for n in result.unknown_citations)
        print(f"\nwarning: the answer cites {nums}, which is not one of the sources above", file=err)


def _payload(result) -> dict:
    return {
        "recipe": result.recipe.slug,
        "answer": result.answer,
        "model_used": result.model_used,
        "no_sources_reason": result.no_sources_reason,
        "prompt": result.prompt,
        "cited": result.cited,
        "unknown_citations": result.unknown_citations,
        "sources": [
            {"n": i, "title": s.title, "url": s.url, "read": s.fetched_at, "tokens": s.tokens}
            for i, s in enumerate(result.sources, 1)
        ],
        "skipped": [asdict(s) for s in result.skipped],
    }


def _overrides(pairs) -> dict:
    """Turn --set file.path=x into {"file": {"path": "x"}}.

    This is the only way an acting step's settings change at run time, and it
    comes from the person at the keyboard. Nothing a model wrote can reach it.
    """
    out: dict = {}
    for pair in pairs or []:
        if "=" not in pair or "." not in pair.split("=", 1)[0]:
            raise ValueError(f"--set wants STEP.KEY=VALUE, got {pair!r}")
        target, value = pair.split("=", 1)
        step, key = target.split(".", 1)
        out.setdefault(step.strip(), {})[key.strip()] = value.strip()
    return out


def _flow_payload(flow, result) -> dict:
    return {
        "recipe": flow.slug,
        "answer": result.answer,
        "stopped_at": result.stopped_at,
        "stopped_reason": result.stopped_reason,
        "steps": [
            {
                "name": s.name,
                "kind": s.kind,
                "text": s.text,
                "prompt": s.prompt,
                "model_used": s.model_used,
                "performed": s.performed,
                "note": s.note,
                "cited": s.cited,
                "unknown_citations": s.unknown_citations,
            }
            for s in result.steps
        ],
        "sources": [
            {"n": i, "title": s.title, "url": s.url, "read": s.fetched_at, "tokens": s.tokens}
            for i, s in enumerate(result.sources, 1)
        ],
        "skipped": [asdict(s) for s in result.skipped],
    }


def _run_flow_cli(flow, args) -> int:
    """Run an agent that has several steps, reporting each one as it lands."""
    err = sys.stderr
    print(f"recipe   {flow.slug}: {flow.name}", file=err)

    try:
        overrides = _overrides(args.set)
    except ValueError as e:
        print(f"error: {e}", file=err)
        return 2

    missing_half = model_half_configured(args.model_url, args.model)
    if missing_half:
        print(f"error: the model setup is missing {missing_half}", file=err)
        return 2

    def report(step) -> None:
        # The read step is reported once the run returns, with the same lines
        # the one-question path prints. Thinking and acting are reported as
        # they land, because a four step flow otherwise goes quiet for a
        # minute and looks stuck.
        if step.kind == "read":
            return
        if step.kind == "think":
            if step.model_used:
                print(f"step     {step.name}: {len(step.text):,} characters", file=err)
            return
        if step.performed:
            print(f"step     {step.name}: {step.text}", file=err)
        else:
            print(f"step     {step.name}: {step.text or step.note}", file=err)

    try:
        result = run_flow(
            flow,
            args.urls,
            client=Lyrenth(),
            token_budget=args.budget,
            fresh=args.fresh,
            question=args.question,
            base_url=args.model_url,
            model=args.model,
            confirm=args.yes,
            overrides=overrides,
            on_step=report,
        )
    except FlowError as e:
        print(f"error: {e}", file=err)
        return 2
    except LyrenthError as e:
        print(f"error: {e}", file=err)
        return 1
    except ModelError as e:
        print(f"error: {e}", file=err)
        return 1

    for s in result.skipped:
        print(f"skipped  {s.url}: {s.reason}", file=err)
    for i, s in enumerate(result.sources, 1):
        label = f"{s.title}  " if s.title else ""
        print(f"read [{i}] {label}{s.tokens:,} tokens  {s.url}", file=err)
    if result.sources:
        line = f"context  {result.tokens:,} tokens from {len(result.sources)} sources"
        if result.raw_html_tokens:
            line += f" (raw HTML would be {result.raw_html_tokens:,})"
        print(line, file=err)

    if args.json:
        print(json.dumps(_flow_payload(flow, result), indent=2))
        return 0 if result.answer else 1

    if not result.sources:
        print(f"error: {result.stopped_reason}", file=err)
        return 1

    if result.stopped_at and result.answer is None:
        # No model: hand over the prompt for the step it stopped at, which is
        # the same bargain the one-question agents make.
        stopped = result.steps[-1]
        print(stopped.prompt)
        _flush(sys.stdout)
        print("", file=err)
        print(result.stopped_reason, file=err)
        return 0

    print(result.answer)
    print("", file=sys.stdout)
    print("Sources", file=sys.stdout)
    cited = {n for s in result.steps for n in s.cited}
    for i, s in enumerate(result.sources, 1):
        mark = "" if i in cited else "  (not cited)"
        label = f"{s.title}  " if s.title else ""
        print(f"  [{i}] {label}{s.url}{mark}", file=sys.stdout)

    waiting = [s for s in result.steps if s.kind == "act" and not s.performed and s.text]
    if waiting:
        print("", file=err)
        for s in waiting:
            print(f"not done yet: {s.text}", file=err)
        print("add --yes to the same command to do it.", file=err)
    return 0


# ------------------------------------------------------------------ main


def main(argv=None) -> int:
    # Intermixed, so an option may sit before, between or after the URLs.
    # Plain parse_args refused `answers -q "..." URL URL` on Python 3.9,
    # the form the site prints, and an option between two URLs on every
    # version (2026-09-24).
    args = _parser().parse_intermixed_args(argv)

    if args.list:
        return _list_recipes(as_json=args.json)

    if not args.recipe:
        print("give a recipe slug, or --list to see what is available", file=sys.stderr)
        return 2

    try:
        recipe = get(args.recipe)
    except UnknownRecipe as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if not args.urls:
        _recipe_card(recipe)
        return 2

    # An agent with steps runs through the flow engine. A one-question recipe
    # keeps its own path, which is that same engine with one step, kept
    # separate while flows are new.
    if getattr(recipe, "steps", None):
        return _run_flow_cli(recipe, args)

    # Reading first, on its own. Whatever happens with a model afterwards, the
    # pages are read and the prompt exists.
    try:
        result = read_for(
            recipe,
            args.urls,
            client=Lyrenth(),
            token_budget=args.budget,
            fresh=args.fresh,
            question=args.question,
        )
    except LyrenthError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    _report(result)

    # Every page failed. Printing a prompt whose sources section reads "none"
    # and exiting 0 tells a script the run went fine, so say it and fail.
    if not result.sources:
        print(
            "error: none of the pages could be read, so there is nothing to work from.",
            file=sys.stderr,
        )
        if args.json:
            print(json.dumps(_payload(result), indent=2))
        return 1

    if args.sources_only:
        if args.json:
            print(json.dumps(
                {
                    "recipe": recipe.slug,
                    "sources": [asdict(s) for s in result.sources],
                    "skipped": [asdict(s) for s in result.skipped],
                },
                indent=2,
            ))
        else:
            print(build_sources_block(result.sources))
        return 0

    missing_half = model_half_configured(args.model_url, args.model)
    if missing_half:
        print(f"error: the model setup is missing {missing_half}", file=sys.stderr)
        print("Or drop both and this prints the finished prompt instead.", file=sys.stderr)
        return 2

    if not model_is_configured(args.model_url, args.model):
        if args.json:
            print(json.dumps(_payload(result), indent=2))
            return 0
        _print_prompt(result)
        return 0

    try:
        answer_into(result, base_url=args.model_url, model=args.model)
    except ModelError as e:
        # The reading is done and the prompt is good. Hand it over rather than
        # throwing the work away, and exit non-zero so a script still notices.
        print(f"error: {e}", file=sys.stderr)
        print("the pages were read anyway, so the prompt follows on standard output.", file=sys.stderr)
        _flush(sys.stderr)
        print(result.prompt)
        return 1

    if args.json:
        print(json.dumps(_payload(result), indent=2))
        return 0

    _print_answer(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
