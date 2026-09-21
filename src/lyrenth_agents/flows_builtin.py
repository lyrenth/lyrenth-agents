"""The flows that ship with the package: agents with more than one step.

A flow is data, like a recipe, so adding one is writing down the steps and
the words. See flow.py for what the three kinds of step mean and for the
two rules that keep an acting step safe.

The same two rules apply to the words here as to the recipes: plain
English, and never a promise the tool cannot keep.
"""

from __future__ import annotations

from typing import List

from .flow import Act, Flow, Read, Think

__all__ = ["BUILTIN_FLOWS"]


COMPANY_PACK = Flow(
    slug="company-pack",
    name="Company pack",
    category="company",
    tagline="Read a company's own pages and leave with a one-page pack for the meeting.",
    what_you_give=(
        "The company's own pages: the about page, the product or pricing page, "
        "and the careers page when there is one."
    ),
    what_you_get=(
        "One page you can take into the meeting: what they do and who they sell "
        "to, the questions their own pages leave open, and what to check before "
        "you believe it. Written to a file when you ask for it."
    ),
    url_hint=(
        "Their own pages only. A news article about the company is somebody "
        "else's summary, and the point here is what they say themselves."
    ),
    example_urls=[
        "https://www.mozilla.org/en-US/about/",
        "https://www.mozilla.org/en-US/about/manifesto/",
        "https://www.mozilla.org/en-US/careers/",
    ],
    steps=[
        Read(),
        Think(
            name="brief",
            uses=("sources",),
            prompt=(
                "You read a company's own pages and write down what they say about "
                "themselves, in plain words, for somebody who has a meeting with "
                "them tomorrow. Use only the pages given. Where the pages do not "
                "answer something, say so instead of filling the gap. Quote the "
                "company's own wording when it is doing real work, and put the "
                "number of the page beside every claim."
            ),
            output_hint=(
                "Four short sections, in this order: what they do, who it is for, "
                "what they sell, and what these pages do not answer. A source "
                "number on every line."
            ),
        ),
        Think(
            name="pack",
            uses=("brief",),
            prompt=(
                "You turn a brief about a company into the single page a person "
                "takes into a meeting with them. Work only from the brief you are "
                "given: it was written from the company's own pages, and the "
                "numbers in it point at those pages. Keep those numbers where they "
                "belong. The questions you write are the ones the brief leaves "
                "open, not general questions anybody could ask."
            ),
            output_hint=(
                "A one page document in Markdown: a title line, three sentences on "
                "what they do, then 'Questions for them' as a numbered list of no "
                "more than six, then 'Check before you believe it' as a short list "
                "of the claims that came from the company's own pages and nowhere "
                "else. Keep the source numbers on the lines that carry them."
            ),
        ),
        Act(
            name="file",
            action="write_file",
            uses="pack",
            config={"path": "company-pack.md"},
        ),
    ],
)


BUILTIN_FLOWS: List[Flow] = [COMPANY_PACK]
