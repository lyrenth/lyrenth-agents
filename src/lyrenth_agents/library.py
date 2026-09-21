"""The recipe library the loader looks for.

`recipes.py` imports this module and reads `RECIPES` from it. The records
themselves live in `recipes_builtin.py`, one file holding all the recipe
text, so there is a single place to read and edit the words. This module
only points at them.
"""

from __future__ import annotations

from .recipes_builtin import RECIPES

__all__ = ["RECIPES"]
