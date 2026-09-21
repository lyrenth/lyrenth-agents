# lyrenth-agents

Ten agents that read the web and finish the job.

Give one a few URLs and it hands back the thing you actually wanted: a
comparison table, a brief on a company, the answer to a documentation
question with the heading it came from, a sheet you open in Excel. Every
claim carries the number of the page it came from, and every page that
could not be read is named with the reason.

The reading goes through [Lyrenth](https://lyrenth.com), which serves each
page as clean text instead of HTML, so the pages arrive without the menus,
banners, scripts and markup.

```bash
export LYRENTH_API_KEY=...        # free key: https://lyrenth.com/signup

uvx lyrenth-agents compare \
  https://en.wikipedia.org/wiki/PostgreSQL \
  https://en.wikipedia.org/wiki/MySQL
```

With that key alone, the agent reads the pages and prints the finished
prompt with its numbered sources, ready to paste into whichever assistant
you already use. Point it at a model and it answers on its own:

```bash
export LLM_BASE_URL=https://api.example.com/v1   # any OpenAI-compatible endpoint
export LLM_MODEL=your-model-name
export LLM_API_KEY=...
```

## The ten

| Command | Give it | Get back |
|---|---|---|
| `compare` | Two or more product pages | One table of what is actually different |
| `brief` | A company's own pages | What they do, who they sell to, and what their pages never answer |
| `answers -q "..."` | The documentation that should hold the answer | The answer with the page and heading behind every line |
| `research -q "..."` | The pages you trust | Plain prose with a number on every claim |
| `summarise` | A long article | What it claims, what that rests on, what it leaves out |
| `extract` | Several pages of the same kind | One row per page, a column for every shared field |
| `terms` | A terms page or a privacy policy | What you agree to, what data is taken, what happens in a dispute |
| `people` | A team page and a careers page | Who the pages name, and what the company is hiring for |
| `integrations` | The pages that say what a product connects to | The tools, grouped, and how firmly each one is claimed |
| `digest` | The last few days of articles | What happened, what is new, where the sources disagree |

`lyrenth-agents --list` prints the same list with an example command for
each one. Every agent also has a page at
[lyrenth.com/agents](https://lyrenth.com/agents) showing a real run.

## A real run

Against the live API on 21 September 2026, unedited. The progress lines go
to stderr, the answer to stdout.

```text
$ uvx lyrenth-agents compare https://en.wikipedia.org/wiki/PostgreSQL https://en.wikipedia.org/wiki/MySQL
recipe   compare: Product comparison
read [1] PostgreSQL - Wikipedia  30,000 tokens  https://en.wikipedia.org/wiki/PostgreSQL
read [2] MySQL - Wikipedia  30,000 tokens  https://en.wikipedia.org/wiki/MySQL
context  60,000 tokens from 2 sources (raw HTML would be 412,333)

| Feature | PostgreSQL | MySQL |
| :--- | :--- | :--- |
| Software Type | Free and open-source object relational database management system [1] | free and open-source relational database management system (RDBMS) [2] |
| License | PostgreSQL License (free and open-source, permissive) [1] | GPLv2 or proprietary [2] |
| Developer | PostgreSQL Global Development Group [1] | Oracle Corporation [2] |
| Initial Release | 8 July 1996; 30 years ago (1996-07-08) [1] | 23 May 1995; 31 years ago (1995-05-23) [2] |
| Stable Release | 18.6 / 13 August 2026 [1] | 26.7.0 / 28 July 2026 [2] |
| Written In | C (and C++ for the LLVM dependency) [1] | C, C++ [2] |
...
```

Two encyclopedia articles that weigh 412,333 tokens as raw HTML arrived as
60,000 tokens of text, and the answer cites which of the two every cell
came from.

## What it does with the pages

1. **Reads text, not markup.** Each page arrives as an AIDocument: the
   content, its canonical URL, when it was read, and what it costs in
   tokens.
2. **Shares the budget between the pages.** Every page gets an equal share
   and a short page gives its leftover back to the long ones, so a
   comparison never comes back with one product filled in and the other
   column empty.
3. **Reads each page once.** A mobile copy, a tracking parameter or an old
   redirect resolves to the same canonical URL and is dropped as a
   duplicate.
4. **Keeps provenance.** Title, canonical URL and read time go into the
   prompt with the source number, which is what makes the citations
   checkable.
5. **Fails out loud.** A page that could not be read is listed with the
   reason, and a citation pointing at a source number that does not exist
   is flagged.

## Write your own

A recipe is data: the instructions for the model and the shape of the
output. Register one and it runs on the same engine.

```python
from lyrenth_agents import Recipe, get, register, run

register(
    Recipe(
        slug="changelog",
        name="Release notes",
        category="content",
        tagline="Turn release pages into one list of what changed.",
        what_you_give="The release or changelog pages, newest first.",
        what_you_get="One list of changes, newest first, with the page each came from.",
        system_prompt="You read release pages and list what changed...",
        output_hint="One list, newest first, with a source number on every line.",
        example_urls=["https://example.com/releases"],
    )
)

result = run(get("changelog"), ["https://example.com/releases"])
print(result.answer or result.prompt)
```

## Options

| Flag | What it does |
|---|---|
| `--list` | The recipes, with an example command for each |
| `-q`, `--question` | What to ask of the pages (`answers` and `research` need one) |
| `--sources-only` | Print the numbered sources and stop |
| `--json` | The whole result as JSON, including the prompt |
| `--budget` | Token budget for all the pages together |
| `--fresh` | Ask Lyrenth for a fresh fetch instead of the stored page |
| `--model-url`, `--model` | The model endpoint, instead of the environment |

## Licence

MIT. See [LICENSE](LICENSE).
