"""HealthLake command line. Prints one compact JSON document on stdout; logs go to stderr.

Exit codes (stable):
  0  success (including idempotent no-op)
  2  invalid contract (manifest, file, parameters)
  3  blocking quality error
  4  transient technical error (safe to retry)
  5  identity / version conflict
  1  unexpected error
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from typing import Any

from healthlake import __version__
from healthlake.errors import ExitCode, HealthLakeError

Handler = Callable[[argparse.Namespace], dict[str, Any]]


def _doctor(_: argparse.Namespace) -> dict[str, Any]:
    from healthlake.doctor import run_doctor

    return run_doctor()


def _db_init(_: argparse.Namespace) -> dict[str, Any]:
    from healthlake.db.init import init_database

    return init_database()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="healthlake", description="HealthLake pipeline CLI")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="check configuration, database and tools").set_defaults(func=_doctor)
    sub.add_parser("db-init", help="apply migrations and create login users").set_defaults(func=_db_init)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    func: Handler = args.func
    try:
        result = func(args)
        out = {"ok": True, "command": args.command, **result}
        code = ExitCode.OK
    except HealthLakeError as exc:
        out = {
            "ok": False,
            "command": args.command,
            "error_code": exc.code,
            "message": str(exc),
            **exc.details,
        }
        code = exc.exit_code
    except Exception as exc:
        out = {"ok": False, "command": args.command, "error_code": "unexpected", "message": repr(exc)}
        code = ExitCode.UNEXPECTED
    sys.stdout.write(json.dumps(out, separators=(",", ":"), sort_keys=True, default=str) + "\n")
    return int(code)


if __name__ == "__main__":
    raise SystemExit(main())
