"""Lightweight compatibility shim.

The real implementation lives in `lib.csv_inference_panel`.
Do not add heavy imports here.
"""

from __future__ import annotations

import importlib
from typing import Any

_TARGET = "lib.csv_inference_panel"


def _load():
    return importlib.import_module(_TARGET)


def __getattr__(name: str) -> Any:
    return getattr(_load(), name)


def __dir__() -> list[str]:
    module = _load()
    return sorted(set(globals().keys()) | set(dir(module)))
