"""Shared pytest fixtures.

Backend modules expect the project root on sys.path so `from backend import …`
resolves. pytest runs from the repo root by default, so this is mostly a
safety net for editor-driven runs.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Make the repo root importable as a package root for `backend.*`.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Tests run against in-process modules; we don't want the audit writer to
# accidentally touch a real DB if a test happens to import it. The actual
# DB-touching tests use their own SQLite tmp paths.
os.environ.setdefault("OPENAI_API_KEY", "test-placeholder")
