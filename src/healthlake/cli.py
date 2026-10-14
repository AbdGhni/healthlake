"""HealthLake command line. Prints one compact JSON document on stdout; logs go to stderr.

Exit codes (stable):
  0  success (including idempotent no-op)
  1  unexpected error
  2  invalid contract (manifest, file, parameters)
  3  blocking quality error
  4  transient technical error (safe to retry)
  5  identity / version conflict
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable
from typing import Any

from healthlake import __version__
from healthlake.errors import ContractError, ExitCode, HealthLakeError

Handler = Callable[[argparse.Namespace], dict[str, Any]]
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _hex64(v: str) -> str:
    if not HEX64.match(v):
        raise argparse.ArgumentTypeError("expected 64 lowercase hex characters")
    return v


def _doctor(_: argparse.Namespace) -> dict[str, Any]:
    from healthlake.doctor import run_doctor

    return run_doctor()


def _db_init(_: argparse.Namespace) -> dict[str, Any]:
    from healthlake.db.init import init_database

    return init_database()


def _generate(a: argparse.Namespace) -> dict[str, Any]:
    from healthlake.generation.pipeline import generate

    return generate(a.profile, a.revision, a.jar, a.sources)


def _discover(_: argparse.Namespace) -> dict[str, Any]:
    from healthlake.db import connect
    from healthlake.ingestion.registry import discover, ensure_sources
    from healthlake.pipelines.runner import landing, limits, sources_config

    with connect("ingest", autocommit=True) as conn:
        ensure_sources(conn, sources_config()["sources"])
        return discover(conn, landing(), limits())


def _verify(a: argparse.Namespace) -> dict[str, Any]:
    from healthlake.db import connect
    from healthlake.ingestion.registry import verify_batch
    from healthlake.pipelines.runner import landing

    with connect("ingest", autocommit=True) as conn:
        return verify_batch(conn, a.batch_id, landing())


def _start(a: argparse.Namespace) -> dict[str, Any]:
    from healthlake.db import connect
    from healthlake.ingestion.registry import start_attempt

    with connect("ingest", autocommit=True) as conn:
        return start_attempt(conn, a.batch_id, a.run_id)


def _step(name: str) -> Handler:
    def handler(a: argparse.Namespace) -> dict[str, Any]:
        from healthlake.pipelines import steps
        from healthlake.pipelines.runner import run_processing_step

        fn = steps.STEPS[name]
        return run_processing_step(
            a.processing_id, lambda c, ws: fn(c, a.processing_id, ws, a.attempt_id), a.attempt_id, name
        )

    return handler


def _finish(a: argparse.Namespace) -> dict[str, Any]:
    from healthlake.pipelines.steps import finish_attempt

    return finish_attempt(a.attempt_id)


def _inspect(a: argparse.Namespace) -> dict[str, Any]:
    from healthlake.pipelines.steps import inspect_attempt

    return inspect_attempt(a.attempt_id)


def _ingest(a: argparse.Namespace) -> dict[str, Any]:
    from healthlake.pipelines.steps import ingest_batch

    return ingest_batch(a.batch_id, a.run_id)


def _build_release(a: argparse.Namespace) -> dict[str, Any]:
    from healthlake.release.build import build_release

    return build_release(a.processing_id)


def _build_snapshot(a: argparse.Namespace) -> dict[str, Any]:
    from healthlake.release.build import prepare_release

    return prepare_release(a.processing_id)


def _dbt_build(a: argparse.Namespace) -> dict[str, Any]:
    from healthlake.release.build import dbt_build

    return dbt_build(a.release_id)


def _dbt_docs(a: argparse.Namespace) -> dict[str, Any]:
    from healthlake.release.build import dbt_docs

    return dbt_docs(a.release_id)


def _report(a: argparse.Namespace) -> dict[str, Any]:
    from healthlake.pipelines.steps import report_attempt

    return report_attempt(a.attempt_id, a.fail_on_unsuccessful)


def _backfill(a: argparse.Namespace) -> dict[str, Any]:
    from healthlake.pipelines.steps import backfill

    ids = [b.strip() for b in a.batch_list.split(",") if b.strip()]
    for b in ids:
        _hex64(b)
    return backfill(ids)


def _quality_gate(a: argparse.Namespace) -> dict[str, Any]:
    from healthlake.release.gate import quality_gate

    return quality_gate(a.release_id)


def _publish(a: argparse.Namespace) -> dict[str, Any]:
    from healthlake.release.publish import publish

    return publish(a.release_id)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="healthlake", description="HealthLake pipeline CLI")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="check configuration, database and tools").set_defaults(func=_doctor)
    sub.add_parser("db-init", help="apply migrations and create login users").set_defaults(func=_db_init)
    g = sub.add_parser("generate", help="generate synthetic batches with pinned Synthea")
    g.add_argument("--profile", choices=["test", "demo", "extended"], required=True)
    g.add_argument("--revision", type=int, default=1)
    g.add_argument("--jar", required=True)
    g.add_argument("--sources", nargs="*", default=None)
    g.set_defaults(func=_generate)
    sub.add_parser("discover", help="register finalized batches in the landing zone").set_defaults(func=_discover)
    v = sub.add_parser("verify", help="verify a registered batch against its manifest")
    v.add_argument("--batch-id", type=_hex64, required=True)
    v.set_defaults(func=_verify)
    s = sub.add_parser("start", help="create the processing (idempotent) and a new attempt")
    s.add_argument("--batch-id", type=_hex64, required=True)
    s.add_argument("--run-id", default=None, help="orchestrator run id")
    s.set_defaults(func=_start)
    for name, help_ in [
        ("archive", "copy batch files into Bronze"),
        ("adapt", "map files to FHIR R4 resources"),
        ("validate", "structural FHIR validation"),
        ("resolve", "resolve references, identities, duplicates"),
        ("classify", "persist quarantine and apply the processing gate"),
        ("normalize", "build Silver rows"),
        ("load", "atomic Silver load"),
    ]:
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("--processing-id", type=_hex64, required=True)
        sp.add_argument("--attempt-id", default=None)
        sp.set_defaults(func=_step(name))
    f = sub.add_parser("finish", help="close an attempt from the processing state")
    f.add_argument("--attempt-id", required=True)
    f.set_defaults(func=_finish)
    i = sub.add_parser("inspect", help="show an attempt, its processing and issues summary")
    i.add_argument("--attempt-id", required=True)
    i.set_defaults(func=_inspect)
    ig = sub.add_parser("ingest", help="run verify..load for one batch (local convenience)")
    ig.add_argument("--batch-id", type=_hex64, required=True)
    ig.add_argument("--run-id", default=None)
    ig.set_defaults(func=_ingest)
    br = sub.add_parser("build-release", help="snapshot all loaded processings and build Gold with dbt")
    br.add_argument("--processing-id", type=_hex64, default=None, help="require this processing in the release")
    br.set_defaults(func=_build_release)
    bs = sub.add_parser("build-snapshot", help="register a release and build its deterministic snapshot")
    bs.add_argument("--processing-id", type=_hex64, default=None)
    bs.set_defaults(func=_build_snapshot)
    for name, fn, help_ in [
        ("dbt-build", _dbt_build, "dbt build into the candidate schema"),
        ("dbt-docs", _dbt_docs, "dbt docs and lineage for a built release"),
    ]:
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("--release-id", type=_hex64, required=True)
        sp.set_defaults(func=fn)
    rp = sub.add_parser("report", help="write the attempt report (artifacts/reports)")
    rp.add_argument("--attempt-id", required=True)
    rp.add_argument("--fail-on-unsuccessful", action="store_true")
    rp.set_defaults(func=_report)
    bf = sub.add_parser("backfill", help="ingest a comma-separated list of batch ids in order")
    bf.add_argument("--batch-list", required=True)
    bf.set_defaults(func=_backfill)
    qg = sub.add_parser("quality-gate", help="evaluate a built release")
    qg.add_argument("--release-id", type=_hex64, required=True)
    qg.set_defaults(func=_quality_gate)
    pb = sub.add_parser("publish", help="atomically activate a release that passed its gate")
    pb.add_argument("--release-id", type=_hex64, required=True)
    pb.set_defaults(func=_publish)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(ExitCode.CONTRACT) if exc.code else 0
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
        import psycopg

        if isinstance(exc, psycopg.OperationalError):
            out = {
                "ok": False,
                "command": args.command,
                "error_code": "db_unavailable",
                "message": str(exc)[:300],
            }
            code = ExitCode.TRANSIENT
        else:
            out = {
                "ok": False,
                "command": args.command,
                "error_code": "unexpected",
                "message": repr(exc)[:500],
            }
            code = ExitCode.UNEXPECTED
    sys.stdout.write(json.dumps(out, separators=(",", ":"), sort_keys=True, default=str) + "\n")
    return int(code)


_ = ContractError

if __name__ == "__main__":
    raise SystemExit(main())
