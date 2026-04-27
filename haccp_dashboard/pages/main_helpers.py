"""Compatibility shim.

All attributes are forwarded to ``haccp_dashboard.lib.main_helpers``.
This file exists so that ``app.py`` can import from
``haccp_dashboard.pages.main_helpers`` without change.
"""

from __future__ import annotations

import importlib
from typing import Any

_TARGET = "haccp_dashboard.lib.main_helpers"


def _load():
    return importlib.import_module(_TARGET)


def __getattr__(name: str) -> Any:
    return getattr(_load(), name)


def __dir__() -> list[str]:
    module = _load()
    return sorted(set(globals().keys()) | set(dir(module)))
