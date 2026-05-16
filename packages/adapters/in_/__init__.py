"""India adapter package.

The folder is `in_` (with trailing underscore) because `in` is a Python
reserved keyword and would break `from packages.adapters.in import ...`.
Import as: `from packages.adapters.in_ import INAdapter`.
"""
from __future__ import annotations

from packages.adapters.in_.adapter import INAdapter

__all__ = ["INAdapter"]
