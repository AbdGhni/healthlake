"""Definition, formula, source, grain, period and limits of every indicator shown in the dashboard."""

from __future__ import annotations

from typing import TypedDict


class Indicator(TypedDict):
    label: str
    definition: str
    formula: str
    source: str
    grain: str
    period: str
    limits: str


_PERIOD = "All events of the pinned release (Synthea history: 5 years before 2026-01-01)."

INDICATORS: dict[str, Indicator] = {
    "patients": {
        "label": "Synthetic patients",
        "definition": "Distinct synthetic patient identities in the release.",
        "formula": "count(dim_patient)",
        "source": "GET /v1/summary -> patients",
        "grain": "patient identity",
        "period": _PERIOD,
        "limits": "Identities are per source: the same person in two sources would count twice (no cross-source "
        "merge, by design).",
    },
    "encounters": {
        "label": "Encounters",
        "definition": "Encounter identities, any class and status.",
        "formula": "count(fct_encounter)",
        "source": "GET /v1/summary -> encounters",
        "grain": "encounter",
        "period": _PERIOD,
        "limits": "Includes encounters still open (no end).",
    },
    "ambulatory": {
        "label": "Outpatient visits",
        "definition": "Encounters whose class maps to 'ambulatory' (AMB, SS, PRENC).",
        "formula": "count(fct_encounter where encounter_category = 'ambulatory')",
        "source": "GET /v1/summary -> encounters_by_category",
        "grain": "encounter",
        "period": _PERIOD,
        "limits": "Mapping from HL7 v3 ActCode in seed encounter_class_category.",
    },
    "inpatient": {
        "label": "Hospitalisations",
        "definition": "Encounters whose class maps to 'inpatient' (IMP, ACUTE, NONAC).",
        "formula": "count(fct_encounter where encounter_category = 'inpatient')",
        "source": "GET /v1/summary -> encounters_by_category",
        "grain": "encounter",
        "period": _PERIOD,
        "limits": "Emergency encounters are counted separately.",
    },
    "conditions": {
        "label": "Diagnoses recorded",
        "definition": "Condition identities (encounter diagnoses and problems).",
        "formula": "count(fct_condition)",
        "source": "GET /v1/summary -> conditions",
        "grain": "condition",
        "period": _PERIOD,
        "limits": "Synthea records social findings (e.g. employment) as conditions.",
    },
    "diagnosis_codes": {
        "label": "Distinct diagnosis codes",
        "definition": "Distinct (system, code) pairs used by conditions.",
        "formula": "count(agg_diagnosis)",
        "source": "GET /v1/summary -> distinct_diagnosis_codes",
        "grain": "code",
        "period": _PERIOD,
        "limits": "Codes are not validated against a terminology server.",
    },
    "observations": {
        "label": "Observations",
        "definition": "Observation identities (vital signs, labs, surveys...).",
        "formula": "count(fct_observation)",
        "source": "GET /v1/summary -> observations",
        "grain": "observation",
        "period": _PERIOD,
        "limits": "Panels count once; their components are counted separately.",
    },
    "components": {
        "label": "Observation components",
        "definition": "Components of observations (e.g. systolic/diastolic).",
        "formula": "count(fct_observation_component)",
        "source": "GET /v1/summary -> observation_components",
        "grain": "component",
        "period": _PERIOD,
        "limits": "-",
    },
    "prescriptions": {
        "label": "Prescriptions",
        "definition": "MedicationRequest identities, any status.",
        "formula": "count(fct_medication_request)",
        "source": "GET /v1/summary -> medication_requests",
        "grain": "medication request",
        "period": _PERIOD,
        "limits": "A request is not a dispensation.",
    },
    "patients_per_dx": {
        "label": "Patients per diagnosis",
        "definition": "Distinct patients having at least one condition with the code.",
        "formula": "count(distinct patient_key) per code_key",
        "source": "GET /v1/diagnoses",
        "grain": "diagnosis code",
        "period": _PERIOD,
        "limits": "Not additive across codes (a patient has several diagnoses).",
    },
    "daily_activity": {
        "label": "Encounters per month",
        "definition": "Encounters by start month (UTC) and category.",
        "formula": "sum(agg_activity_daily.encounters) per month and category",
        "source": "GET /v1/encounters?group_by=day",
        "grain": "month x category",
        "period": "Filter above (dates are UTC, [start, end)).",
        "limits": "Encounters without a start instant are not dated and not shown.",
    },
    "obs_volume": {
        "label": "Observation volume by code",
        "definition": "Observations per (code, value type, unit).",
        "formula": "agg_observation_volume.observations",
        "source": "GET /v1/observations?group_by=code",
        "grain": "code x value type x unit",
        "period": _PERIOD,
        "limits": "Min/mean/max are computed per code and unit only; never across units.",
    },
    "reject_rate": {
        "label": "Rejection rate (new resources)",
        "definition": "Share of new resources of a processing that were rejected and quarantined.",
        "formula": "rejected_new / received_new per processing",
        "source": "GET /v1/quality -> processings",
        "grain": "processing (batch)",
        "period": "Processings included in the release",
        "limits": "Gate threshold 1 % is a demonstration policy, not a medical threshold.",
    },
    "terminology": {
        "label": "Terminology coverage",
        "definition": "Share of codings whose code system URI is a known system (SNOMED CT, LOINC, RxNorm, HL7...).",
        "formula": "codings with known system / all codings of the release snapshot",
        "source": "GET /v1/quality -> release.terminology_coverage",
        "grain": "release",
        "period": "Release",
        "limits": "Checks the system URI only. Codes are NOT validated against a terminology server.",
    },
    "freshness": {
        "label": "Publication age",
        "definition": "Time since the active release was published.",
        "formula": "now - published_at",
        "source": "GET /v1/releases/current",
        "grain": "release",
        "period": "Now",
        "limits": "Depends on the dashboard clock (UTC).",
    },
    "event_age": {
        "label": "Age of latest clinical event",
        "definition": "Days between the latest encounter start and the batches' reference date.",
        "formula": "reference_date - max(encounter.start)",
        "source": "GET /v1/quality -> release.freshness_clinical_data",
        "grain": "release",
        "period": "Release",
        "limits": "Synthetic data are generated up to 2026-01-01.",
    },
    "pipeline_runs": {
        "label": "Pipeline runs",
        "definition": "Ingestion attempts and their outcome.",
        "formula": "ctl.attempt, most recent first",
        "source": "GET /v1/pipeline-runs",
        "grain": "attempt",
        "period": "Latest 200 attempts",
        "limits": "Duration = attempt start to finish (Silver load).",
    },
}


def help_text(key: str) -> str:
    i = INDICATORS[key]
    return (
        f"{i['definition']}  \nFormula: {i['formula']}  \nSource: {i['source']}  \nGrain: {i['grain']}  \n"
        f"Period: {i['period']}  \nLimits: {i['limits']}"
    )
