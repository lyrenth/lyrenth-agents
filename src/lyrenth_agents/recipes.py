"""What a recipe is, and where the installed ones come from.

A recipe is data, not a program. It carries the words that make one agent
different from another: what to tell the model, what shape the output should
take, what the person gives it and what they get back. The engine is the same
for all of them, so adding an agent means adding a record here, not writing
code.

The records themselves live in `lyrenth_agents.library`, which exposes
`RECIPES`. That module is written by whoever writes the recipe text. This
module only defines the shape, loads whatever is there, and keeps a bad or
missing library from taking the whole command down: if nothing loads, the
registry is empty and `--list` says so.
"""

from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass, field
from typing import Dict, List, Optional

__all__ = [
    "Recipe",
    "REGISTRY",
    "UnknownRecipe",
    "all_recipes",
    "get",
    "load_error",
    "register",
]

# Every field a recipe must carry. Checked when one is registered, so a
# half-written record is refused at import time instead of producing an agent
# that runs with an empty prompt.
# What anything in the registry has to say about itself, whether it is a
# one-question recipe or a flow with several steps. The command line and the
# website both print exactly these fields.
REQUIRED_TEXT_FIELDS = (
    "slug",
    "name",
    "category",
    "tagline",
    "what_you_give",
    "what_you_get",
)

# A one-question recipe carries its instructions directly. A flow carries
# steps instead, and its instructions live in those. One of the two.
RECIPE_ONLY_FIELDS = ("system_prompt", "output_hint")


@dataclass
class Recipe:
    """One agent, written down.

    slug            the name on the command line, lowercase with hyphens
    name            the human name, shown in the list and on the site
    category        groups the recipe in the list and in the gallery
    tagline         one plain sentence describing what it does
    what_you_give   what the person is expected to supply
    what_you_get    what comes back
    system_prompt   the instructions the model is given
    output_hint     the shape the answer should take
    example_urls    URLs that show the recipe working, used in the help text
    url_hint        optional extra note about which pages suit this recipe
    """

    slug: str
    name: str
    category: str
    tagline: str
    what_you_give: str
    what_you_get: str
    system_prompt: str
    output_hint: str
    example_urls: List[str] = field(default_factory=list)
    url_hint: Optional[str] = None


class UnknownRecipe(ValueError):
    """Asked for a recipe slug that is not registered."""


# Where the recipe records come from. The module must expose RECIPES, either a
# list of Recipe or a dict of slug to Recipe.
LIBRARY_MODULE = "lyrenth_agents.library"

REGISTRY: Dict[str, Recipe] = {}

# Why the library did not load, when it did not. `--list` shows this instead
# of pretending there are simply no recipes.
_LOAD_ERROR: Optional[str] = None


def load_error() -> Optional[str]:
    """The reason the recipe library failed to load, or None."""
    return _LOAD_ERROR


def register(recipe):
    """Put one recipe or flow in the registry, refusing anything malformed.

    Flows are not imported here on purpose. This module is imported by the
    engine, which the flow module imports in turn, so asking for the Flow
    type here would be a circle. A record is a flow if it carries steps, and
    a recipe if it carries the instructions itself; anything with neither is
    refused by name rather than by type.
    """
    steps = getattr(recipe, "steps", None)
    if not isinstance(recipe, Recipe) and steps is None:
        raise TypeError(f"expected a Recipe or a Flow, got {type(recipe).__name__}")
    missing = [f for f in REQUIRED_TEXT_FIELDS if not str(getattr(recipe, f, "") or "").strip()]
    if steps is None:
        missing += [f for f in RECIPE_ONLY_FIELDS if not str(getattr(recipe, f, "") or "").strip()]
    elif not steps:
        missing.append("steps")
    if missing:
        raise ValueError(
            f"recipe {getattr(recipe, 'slug', '') or '(no slug)'!r} is missing: {', '.join(missing)}"
        )
    if recipe.slug in REGISTRY:
        raise ValueError(f"two recipes share the slug {recipe.slug!r}")
    REGISTRY[recipe.slug] = recipe
    return recipe


def all_recipes() -> List[Recipe]:
    """Every registered recipe, ordered by category then name."""
    return sorted(REGISTRY.values(), key=lambda r: (r.category.lower(), r.name.lower()))


def get(slug: str) -> Recipe:
    """Look up one recipe, or raise an error that says what is available."""
    slug = (slug or "").strip()
    if slug in REGISTRY:
        return REGISTRY[slug]
    if not REGISTRY:
        raise UnknownRecipe(
            f"no recipe named {slug!r}, and no recipes are installed at all. "
            + (load_error() or "The recipe library is empty.")
        )
    available = ", ".join(sorted(REGISTRY))
    raise UnknownRecipe(f"no recipe named {slug!r}. Available recipes: {available}")


def _items_from(library) -> List[Recipe]:
    """Accept RECIPES as a list, a tuple or a dict of slug to Recipe."""
    found = getattr(library, "RECIPES", None)
    if found is None:
        raise ValueError("it does not define RECIPES")
    if isinstance(found, dict):
        return list(found.values())
    if isinstance(found, (list, tuple)):
        return list(found)
    raise ValueError(f"RECIPES is a {type(found).__name__}, expected a list or a dict")


def _load_library(module_name: str = LIBRARY_MODULE) -> Optional[str]:
    """Fill the registry from the recipe library, if there is one.

    A missing library is normal while the recipes are still being written and
    stays quiet. A library that exists but does not import, or that holds a
    malformed record, is recorded so the command can say what went wrong
    instead of reporting that there are simply no recipes. Returns the problem,
    or None when there was none.
    """
    global _LOAD_ERROR
    try:
        if importlib.util.find_spec(module_name) is None:
            return None
    except (ImportError, ValueError):
        return None
    try:
        library = importlib.import_module(module_name)
        for recipe in _items_from(library):
            register(recipe)
    except Exception as exc:  # noqa: BLE001 - one bad record must not kill the command
        _LOAD_ERROR = f"The recipe library could not be loaded: {exc}"
    return _LOAD_ERROR


_load_library()
