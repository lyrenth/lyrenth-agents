"""A library of small agents that read the web through Lyrenth.

One engine, many recipes. A recipe is data: the instructions for the model and
the shape of the output. The engine reads the pages, numbers them so they can
be cited, and either asks a model or hands you the finished prompt.

    from lyrenth_agents import get, run

    result = run(get("some-recipe"), ["https://example.com/page"])
    print(result.answer or result.prompt)

Reading goes through Lyrenth (LYRENTH_API_KEY, free key at
https://lyrenth.com/signup). A model is optional: with none configured,
`result.answer` is None and `result.prompt` holds the finished prompt, ready
to paste into any assistant. Configure one with LLM_BASE_URL and LLM_MODEL
(any OpenAI-compatible endpoint) to have the engine answer directly.
"""

__version__ = "0.2.2"

from .engine import (  # noqa: E402
    AgentResult,
    Gathered,
    ModelError,
    Skipped,
    Source,
    answer_into,
    build_messages,
    build_prompt,
    build_sources_block,
    call_model,
    check_citations,
    gather,
    model_is_configured,
    read_for,
    run,
)
from .recipes import (  # noqa: E402
    REGISTRY,
    Recipe,
    UnknownRecipe,
    all_recipes,
    get,
    load_error,
    register,
)

__all__ = [
    "AgentResult",
    "Gathered",
    "ModelError",
    "REGISTRY",
    "Recipe",
    "Skipped",
    "Source",
    "UnknownRecipe",
    "all_recipes",
    "answer_into",
    "build_messages",
    "build_prompt",
    "build_sources_block",
    "call_model",
    "check_citations",
    "gather",
    "get",
    "load_error",
    "model_is_configured",
    "read_for",
    "register",
    "run",
    "__version__",
]
