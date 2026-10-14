from __future__ import annotations

import sys
from pathlib import Path

import pytest

DAGS = Path(__file__).resolve().parents[2] / "airflow" / "dags"

try:
    import airflow.sdk  # noqa: F401  (the repo folder airflow/ is a namespace package, not Airflow)
except ImportError:  # these tests run in the Airflow virtualenv only
    collect_ignore_glob = ["test_*.py"]
else:
    sys.path.insert(0, str(DAGS))


@pytest.fixture(scope="session")
def dagbag():  # type: ignore[no-untyped-def]
    from airflow.models.dagbag import DagBag

    return DagBag(dag_folder=str(DAGS))
