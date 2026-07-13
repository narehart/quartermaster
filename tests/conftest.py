"""Shared test fixtures.

classify-mcp.py and enforce-agent-model.py are hyphenated filenames (not
importable via plain `import`), so they're loaded via importlib with an
explicit file location -- the standard technique for importing a module whose
path isn't a valid Python identifier.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


def load_script_module(filename: str, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, SCRIPTS_DIR / filename)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load spec for {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def classify_mcp() -> ModuleType:
    """A fresh module object per test -- module-level constants (HOME, CACHE,
    STATE_DIR, ...) are recomputed each time so monkeypatching one test's
    module attributes can never leak into another test."""
    return load_script_module("classify-mcp.py", "classify_mcp_under_test")


@pytest.fixture
def enforce_agent_model() -> ModuleType:
    return load_script_module("enforce-agent-model.py", "enforce_agent_model_under_test")
