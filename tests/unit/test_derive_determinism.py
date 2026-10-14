from __future__ import annotations

from tests.fixtures import factory as f

from healthlake.generation.derive import extract_rows, to_csv_files, to_json_files


def test_derivation_is_deterministic_and_drops_names() -> None:
    files = {"patients/a.json": f.bundle_bytes(f.fhir_population(3))}
    a = to_csv_files(extract_rows(files))
    b = to_csv_files(extract_rows(dict(reversed(list(files.items())))))
    assert a == b
    assert b"family" not in b"".join(a.values())
    j = to_json_files(extract_rows(files))
    assert set(j) == {"reference-data.json", "records/records-0001.json"}
