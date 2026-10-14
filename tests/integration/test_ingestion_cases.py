"""Data cases from section 19.1, run against PostgreSQL through the real pipeline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.fixtures import factory as f
from tests.integration.helpers import issues, one, run

from healthlake.db import connect
from healthlake.ingestion.registry import discover
from healthlake.pipelines.runner import limits

pytestmark = pytest.mark.db


def counts(pid: str) -> dict[str, int]:
    with connect("owner") as conn:
        return dict(
            conn.execute(
                "SELECT outcome, count(*) FROM bronze.resource_occurrence WHERE processing_id=%s GROUP BY 1",
                (pid,),
            ).fetchall()
        )


def test_normal_three_sources_reconcile(lake: dict[str, Path]) -> None:
    b1 = f.write_fhir_batch(lake["landing"], f.fhir_population())
    b2 = f.write_csv_batch(lake["landing"], f.business_rows())
    b3 = f.write_json_batch(lake["landing"], f.business_rows())
    for b in (b1, b2, b3):
        r = run(lake["landing"], b)
        assert r["ok"] and r["status"] == "succeeded", r
        c = counts(r["processing_id"])
        assert sum(c.values()) == r["counters"]["received"]
        assert c.get("rejected", 0) == 0
    assert one("SELECT count(*) FROM silver.patient") == 6
    assert one("SELECT count(*) FROM silver.observation_component") == 0
    assert one("SELECT count(DISTINCT source_id) FROM silver.encounter") == 3
    # same business ids in nord and sud (P1...) are distinct identities: namespace per source
    assert (
        one("SELECT count(DISTINCT entity_id) FROM silver.patient WHERE source_id IN ('horizon-nord','horizon-sud')")
        == 4
    )


def test_identical_replay_is_idempotent(lake: dict[str, Path]) -> None:
    b = f.write_csv_batch(lake["landing"], f.business_rows())
    r1 = run(lake["landing"], b)
    before = one("SELECT count(*) FROM silver.resource_version")
    r2 = run(lake["landing"], b)
    assert r1["ok"] and r2["ok"] and r1["processing_id"] == r2["processing_id"]
    assert one("SELECT count(*) FROM silver.resource_version") == before
    assert one("SELECT count(*) FROM bronze.resource_occurrence") == r1["counters"]["received"]
    assert one("SELECT count(*) FROM ctl.attempt WHERE status='succeeded'") == 2


def test_truncated_json_blocks_processing(lake: dict[str, Path]) -> None:
    good = f.bundle_bytes(f.fhir_population())
    b = f.write_fhir_batch(lake["landing"], f.fhir_population(), extra_files={"patients/broken.json": good[:500]})
    r = run(lake["landing"], b)
    assert not r["ok"] and r["exit_code"] == 3
    assert issues("json_unparseable")
    assert one("SELECT status FROM ctl.processing") == "blocked"
    assert one("SELECT count(*) FROM silver.resource_version") == 0


def test_invalid_csv_header_blocks(lake: dict[str, Path]) -> None:
    b = f.write_csv_batch(lake["landing"], f.business_rows(), raw_override={"patients.csv": b"id;sex\n1;f\n"})
    r = run(lake["landing"], b)
    assert not r["ok"] and r["exit_code"] == 3
    assert issues("header_mismatch")


def test_one_bad_csv_row_under_threshold_is_quarantined(lake: dict[str, Path]) -> None:
    rows = f.business_rows(n_patients=10, obs_per_patient=12)  # > 100 resources
    rows["observations.csv"][5]["value"] = "not-a-number"
    b = f.write_csv_batch(lake["landing"], rows)
    r = run(lake["landing"], b)
    assert r["ok"], r
    assert r["counters"]["rejected"] == 1 and r["counters"]["reject_rate_new"] <= 0.01
    (row,) = issues("row_unmappable")
    assert row[3].startswith("observations.csv#line=")


def test_bad_rows_over_threshold_block(lake: dict[str, Path]) -> None:
    rows = f.business_rows(n_patients=1, obs_per_patient=5)
    rows["observations.csv"][0]["status"] = "bogus"
    r = run(lake["landing"], f.write_csv_batch(lake["landing"], rows))
    assert not r["ok"] and "quarantine.reject_rate_new" in r["failed_checks"]


@pytest.mark.parametrize(
    "mutate,code",
    [
        (lambda m: m.update(synthetic=False), "manifest_invalid"),
        (lambda m: m["files"][0].update(path="../escape.json"), "manifest_invalid"),
        (lambda m: m["files"].reverse(), "manifest_invalid"),
    ],
)
def test_invalid_manifest_is_not_registered(lake: dict[str, Path], mutate, code) -> None:  # type: ignore[no-untyped-def]
    f.write_csv_batch(lake["landing"], f.business_rows())
    mpath = lake["landing"] / "horizon-nord" / "rev-000001" / "manifest.json"
    m = json.loads(mpath.read_text())
    mutate(m)
    mpath.write_text(json.dumps(m))
    with connect("ingest", autocommit=True) as conn:
        res = discover(conn, lake["landing"], limits())
    assert res["batches"][0]["error_code"] == code
    assert one("SELECT count(*) FROM ctl.batch") == 0


def test_altered_file_fails_verification(lake: dict[str, Path]) -> None:
    b = f.write_csv_batch(lake["landing"], f.business_rows())
    p = lake["landing"] / "horizon-nord" / "rev-000001" / "patients.csv"
    p.write_bytes(p.read_bytes().replace(b"female", b"male!!"))
    r = run(lake["landing"], b)
    assert not r["ok"] and r["exit_code"] == 2 and r["error_code"] == "batch_invalid"
    assert one("SELECT status FROM ctl.batch") == "invalid"


def test_undeclared_file_fails_verification(lake: dict[str, Path]) -> None:
    b = f.write_csv_batch(lake["landing"], f.business_rows())
    (lake["landing"] / "horizon-nord" / "rev-000001" / "extra.csv").write_text("x\n")
    r = run(lake["landing"], b)
    assert not r["ok"] and r["error_code"] == "batch_invalid"


def test_same_revision_different_content_is_a_conflict(lake: dict[str, Path]) -> None:
    b = f.write_csv_batch(lake["landing"], f.business_rows())
    assert run(lake["landing"], b)["ok"]
    # someone replaces the finalized revision directory with other content
    d = lake["landing"] / "horizon-nord" / "rev-000001"
    rows = f.business_rows()
    rows["patients.csv"][0]["gender"] = "male"
    import shutil

    shutil.rmtree(d)
    f.write_csv_batch(lake["landing"], rows)
    with connect("ingest", autocommit=True) as conn:
        res = discover(conn, lake["landing"], limits())
    assert res["batches"][0]["error_code"] == "revision_conflict"


def test_duplicate_file_stored_once(lake: dict[str, Path]) -> None:
    rows = f.business_rows()
    b1 = f.write_csv_batch(lake["landing"], rows, revision=1)
    rows["patients.csv"][0]["gender"] = "male"  # only patients.csv differs in revision 2
    b2 = f.write_csv_batch(lake["landing"], rows, revision=2)
    assert run(lake["landing"], b1)["ok"] and run(lake["landing"], b2)["ok"]
    assert one("SELECT count(*) FROM bronze.batch_file") == 16
    assert one("SELECT count(*) FROM bronze.file") == 9


def test_duplicate_resource_is_deduplicated(lake: dict[str, Path]) -> None:
    entries = f.fhir_population()
    entries.append(f.clone(entries[-1]))
    r = run(lake["landing"], f.write_fhir_batch(lake["landing"], entries))
    assert r["ok"] and r["counters"]["deduplicated"] == 1
    assert one("SELECT count(*) FROM silver.resource_lineage") == r["counters"]["received"]


def test_same_id_different_content_in_one_revision_blocks(lake: dict[str, Path]) -> None:
    entries = f.fhir_population()
    dup = f.clone(entries[-1])
    dup["resource"]["status"] = "stopped"
    entries.append(dup)
    r = run(lake["landing"], f.write_fhir_batch(lake["landing"], entries))
    assert not r["ok"] and issues("content_conflict")


def test_conflicting_identity_blocks_with_conflict_code(lake: dict[str, Path]) -> None:
    entries = f.fhir_population()
    second = f.clone(entries[1])
    second["resource"]["id"] = f.u(2, "0002")
    second["fullUrl"] = f"urn:uuid:{f.u(2, '0002')}"
    entries.insert(2, second)  # two practitioners claim the same NPI
    r = run(lake["landing"], f.write_fhir_batch(lake["landing"], entries))
    assert not r["ok"]
    assert issues("identity_conflict")
    assert issues("reference_ambiguous")  # references by that NPI cannot be resolved uniquely


def test_missing_patient_rejects_dependents(lake: dict[str, Path]) -> None:
    rows = f.business_rows(n_patients=30, obs_per_patient=4)
    rows["observations.csv"].append(
        {**rows["observations.csv"][0], "observation_id": "ORPHAN", "patient_id": "NOPE", "encounter_id": ""}
    )
    r = run(lake["landing"], f.write_csv_batch(lake["landing"], rows))
    assert r["ok"] and r["counters"]["rejected"] == 1
    assert issues("reference_unresolved")


def test_patient_encounter_mismatch_rejected(lake: dict[str, Path]) -> None:
    rows = f.business_rows(n_patients=30, obs_per_patient=4)
    rows["observations.csv"][0]["patient_id"] = "P2"  # encounter E1 belongs to P1
    r = run(lake["landing"], f.write_csv_batch(lake["landing"], rows))
    assert r["ok"] and r["counters"]["rejected"] == 1
    assert issues("patient_encounter_mismatch")


def test_rejected_patient_cascades_with_cause(lake: dict[str, Path]) -> None:
    rows = f.business_rows(n_patients=2, obs_per_patient=2)
    rows["patients.csv"][0]["gender"] = "dragon"
    r = run(lake["landing"], f.write_csv_batch(lake["landing"], rows))
    assert not r["ok"]  # 1 patient + its encounter + 4 dependents = far above 1 %
    dep = one(
        "SELECT count(*) FROM quality.issue WHERE cause_code='dependency_rejected' AND caused_by_issue_id IS NOT NULL"
    )
    assert dep >= 1


def test_contained_reference_partial_dates_absent_value_components_out_of_scope(
    lake: dict[str, Path],
) -> None:
    entries = f.fhir_population(n_patients=1)
    pid = f.u(1, "0003")
    entries[2]["resource"]["birthDate"] = "1980"
    entries[4]["resource"]["onsetDateTime"] = "2020-05"
    entries.append(
        f._e(
            {
                "resourceType": "Observation",
                "id": f.u(99, "0006"),
                "status": "final",
                "code": {
                    "coding": [{"system": "http://loinc.org", "code": "85354-9", "display": "Blood pressure panel"}]
                },
                "subject": {"reference": f"urn:uuid:{pid}"},
                "component": [
                    {
                        "code": {"coding": [{"system": "http://loinc.org", "code": "8480-6"}]},
                        "valueQuantity": {"value": 120, "unit": "mm[Hg]"},
                    },
                    {
                        "code": {"coding": [{"system": "http://loinc.org", "code": "8462-4"}]},
                        "dataAbsentReason": {"coding": [{"code": "not-performed"}]},
                    },
                ],
            }
        )
    )
    entries.append(
        f._e(
            {
                "resourceType": "Observation",
                "id": f.u(98, "0006"),
                "status": "final",
                "code": {"coding": [{"system": "http://loinc.org", "code": "2339-0"}]},
                "subject": {"reference": f"urn:uuid:{pid}"},
                "dataAbsentReason": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/data-absent-reason",
                            "code": "asked-unknown",
                        }
                    ]
                },
            }
        )
    )
    entries.append(
        f._e(
            {
                "resourceType": "Observation",
                "id": f.u(97, "0006"),
                "status": "final",
                "code": {"coding": [{"system": "http://loinc.org", "code": "72166-2"}]},
                "subject": {"reference": f"urn:uuid:{pid}"},
                "valueBoolean": False,
                "effectiveDateTime": "2025",
            }
        )
    )
    entries.append(
        f._e(
            {
                "resourceType": "MedicationRequest",
                "id": f.u(9, "0007"),
                "status": "active",
                "intent": "order",
                "contained": [
                    {
                        "resourceType": "Medication",
                        "id": "med1",
                        "code": {
                            "coding": [{"system": "http://www.nlm.nih.gov/research/umls/rxnorm", "code": "1049221"}]
                        },
                    }
                ],
                "medicationReference": {"reference": "#med1"},
                "subject": {"reference": f"urn:uuid:{pid}"},
            }
        )
    )
    entries.append(f._e({"resourceType": "Claim", "id": f.u(1, "0009"), "status": "active"}))
    r = run(lake["landing"], f.write_fhir_batch(lake["landing"], entries))
    assert r["ok"], r
    assert r["counters"]["out_of_scope"] == 1
    assert one("SELECT birth_date_precision || coalesce(birth_date::text,'-') FROM silver.patient") == "year-"
    assert one("SELECT onset_precision || coalesce(onset_at::text,'-') FROM silver.condition") == "month-"
    assert (
        one("SELECT value_type || data_absent_reason FROM silver.observation WHERE code='2339-0'")
        == "noneasked-unknown"
    )
    assert (
        one(
            "SELECT value_type || value_boolean::text || effective_precision"
            " FROM silver.observation WHERE code='72166-2'"
        )
        == "booleanfalseyear"
    )
    assert one("SELECT count(*) FROM silver.observation_component") == 2
    assert one("SELECT data_absent_reason FROM silver.observation_component WHERE code='8462-4'") == "not-performed"
    assert one("SELECT medication_code FROM silver.medication_request WHERE medication_code='1049221'") == "1049221"
    assert one("SELECT resolution_method FROM silver.reference WHERE path='medicationReference'") == "contained"
    assert one("SELECT resource->>'resourceType' FROM silver.resource_version WHERE NOT in_analytic_scope") == "Claim"


def test_inverted_period_rejected(lake: dict[str, Path]) -> None:
    rows = f.business_rows(n_patients=40, obs_per_patient=3)
    rows["encounters.csv"][0]["end"] = "2025-03-01T00:00:00+00:00"
    r = run(lake["landing"], f.write_csv_batch(lake["landing"], rows))
    assert issues("period_inverted")
    assert not r["ok"] or r["counters"]["rejected"] >= 1


def test_absolute_reference_with_declared_base_and_external_refused(lake: dict[str, Path]) -> None:
    entries = f.fhir_population(n_patients=40, obs_per_patient=1)
    pid = f.u(1, "0003")
    obs = next(e for e in entries if e["resource"]["resourceType"] == "Observation")
    obs["resource"]["subject"] = {"reference": f"https://central.horizon.example/fhir/Patient/{pid}"}
    obs2 = [e for e in entries if e["resource"]["resourceType"] == "Observation"][1]
    obs2["resource"]["subject"] = {"reference": "https://elsewhere.example/fhir/Patient/x"}
    r = run(lake["landing"], f.write_fhir_batch(lake["landing"], entries))
    assert r["ok"], r
    assert one("SELECT count(*) FROM silver.reference WHERE resolution_method='absolute'") == 1
    assert issues("reference_external")


def test_valid_update_invalid_update_and_backfill(lake: dict[str, Path]) -> None:
    rows = f.business_rows()
    b1 = f.write_csv_batch(lake["landing"], rows, revision=1)
    rows2 = f.clone(rows)
    rows2["patients.csv"][0]["gender"] = "male"
    b2 = f.write_csv_batch(lake["landing"], rows2, revision=2)
    # backfill: revision 2 arrives before revision 1
    assert run(lake["landing"], b2)["ok"]
    assert run(lake["landing"], b1)["ok"]
    latest = one(
        "SELECT p.gender FROM silver.processing_resource pr JOIN silver.patient p USING (resource_version_id)"
        " WHERE p.source_id='horizon-nord' AND pr.entity_id=(SELECT entity_id FROM silver.patient WHERE gender='male')"
        " ORDER BY pr.source_revision DESC LIMIT 1"
    )
    assert latest == "male"
    assert one("SELECT count(*) FROM silver.patient WHERE source_id='horizon-nord'") == 3  # 2 + 1 changed version
    rows3 = f.clone(rows2)
    rows3["patients.csv"][0]["birth_date"] = "1980-13-45"
    r3 = run(lake["landing"], f.write_csv_batch(lake["landing"], rows3, revision=3))
    assert not r3["ok"] and "identity.invalid_updates" in r3["failed_checks"]
    assert issues("invalid_update")


def test_cli_exit_codes(lake: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    from healthlake.cli import main

    assert main(["verify", "--batch-id", "nothex"]) == 2
    b = f.write_csv_batch(lake["landing"], f.business_rows())
    assert main(["discover"]) == 0
    assert main(["ingest", "--batch-id", b]) == 0
    out = capsys.readouterr().out.strip().splitlines()[-1]
    assert json.loads(out)["status"] == "succeeded"
