"""Write docs/api/openapi.json from the FastAPI app (the code is the source of truth). --check compares."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def render() -> str:
    from healthlake.api.app import app

    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    target = ROOT / "docs" / "api" / "openapi.json"
    content = render()
    if "--check" in sys.argv:
        sys.exit(0 if target.exists() and target.read_text() == content else 1)
    target.write_text(content)
