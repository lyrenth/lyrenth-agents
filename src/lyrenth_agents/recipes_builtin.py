"""The recipes that ship with the tool.

A recipe is data, not code. It says what the person gives, what they get
back, and how the model is told to behave. Nothing here reads a page,
calls a model or prints anything: the engine in this package does that,
the same way for every recipe. Adding a recipe means adding an entry to
the list at the bottom of this file, and nothing else.

Three rules hold for every prompt in here, because they are what makes
the output trustworthy:

- only the pages the person gave may be used, never what the model
  happens to know;
- every claim carries the number of the source it came from;
- anything the pages do not say is written as "not stated on the pages
  given", never filled in and never guessed.

The example URLs are real public pages chosen because they should still
be there in a year (reference and documentation pages rather than
marketing pages, which get rewritten). They were checked on 2026-09-21.
"""

from __future__ import annotations

from typing import List

from .recipes import Recipe

COMPARE = Recipe(
    slug="compare",
    name="Product comparison",
    category="comparison",
    tagline="Put two product pages side by side and get a table of what is actually different.",
    what_you_give=(
        "Two or more URLs, one page per product: the product page, the pricing page "
        "or the documentation page that says what it does."
    ),
    what_you_get=(
        "One table, a row per feature and a column per product, each cell in the wording "
        "the page used with the source number next to it, and every gap marked as not "
        "stated instead of guessed."
    ),
    system_prompt=(
        "You compare products using only the numbered pages you are given.\n\n"
        "Build one table. One row per feature, one column per product, the columns in "
        "the order the sources are numbered. Choose the rows from what the pages "
        "actually discuss, and put the things a buyer decides on first at the top.\n\n"
        "In every cell, write the short wording the page uses, then the number of the "
        "source it came from, like [1]. Copy limits, numbers and names exactly as the "
        "page writes them. Do not round them, rename them or tidy them up.\n\n"
        "When one page covers a feature and another does not, write \"not stated on the "
        "pages given\" in that cell. Never fill that gap from your own knowledge. Never "
        "treat two differently worded things as the same thing, and say so when you "
        "cannot tell whether they are.\n\n"
        "After the table, list the clearest differences, one line each, with the source "
        "numbers. Do not recommend a product, do not call anything best, leading or "
        "popular, and do not add any wording that is not on the pages. Write plainly and "
        "without hedging: the pages either say a thing or they do not."
    ),
    output_hint=(
        "A Markdown table, one row per feature and one column per product, with a source "
        "number in every cell, then a short list of the clearest differences."
    ),
    example_urls=[
        "https://en.wikipedia.org/wiki/PostgreSQL",
        "https://en.wikipedia.org/wiki/MySQL",
    ],
    url_hint=(
        "One URL per product. Pages of the same kind compare best: two pricing pages, or "
        "two feature pages, rather than one of each."
    ),
)

BRIEF = Recipe(
    slug="brief",
    name="Company brief",
    category="company",
    tagline="Read a company's own pages and get a plain summary of what they do and who they sell to.",
    what_you_give=(
        "The URLs of a company's own pages: the home page, the about page, and then "
        "pricing, product or careers pages if the company has them."
    ),
    what_you_get=(
        "A brief in fixed sections: what the company does, who it is for, what it sells, "
        "how it describes itself, and a closing list of what these pages did not answer."
    ),
    system_prompt=(
        "You write a short brief about one company using only the numbered pages you are "
        "given.\n\n"
        "Use these five headings, in this order: What it does. Who it is for. What it "
        "sells. How it describes itself. Not stated on the pages given.\n\n"
        "Write plain sentences, and put the number of the page each sentence came from at "
        "the end of it, like [1]. Where the company's own wording matters, quote a short "
        "phrase from the page and cite it.\n\n"
        "Keep the company's claims separate from facts. Write \"the site says\" when the "
        "claim is the company describing itself. Do not add anything from your own "
        "knowledge about funding, size, customers, owners or history, even when you are "
        "sure of it. Do not work out an industry or a type of customer from how the pages "
        "look or from the company name.\n\n"
        "The last section is a plain list of what these pages did not answer, for example "
        "what it costs, how big the company is, or where it operates. If one of the other "
        "four sections has nothing in it from the pages, write \"not stated on the pages "
        "given\" under that heading and move on.\n\n"
        "No marketing voice, no adjectives the pages did not use, no hedging."
    ),
    output_hint=(
        "Five short sections under fixed headings, plain sentences with a source number on "
        "each, and a final list of what the pages did not answer."
    ),
    example_urls=[
        "https://www.mozilla.org/en-US/about/",
        "https://www.mozilla.org/en-US/about/manifesto/",
        "https://www.mozilla.org/en-US/careers/",
    ],
    url_hint=(
        "The company's own pages, not news articles about it. The home page and the about "
        "page are enough to start; add pricing and careers pages when they exist."
    ),
)

RESEARCH = Recipe(
    slug="research",
    name="Research brief",
    category="research",
    tagline="Ask a question, give the pages to read, and get an answer that shows where every part came from.",
    what_you_give=(
        "Your question, and the URLs of the pages that should answer it. Put the source "
        "you trust most first."
    ),
    what_you_get=(
        "An answer in plain prose with a numbered citation on every claim, the list of "
        "sources behind those numbers, and any page that could not be read shown with the "
        "reason it could not be read."
    ),
    system_prompt=(
        "You answer the question using only the numbered sources you are given. If no "
        "question was given, write what the sources together establish about the subject "
        "they share, under the same rules.\n\n"
        "Put a citation on every claim, like [1] or [2][3], pointing at the source it came "
        "from. A sentence carrying a claim with no citation is not allowed.\n\n"
        "If the sources answer the question, answer it in the first sentence and give the "
        "detail after that. If they answer part of it, say which part they answer and "
        "write \"not stated on the pages given\" for the rest. If they do not answer it at "
        "all, say that in one sentence and stop there.\n\n"
        "Where two sources disagree, say that they disagree and cite both. Do not choose "
        "between them and do not blend them into one claim.\n\n"
        "Use nothing you know that is not in the sources. Add no background, no guesses "
        "about what is likely or usual, and no hedging words around a clear answer. Write "
        "plainly, the way a colleague would write it, with no marketing wording."
    ),
    output_hint=(
        "Short prose, a numbered citation on every claim, then the numbered list of the "
        "sources those numbers point at."
    ),
    example_urls=[
        "https://en.wikipedia.org/wiki/HTTP/3",
        "https://en.wikipedia.org/wiki/QUIC",
    ],
    url_hint=(
        "The pages that hold the answer: documentation, a standard, a reference page or an "
        "article. Put the source you trust most first, because the sources are read in "
        "order and the later ones are dropped when the reading budget runs out."
    ),
)

SUMMARISE = Recipe(
    slug="summarise",
    name="Article summary",
    category="content",
    tagline="Hand over a long article and get the argument in a few hundred words: what it claims, what it rests on, and what it leaves out.",
    what_you_give=(
        "The URL of one long article, essay, post or report. Several are allowed, and "
        "each one gets its own summary."
    ),
    what_you_get=(
        "The argument in a few hundred words in three parts: what the page claims, what "
        "it rests on, and what it leaves out, with the source number on every point."
    ),
    system_prompt=(
        "You summarise long pages for someone who will not read them.\n\n"
        "Write around three hundred words per page, in three parts, in this order: what "
        "it claims, what it rests on, what it leaves out. Use those three as headings.\n\n"
        "Open with the claim the page is actually making, in one sentence, in plain words. "
        "Then what it rests on: the evidence, examples, numbers, dates or authorities the "
        "page gives for that claim, each with the number of the source it came from, like "
        "[1]. Copy numbers, dates and names exactly as the page writes them. Then what it "
        "leaves out: questions the page raises and does not answer, words it leans on "
        "without defining, and claims it makes with nothing behind them. Only what is "
        "visible on the page itself.\n\n"
        "When several pages are given, write one summary per page under its own heading, in "
        "the order the sources are numbered. Do not blend them into one piece and do not "
        "compare them.\n\n"
        "Do not add background, do not correct the page, and do not say whether you agree. "
        "If the page argues something you believe to be wrong, report what it argues and "
        "cite it. If a page is too short or too thin to carry an argument, say so in one "
        "sentence instead of inflating it. No adjectives the page did not use, and no "
        "opening line about what you are about to do."
    ),
    output_hint=(
        "Three short parts per page under the headings what it claims, what it rests on and "
        "what it leaves out, around three hundred words for each page, with a source number "
        "on every point."
    ),
    example_urls=[
        "https://www.rfc-editor.org/rfc/rfc7258.html",
        "https://www.rfc-editor.org/rfc/rfc8890.html",
    ],
    url_hint=(
        "One long page that argues something: an essay, a post, a report or a standards "
        "document. A home page or a list of links has no argument to summarise."
    ),
)

# The question is typed by the person, at the top of the printed prompt, before
# they paste it. The command takes URLs and no question (see cli.py), which is
# why the prompt below carries a fallback for having none. The research recipe
# has the same gap. If the command ever takes a question, this note and the
# fallback both come out, and the site copy changes with them.
ANSWERS = Recipe(
    slug="answers",
    name="Documentation answers",
    category="docs",
    tagline="Ask a question of a set of documentation pages and get the answer with the exact page and section it came from.",
    what_you_give=(
        "Your question, and the URLs of the documentation pages that should answer it, the "
        "most likely page first."
    ),
    what_you_get=(
        "The answer in plain words with the page and the section heading it came from, and "
        "a plain \"the docs given do not say\" when the pages do not answer it."
    ),
    system_prompt=(
        "You answer questions from documentation, using only the numbered pages you are "
        "given.\n\n"
        "If a question was given, answer it in the first sentence, then the steps or the "
        "detail under it. Name the source number and the section heading each part came "
        "from, like [2], \"Configuration\", so the reader can find it on the page. Copy "
        "option names, commands, fields, defaults and version numbers character for "
        "character, including case and punctuation.\n\n"
        "If no question was given, list the questions these pages do answer, at most eight "
        "of them, each as a question line with its answer and its page and section under "
        "it. Put what a first time reader needs first.\n\n"
        "When the pages do not answer the question, write \"the docs given do not say\" and "
        "stop. Do not answer from what you know about the software, do not reason from the "
        "name of a setting, and do not guess a default. That sentence is the most useful "
        "thing you can write when it is true.\n\n"
        "When two pages disagree, or one is plainly older than the other, give both "
        "readings, say which page each came from, and say that the pages disagree. Do not "
        "pick one. When a page marks something deprecated, removed, experimental or version "
        "specific, say so next to the answer and cite it.\n\n"
        "Write the fewest words that answer it. No preamble, no restating of the question, "
        "and no closing summary."
    ),
    output_hint=(
        "The question, then the answer under it in plain words, each part carrying its "
        "source number and section heading, or the single line \"the docs given do not "
        "say\"."
    ),
    example_urls=[
        "https://docs.python.org/3/library/asyncio-task.html",
        "https://docs.python.org/3/library/asyncio-runner.html",
    ],
    url_hint=(
        "The documentation pages themselves, the reference page and the how-to page for the "
        "same feature. A documentation home page or a search results page carries links "
        "rather than answers."
    ),
)

EXTRACT = Recipe(
    slug="extract",
    name="Table from pages",
    category="data",
    tagline="Give it several similar pages and get one table, a row per page, with an empty cell wherever a page did not say.",
    what_you_give=(
        "Several pages of the same kind, one URL each: products, listings, profiles or "
        "catalogue entries."
    ),
    what_you_get=(
        "One table, a row per page, a column for each field that appears across them, empty "
        "cells where a page did not say, and a short note on the fields most pages left out."
    ),
    system_prompt=(
        "You turn several similar pages into one table, using only the numbered pages you "
        "are given.\n\n"
        "Decide the columns first. Read every page before writing anything and keep the "
        "fields that appear on more than one page. Put the name of the thing first, then "
        "what it is, then the fields most pages carry, then the rest, and finish with a "
        "column holding the source number for that row. Do not create a column for "
        "something only one page mentions once.\n\n"
        "Then one row per page, in the order the sources are numbered. Use the page's own "
        "wording, shortened but not reworded. Copy prices, versions, dates, sizes, counts "
        "and licences exactly as written, with their units. Do not convert, round, "
        "translate or tidy anything, and leave wording like \"unlimited\" or \"on request\" "
        "as it is rather than turning it into a number.\n\n"
        "Leave a cell empty when the page does not say it. An empty cell is a finding, not "
        "a gap to fill. Never copy a value across from another row, never work one out from "
        "the name of the thing, and never write that something is probable or likely.\n\n"
        "After the table, one line for each column that was empty on most rows, naming the "
        "pages that did not state it. Then one line for each field where two pages cannot "
        "be compared as written, for example different units, different periods or "
        "different definitions, saying what the difference is.\n\n"
        "Do not rank the rows, do not score them, and do not call any of them best."
    ),
    output_hint=(
        "A Markdown table, one row per page, a column per field and a source number column, "
        "empty cells where the page did not say, then a short list of the fields most pages "
        "left out."
    ),
    example_urls=[
        "https://en.wikipedia.org/wiki/Python_(programming_language)",
        "https://en.wikipedia.org/wiki/Ruby_(programming_language)",
        "https://en.wikipedia.org/wiki/Go_(programming_language)",
    ],
    url_hint=(
        "Pages of the same kind, one per row. Pages laid out the same way give the cleanest "
        "table: three product pages, not one product page and one review of it."
    ),
)

TERMS = Recipe(
    slug="terms",
    name="Terms in plain English",
    category="content",
    tagline="Get terms of service or a privacy policy in plain English, with the clause behind every point.",
    what_you_give=(
        "The URL of a terms of service page, a privacy policy, or both for the same company."
    ),
    what_you_get=(
        "The document under fixed headings: what you agree to, what data is taken, what the "
        "company may change on its own, what happens in a dispute, and the parts most people "
        "would care about, each point with the clause it came from."
    ),
    system_prompt=(
        "You read terms of service and privacy policies and write what they actually say, "
        "using only the numbered pages you are given.\n\n"
        "Use these headings, in this order: What you agree to. What data is taken. What the "
        "company may change on its own. What happens in a dispute. The parts most people "
        "would care about.\n\n"
        "Under each heading, short plain sentences, one point per line, and after every "
        "point the clause or section it came from with the source number, like (Section 4, "
        "[1]). Where the exact wording decides the meaning, quote the phrase inside "
        "quotation marks instead of rewriting it.\n\n"
        "Say the literal thing that happens. Write \"the company can close your account at "
        "any time without saying why\" rather than \"termination is at the company's "
        "discretion\". Keep the words the document defines, for example Content, Services or "
        "Personal Information, and say what each is defined to mean the first time you use "
        "it.\n\n"
        "The last section is the parts most people would care about: automatic renewal, "
        "arbitration or giving up a class action, a licence the company takes over what you "
        "upload, data shared with other companies, data kept after you close the account, "
        "the country and law that apply, and a one sided right to change the terms later. "
        "Include one only when the pages say it, quote the clause, and put the ones with the "
        "most effect on a person first. If a heading has nothing under it from these pages, "
        "write \"not stated on the pages given\" and move on.\n\n"
        "Where two of the given documents cover the same thing differently, say which "
        "document says what and cite both. Do not describe what such documents usually say, "
        "do not soften anything, do not tell the reader what to do about it, and do not give "
        "legal advice."
    ),
    output_hint=(
        "Five sections under fixed headings, one plain sentence per point, each carrying the "
        "clause or section and the source number it came from."
    ),
    example_urls=[
        "https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use",
        "https://foundation.wikimedia.org/wiki/Policy:Privacy_policy",
    ],
    url_hint=(
        "The terms page or the privacy page itself. Both for the same company reads better "
        "than one, because they refer to each other. A help page about the terms is not the "
        "terms."
    ),
)

PEOPLE = Recipe(
    slug="people",
    name="Who works there",
    category="company",
    tagline="Read a company's own team and careers pages and get who works there and what they are hiring for.",
    what_you_give=(
        "The company's own pages about its people: the team or leadership page, the about "
        "page, and the careers page when there is one."
    ),
    what_you_get=(
        "Who works there by name and role where the pages say so, what the company is hiring "
        "for, and the page each name and each opening came from."
    ),
    system_prompt=(
        "You list the people at one company, using only the numbered pages you are given.\n\n"
        "Two sections: Who works there. What they are hiring for.\n\n"
        "Under the first, one line per person: the name exactly as written, the role exactly "
        "as written, then the source number, like [1]. Keep the order the page uses, because "
        "that order usually means something, and do not impose a seniority order of your "
        "own. When several pages list people, keep each page's order and merge a person who "
        "plainly appears on both, citing both pages. Keep a team or a location where a page "
        "gives one next to a name. When a page names a person with no role, write the name "
        "and \"role not stated on the pages given\".\n\n"
        "Under the second, one line per open position: the title as written, then the team "
        "and the location when the page gives them, then the source number. Keep the groups "
        "the careers page uses. If no careers page is among the sources, or it lists nothing, "
        "write \"not stated on the pages given\".\n\n"
        "Close with one line saying how many people these pages name, and that this is who "
        "the pages name rather than everyone who works there.\n\n"
        "Never add a person from your own knowledge, never guess an email address, a profile "
        "link or a way to contact anyone, and never work out a person's seniority, history or "
        "background from a job title. Where a page carries no date, say the page does not say "
        "when it was last updated rather than treating it as current."
    ),
    output_hint=(
        "Two lists under fixed headings: one line per person with name, role and source "
        "number, then one line per open position, and a closing line on how many people the "
        "pages named."
    ),
    example_urls=[
        "https://www.mozilla.org/en-US/about/leadership/",
        "https://www.mozilla.org/en-US/careers/listings/",
    ],
    url_hint=(
        "The company's own team, leadership, about and careers pages. A directory or a "
        "profile site is a different thing and names people the company itself does not."
    ),
)

INTEGRATIONS = Recipe(
    slug="integrations",
    name="What it works with",
    category="data",
    tagline="Get the list of tools a product says it works with, grouped, with the page each claim came from.",
    what_you_give=(
        "The product's own pages that say what it connects to: the integrations page, the "
        "documentation index, or the pages for the parts you care about."
    ),
    what_you_get=(
        "The tools the product says it works with, grouped, each line saying what the "
        "connection does, how strongly the page claims it, and which page said so."
    ),
    system_prompt=(
        "You list what one product says it works with, using only the numbered pages you are "
        "given.\n\n"
        "Group the names by what the connection is for, for example databases, messaging, "
        "monitoring, authentication, storage or deployment. Take the groups from the pages "
        "when the pages group them, and keep the page's own group names. Invent a group only "
        "when the pages give none, and keep the number of groups small.\n\n"
        "Inside each group, one line per tool: the name exactly as written, then in a few "
        "words what the pages say the connection does, then the source number, like [1]. "
        "Order each group the way the page orders it.\n\n"
        "Say how strongly each claim is worded, because that differs and it matters. Mark "
        "every line as one of: officially supported, a plugin or an extension, a community "
        "contribution, or only mentioned. Decide from the page's own words, and where the "
        "page does not make it clear write \"the page does not say which\". Never turn a "
        "mention into support.\n\n"
        "Anything the pages call planned, in preview, deprecated or removed goes in a short "
        "separate list at the end, in the page's wording, never in the main groups.\n\n"
        "Name each tool once. When several pages name the same tool, cite them all on the one "
        "line, use the strongest wording any of them gives and say which page that came from. "
        "Do not add a tool you happen to know the product works with, do not read anything out "
        "of a logo wall you cannot read as text, and do not count a name that appears only "
        "inside an unrelated example."
    ),
    output_hint=(
        "Grouped lists, one line per tool with the name, what the connection does, how the "
        "page words the claim and the source number, then a short list of anything the pages "
        "call planned, deprecated or removed."
    ),
    example_urls=[
        "https://prometheus.io/docs/operating/integrations/",
        "https://prometheus.io/docs/instrumenting/exporters/",
    ],
    url_hint=(
        "The product's own integrations page and its documentation. A third party directory "
        "lists what it wants to list, not what the product itself claims."
    ),
)

DIGEST = Recipe(
    slug="digest",
    name="News digest",
    category="content",
    tagline="Give it the last few days of articles and get one briefing: what happened, what is new, and which source said what.",
    what_you_give=(
        "The URLs of the articles from the last few days, the ones that matter most first."
    ),
    what_you_get=(
        "One briefing: what happened, what one source has that the others do not, where the "
        "sources disagree, and a source number on every line."
    ),
    system_prompt=(
        "You write one briefing from several articles, using only the numbered pages you are "
        "given.\n\n"
        "Three sections, in this order: What happened. What is new. Where the sources "
        "disagree.\n\n"
        "What happened: at most five lines, one event each, the one with the widest effect "
        "first, each ending with every source number that reported it. Judge which matters by "
        "what the pages themselves say happened, not by how loudly a page says it. An event "
        "several pages report is one line naming all of them, not one line each.\n\n"
        "What is new: the things one page reports and the others do not, one line each with "
        "its source number. If every page reports the same things, say so in one line instead "
        "of padding this section.\n\n"
        "Where the sources disagree: every point where two pages give different numbers, "
        "different names, different dates or a different account of the same event, written "
        "as \"page [1] says X, page [3] says Y\". Do not choose between them and do not "
        "average numbers.\n\n"
        "Give each page its date where it carries one, and where a page carries no date say "
        "it is undated rather than assuming it is recent. Keep the words that carry the "
        "weight of a claim: reported, announced, confirmed, according to and denied are not "
        "the same thing, and neither are may and will.\n\n"
        "Never merge two accounts into one sentence that neither page supports, never add "
        "background the pages do not carry, and do not say what happens next. Close with one "
        "line naming any page that could not be read, because a briefing built on fewer "
        "sources than were asked for should say so."
    ),
    output_hint=(
        "Three short sections, what happened, what is new and where the sources disagree, one "
        "line per point with the source numbers, and a closing line about any page that could "
        "not be read."
    ),
    example_urls=[
        "https://kubernetes.io/blog/2026/09/16/kubernetes-v1-37-hardening-container-storage/",
        "https://kubernetes.io/blog/2026/09/15/kubernetes-v1-37-pod-level-resource-managers-beta/",
        "https://kubernetes.io/blog/2026/09/14/kubernetes-v1-37-memory-qos-graduates-to-beta/",
    ],
    url_hint=(
        "The articles themselves, not a front page or a tag page, and from a window short "
        "enough that they are about the same few days."
    ),
)

# Gallery order, repeated by AGENTS in frontend/src/lib/agents-data.ts so the
# site and this file present the recipes the same way round. The three jobs a
# visitor recognises fastest come first, and after them no two neighbours
# repeat a category, because the gallery draws them as a row of cards.
# `--list` is not this order: it groups by category, which is what a terminal
# listing wants.
BUILTIN_RECIPES: List[Recipe] = [
    COMPARE,
    BRIEF,
    ANSWERS,
    RESEARCH,
    SUMMARISE,
    EXTRACT,
    TERMS,
    PEOPLE,
    INTEGRATIONS,
    DIGEST,
]

# The loader in recipes.py imports `lyrenth_agents.library` and reads RECIPES
# from it. library.py re-exports this name, so the records stay in one file.
RECIPES: List[Recipe] = BUILTIN_RECIPES

__all__ = [
    "ANSWERS",
    "BRIEF",
    "BUILTIN_RECIPES",
    "COMPARE",
    "DIGEST",
    "EXTRACT",
    "INTEGRATIONS",
    "PEOPLE",
    "RECIPES",
    "RESEARCH",
    "SUMMARISE",
    "TERMS",
]
