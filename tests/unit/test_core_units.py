from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest

from healthlake.errors import ConflictError, ContractError
from healthlake.fhirtypes import parse_date, parse_datetime
from healthlake.generation.batch_writer import write_batch
from healthlake.ids import batch_id, canonical_json, entity_id, release_schema
from healthlake.ingestion.manifest import parse_manifest, scan_batch_dir
from healthlake.ingestion.rawstore import IntegrityError, LocalRawStore
from healthlake.normalization.references import parse_reference
from tests.fixtures import factory as f


def test_canonical_json_is_order_independent() -> None:
    assert canonical_json({"b": 1, "a": "é"}) == canonical_json({"a": "é", "b": 1}) == '{"a":"é","b":1}'.encode()
    assert batch_id({"x": [1, 2]}) != batch_id({"x": [2, 1]})


def test_entity_ids_are_namespaced_per_source() -> None:
    assert entity_id("horizon-nord", "Patient", "P1") != entity_id("horizon-sud", "Patient", "P1")
    assert entity_id("horizon-nord", "Patient", "P1") == entity_id("horizon-nord", "Patient", "P1")
    assert entity_id("horizon-nord", "Patient", "P1") != entity_id("horizon-nord", "Encounter", "P1")


def test_release_schema_name_is_controlled() -> None:
    assert release_schema("a" * 64) == "release_aaaaaaaaaaaaaaaa"
    with pytest.raises(ValueError):
        release_schema("x; drop schema silver")


def test_batch_writer_is_atomic_and_deterministic(tmp_path: Path) -> None:
    rows = f.business_rows()
    b1 = f.write_csv_batch(tmp_path, rows)
    assert not list((tmp_path / "horizon-nord").glob(".tmp-*"))
    b_again = f.write_csv_batch(tmp_path, rows)
    assert b1 == b_again
    rows["patients.csv"][0]["gender"] = "male"
    with pytest.raises(ConflictError):
        f.write_csv_batch(tmp_path, rows)


def test_manifest_written_last_and_batch_id_matches(tmp_path: Path) -> None:
    final, bid = write_batch(
        tmp_path,
        "horizon-nord",
        3,
        "horizon-csv-v1",
        "horizon-csv-v1",
        "2026-01-01",
        f.GEN,
        {"b.csv": b"x\n", "a.csv": b"y\n"},
    )
    m = json.loads((final / "manifest.json").read_text())
    assert [x["path"] for x in m["files"]] == ["a.csv", "b.csv"]
    _, _, again = parse_manifest((final / "manifest.json").read_bytes())
    assert again == bid
    names = sorted(os.listdir(final))
    assert names == ["a.csv", "b.csv", "manifest.json"]


def test_symlink_refused(tmp_path: Path) -> None:
    d = tmp_path / "batch"
    d.mkdir()
    (d / "real.csv").write_text("x")
    (d / "link.csv").symlink_to(d / "real.csv")
    with pytest.raises(ContractError):
        scan_batch_dir(d)


def test_rawstore_never_overwrites_and_detects_tampering(tmp_path: Path) -> None:
    import hashlib

    store = LocalRawStore(tmp_path)
    data = b"synthetic bytes"
    h = hashlib.sha256(data).hexdigest()
    assert store.put_if_absent(h, io.BytesIO(data)) is True
    assert store.put_if_absent(h, io.BytesIO(data)) is False
    with pytest.raises(IntegrityError):
        store.put_if_absent("0" * 64, io.BytesIO(data))
    assert store.get(h) == data
    p = store.path(h)
    os.chmod(p, 0o644)
    p.write_bytes(b"tampered")
    assert store.verify(h) is False
    with pytest.raises(IntegrityError):
        store.get(h)
    rec = store.list_referenced_objects([h, "1" * 64])
    assert rec["corrupted"] == [h] and rec["missing"] == ["1" * 64]


@pytest.mark.parametrize(
    "raw,kind,ttype,tid",
    [
        ("urn:uuid:abc", "urn_uuid", None, "urn:uuid:abc"),
        ("Patient/123", "relative", "Patient", "123"),
        ("Patient/123/_history/2", "relative", "Patient", "123"),
        ("https://central.horizon.example/fhir/Patient/9", "absolute", "Patient", "9"),
        ("https://other.example/fhir/Patient/9", "external", None, None),
        ("#med1", "contained", None, "med1"),
        ("Practitioner?identifier=http://hl7.org/fhir/sid/us-npi|999", "identifier", "Practitioner", None),
        ("not a reference", "invalid", None, None),
    ],
)
def test_parse_reference(raw: str, kind: str, ttype: str | None, tid: str | None) -> None:
    pr = parse_reference("subject", {"reference": raw}, "https://central.horizon.example/fhir/")
    assert (pr.kind, pr.target_type, pr.target_id) == (kind, ttype, tid)


def test_logical_identifier_reference() -> None:
    pr = parse_reference("requester", {"type": "Practitioner", "identifier": {"system": "s", "value": "v"}}, None)
    assert (pr.kind, pr.target_type, pr.system, pr.value) == ("identifier", "Practitioner", "s", "v")


def test_time_precision_never_invents_dates() -> None:
    assert parse_date("1980").precision == "year" and parse_date("1980").day is None  # type: ignore[union-attr]
    assert parse_datetime("2020-05").precision == "month"  # type: ignore[union-attr]
    t = parse_datetime("2020-05-01T10:00:00+02:00")
    assert (
        t is not None and t.instant is not None and t.instant.hour == 8 and t.instant.utcoffset().total_seconds() == 0
    )
    assert parse_datetime("2020-05-01T10:00:00") is None  # time without zone is invalid in FHIR
    assert parse_date("2021-02-30") is None
