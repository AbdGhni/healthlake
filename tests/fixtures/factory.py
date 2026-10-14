"""Small, readable synthetic fixtures (no Java needed). All identifiers are invented."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from healthlake.generation.batch_writer import write_batch
from healthlake.generation.derive import to_csv_files, to_json_files

NPI = "http://hl7.org/fhir/sid/us-npi"
SYN = "https://github.com/synthetichealth/synthea"
GEN = {"name": "healthlake-test-fixtures", "version": "1", "parameters": {}}


def u(n: int, kind: str = "0000") -> str:
    return f"00000000-{kind}-4000-8000-{n:012d}"


def fhir_population(n_patients: int = 2, obs_per_patient: int = 3) -> list[dict[str, Any]]:
    """List of Bundle.entry dicts (fullUrl + resource + request), Synthea-like references."""
    org = {
        "resourceType": "Organization",
        "id": u(1, "0001"),
        "identifier": [{"system": SYN, "value": u(1, "0001")}],
        "name": "Clinique Fictive Horizon",
        "active": True,
    }
    prac = {
        "resourceType": "Practitioner",
        "id": u(1, "0002"),
        "identifier": [{"system": NPI, "value": "9990000001"}],
        "gender": "female",
        "active": True,
    }
    entries = [_e(org), _e(prac)]
    for p in range(1, n_patients + 1):
        pid = u(p, "0003")
        entries.append(
            _e(
                {
                    "resourceType": "Patient",
                    "id": pid,
                    "identifier": [{"system": SYN, "value": pid}],
                    "gender": "female" if p % 2 else "male",
                    "birthDate": f"{1940 + p % 60}-0{p % 9 + 1}-15",
                }
            )
        )
        enc = u(p, "0004")
        entries.append(
            _e(
                {
                    "resourceType": "Encounter",
                    "id": enc,
                    "status": "finished",
                    "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB"},
                    "type": [
                        {
                            "coding": [
                                {
                                    "system": "http://snomed.info/sct",
                                    "code": "185349003",
                                    "display": "Check up",
                                }
                            ]
                        }
                    ],
                    "subject": {"reference": f"urn:uuid:{pid}"},
                    "participant": [{"individual": {"reference": f"Practitioner?identifier={NPI}|9990000001"}}],
                    "period": {"start": "2025-03-01T09:00:00+00:00", "end": "2025-03-01T09:30:00+00:00"},
                    "serviceProvider": {"reference": f"Organization?identifier={SYN}|{u(1, '0001')}"},
                }
            )
        )
        entries.append(
            _e(
                {
                    "resourceType": "Condition",
                    "id": u(p, "0005"),
                    "clinicalStatus": {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                                "code": "active",
                            }
                        ]
                    },
                    "code": {
                        "coding": [{"system": "http://snomed.info/sct", "code": "44054006", "display": "Diabetes"}]
                    },
                    "subject": {"reference": f"urn:uuid:{pid}"},
                    "encounter": {"reference": f"urn:uuid:{enc}"},
                    "onsetDateTime": "2025-03-01T09:10:00+00:00",
                }
            )
        )
        for k in range(obs_per_patient):
            entries.append(
                _e(
                    {
                        "resourceType": "Observation",
                        "id": u(p * 1000 + k, "0006"),
                        "status": "final",
                        "code": {
                            "coding": [{"system": "http://loinc.org", "code": "8302-2", "display": "Body height"}]
                        },
                        "subject": {"reference": f"urn:uuid:{pid}"},
                        "encounter": {"reference": f"urn:uuid:{enc}"},
                        "effectiveDateTime": "2025-03-01T09:05:00+00:00",
                        "valueQuantity": {
                            "value": 160.5 + k,
                            "unit": "cm",
                            "system": "http://unitsofmeasure.org",
                            "code": "cm",
                        },
                    }
                )
            )
        entries.append(
            _e(
                {
                    "resourceType": "MedicationRequest",
                    "id": u(p, "0007"),
                    "status": "active",
                    "intent": "order",
                    "medicationCodeableConcept": {
                        "coding": [
                            {
                                "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                                "code": "860975",
                                "display": "metformin",
                            }
                        ]
                    },
                    "subject": {"reference": f"urn:uuid:{pid}"},
                    "encounter": {"reference": f"urn:uuid:{enc}"},
                    "authoredOn": "2025-03-01T09:20:00+00:00",
                    "requester": {"reference": f"Practitioner?identifier={NPI}|9990000001"},
                }
            )
        )
    return entries


def _e(res: dict[str, Any]) -> dict[str, Any]:
    return {
        "fullUrl": f"urn:uuid:{res['id']}",
        "resource": res,
        "request": {"method": "POST", "url": res["resourceType"]},
    }


def bundle_bytes(entries: list[dict[str, Any]]) -> bytes:
    return json.dumps({"resourceType": "Bundle", "type": "transaction", "entry": entries}, indent=1).encode()


def write_fhir_batch(
    landing: Path,
    entries: list[dict[str, Any]],
    revision: int = 1,
    extra_files: dict[str, bytes] | None = None,
    source_id: str = "horizon-central",
) -> str:
    files = {"patients/bundle.json": bundle_bytes(entries), **(extra_files or {})}
    _, bid = write_batch(
        landing,
        source_id,
        revision,
        "fhir-r4-bundle",
        "fhir-4.0.1",
        "2026-01-01",
        GEN,
        files,
        dict.fromkeys(files, "application/fhir+json"),
    )
    return bid


def business_rows(n_patients: int = 2, obs_per_patient: int = 3, prefix: str = "") -> dict[str, list[dict[str, str]]]:
    rows: dict[str, list[dict[str, str]]] = {
        k: []
        for k in (
            "organizations.csv",
            "practitioners.csv",
            "patients.csv",
            "encounters.csv",
            "conditions.csv",
            "observations.csv",
            "observation_components.csv",
            "medication_requests.csv",
        )
    }
    rows["organizations.csv"].append(
        {"organization_id": f"{prefix}ORG1", "name": "Centre Fictif", "type_code": "prov", "active": "true"}
    )
    rows["practitioners.csv"].append(
        {"practitioner_id": f"{prefix}PR1", "npi": "9990000002", "gender": "male", "active": "true"}
    )
    for p in range(1, n_patients + 1):
        pid, enc = f"{prefix}P{p}", f"{prefix}E{p}"
        rows["patients.csv"].append(
            {
                "patient_id": pid,
                "gender": "female",
                "birth_date": "1980-05-01",
                "deceased_datetime": "",
                "managing_organization_id": f"{prefix}ORG1",
            }
        )
        rows["encounters.csv"].append(
            {
                "encounter_id": enc,
                "patient_id": pid,
                "organization_id": f"{prefix}ORG1",
                "practitioner_npi": "9990000002",
                "status": "finished",
                "class_code": "IMP",
                "type_system": "http://snomed.info/sct",
                "type_code": "32485007",
                "type_display": "Hospital admission",
                "start": "2025-04-01T08:00:00+00:00",
                "end": "2025-04-03T10:00:00+00:00",
            }
        )
        rows["conditions.csv"].append(
            {
                "condition_id": f"{prefix}C{p}",
                "patient_id": pid,
                "encounter_id": enc,
                "clinical_status": "active",
                "verification_status": "confirmed",
                "category": "encounter-diagnosis",
                "code_system": "http://snomed.info/sct",
                "code": "38341003",
                "display": "Hypertension",
                "onset": "2025-04-01T08:30:00+00:00",
                "abatement": "",
                "recorded": "",
            }
        )
        for k in range(obs_per_patient):
            rows["observations.csv"].append(
                {
                    "observation_id": f"{prefix}O{p}-{k}",
                    "patient_id": pid,
                    "encounter_id": enc,
                    "status": "final",
                    "category": "vital-signs",
                    "code_system": "http://loinc.org",
                    "code": "8867-4",
                    "display": "Heart rate",
                    "effective": "2025-04-01T09:00:00+00:00",
                    "value_type": "quantity",
                    "value": str(70 + k),
                    "unit": "/min",
                    "unit_code": "/min",
                    "value_code_system": "",
                    "value_code": "",
                    "value_code_display": "",
                    "data_absent_reason": "",
                }
            )
        rows["medication_requests.csv"].append(
            {
                "medication_request_id": f"{prefix}M{p}",
                "patient_id": pid,
                "encounter_id": enc,
                "requester_npi": "9990000002",
                "status": "active",
                "intent": "order",
                "medication_system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                "medication_code": "197361",
                "medication_display": "amlodipine",
                "authored": "2025-04-01T10:00:00+00:00",
            }
        )
    return rows


def write_csv_batch(
    landing: Path,
    rows: dict[str, list[dict[str, str]]],
    revision: int = 1,
    raw_override: dict[str, bytes] | None = None,
) -> str:
    files = {**to_csv_files(rows), **(raw_override or {})}
    _, bid = write_batch(
        landing, "horizon-nord", revision, "horizon-csv-v1", "horizon-csv-v1", "2026-01-01", GEN, files
    )
    return bid


def write_json_batch(landing: Path, rows: dict[str, list[dict[str, str]]], revision: int = 1) -> str:
    _, bid = write_batch(
        landing,
        "horizon-sud",
        revision,
        "horizon-json-v1",
        "horizon-json-v1",
        "2026-01-01",
        GEN,
        to_json_files(rows),
    )
    return bid


def clone(x: Any) -> Any:
    return copy.deepcopy(x)
