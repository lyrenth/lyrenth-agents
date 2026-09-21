"""The library the loader looks for.

`recipes.py` imports this module and reads `RECIPES` from it. The records
themselves live next door: `recipes_builtin.py` holds the one-question
recipes and `flows_builtin.py` holds the agents that take several steps.
Both are registered the same way and both appear in the same list, because
from the outside they are all just agents you can run.

This module only points at them.
"""

from __future__ import annotations

from .flows_builtin import BUILTIN_FLOWS
from .recipes_builtin import RECIPES as BUILTIN_RECIPES

RECIPES = list(BUILTIN_RECIPES) + list(BUILTIN_FLOWS)

__all__ = ["RECIPES"]
