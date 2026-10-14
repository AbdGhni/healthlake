from __future__ import annotations

import json
from pathlib import Path

import pytest

from healthlake.cli import main
from healthlake.config import ConfigError, secret


def test_secret_file_wins_and_is_stripped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / "s"
    f.write_text("abc\n")
    monkeypatch.setenv("X_FILE", str(f))
    monkeypatch.setenv("X", "other")
    assert secret("X") == "abc"


def test_missing_required_secret_has_no_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NOPE", raising=False)
    monkeypatch.delenv("NOPE_FILE", raising=False)
    with pytest.raises(ConfigError):
        secret("NOPE")


def test_cli_reports_unreachable_db_as_transient(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HEALTHLAKE_DB_HOST", "127.0.0.1")
    monkeypatch.setenv("HEALTHLAKE_DB_PORT", "1")
    code = main(["doctor"])
    out = json.loads(capsys.readouterr().out)
    assert code == 4
    assert out["ok"] is False and out["error_code"] == "db_unreachable"
