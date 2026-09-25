from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))

FIXTURES = BACKEND / "tests" / "fixtures"
RUNS_DIR = FIXTURES / "n8n_runs"
JS_RUNNER = BACKEND / "tests" / "js_parity" / "run_node.js"

# tests never touch real services
os.environ.setdefault("GEMINI_API_KEY", "")
os.environ.setdefault("LLM_MODE", "replay")
os.environ.setdefault("LANGSMITH_TRACING", "false")


def load_runs() -> list[tuple[str, dict]]:
    idx = json.loads((RUNS_DIR / "INDEX.json").read_text(encoding="utf-8"))
    return [(r["name"], json.loads((RUNS_DIR / f"{r['name']}.json").read_text(encoding="utf-8"))) for r in idx]


@pytest.fixture(scope="session")
def n8n_runs() -> list[tuple[str, dict]]:
    return load_runs()


def run_js(requests: list[dict]) -> list:
    """Run original n8n node bodies in Node (batch)."""
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    out = subprocess.run(["node", str(JS_RUNNER)], input=json.dumps(requests, ensure_ascii=False),
                         capture_output=True, text=True, check=True, encoding="utf-8")
    return json.loads(out.stdout)


def roundtrip(o):
    """Normalise through JSON like n8n does between nodes."""
    return json.loads(json.dumps(o, ensure_ascii=False))
