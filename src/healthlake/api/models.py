"""Pydantic response contracts (OpenAPI). Synthetic data only; no names, addresses or raw resources."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

SourceId = Literal["horizon-central", "horizon-nord", "horizon-sud"]


class PageMeta(BaseModel):
    limit: int
    next_cursor: str | None = Field(description="Opaque signed cursor; pins the release_id of the first page.")


class Page[T](BaseModel):
    release_id: str
    data: list[T]
    page: PageMeta


class ErrorBody(BaseModel):
    detail: str
    error_code: str


class Release(BaseModel):
    release_id: str
    status: str
    published_at: datetime | None
    created_at: datetime
    active: bool
    processings: int | None = None


class ReleaseList(BaseModel):
    active_release_id: str | None
    data: list[Release]


class Patient(BaseModel):
    patient_key: str
    source_id: str
    gender: str | None
    birth_year: int | None
    birth_date_precision: str | None
    deceased: bool


class Code(BaseModel):
    system: str | None
    code: str | None
    display: str | None


class Encounter(BaseModel):
    encounter_key: str
    patient_key: str
    source_id: str
    status: str
    class_code: str | None
    encounter_category: str
    type: Code | None
    start_at: datetime | None
    end_at: datetime | None
    duration_minutes: float | None


class ActivityDay(BaseModel):
    activity_date: date
    source_id: str
    encounter_category: str
    encounters: int
    distinct_patients: int


class Diagnosis(BaseModel):
    code_key: str
    system: str | None
    system_label: str
    code: str
    display: str | None
    conditions: int
    distinct_patients: int
    first_onset_at: datetime | None
    last_onset_at: datetime | None


class Observation(BaseModel):
    observation_key: str
    patient_key: str
    encounter_key: str | None
    source_id: str
    status: str
    category_code: str | None
    code: Code
    effective_at: datetime | None
    effective_precision: str | None
    value_type: str
    value_numeric: float | None
    value_unit_code: str | None
    value_string: str | None
    value_boolean: bool | None
    value_code: Code | None
    data_absent_reason: str | None
    component_count: int


class ObservationVolume(BaseModel):
    code_key: str
    system: str | None
    code: str
    display: str | None
    value_type: str
    value_unit_code: str | None
    observations: int
    numeric_values: int
    absent_values: int
    distinct_patients: int
    min_value: float | None
    mean_value: float | None
    max_value: float | None


class MedicationRequest(BaseModel):
    medication_request_key: str
    patient_key: str
    encounter_key: str | None
    source_id: str
    status: str
    intent: str
    authored_at: datetime | None
    medication: Code | None


class SourceCount(BaseModel):
    source_id: str
    patients: int
    encounters: int


class Summary(BaseModel):
    release_id: str
    published_at: datetime | None
    notice: str
    patients: int
    encounters: int
    encounters_by_category: dict[str, int]
    conditions: int
    distinct_diagnosis_codes: int
    observations: int
    observation_components: int
    medication_requests: int
    first_encounter_at: datetime | None
    last_encounter_at: datetime | None
    by_source: list[SourceCount]


class CheckResult(BaseModel):
    check_id: str
    status: str
    observed: float | None
    threshold: float | None
    details: dict[str, object]


class ProcessingQuality(BaseModel):
    processing_id: str
    source_id: str
    source_revision: int
    received: int | None
    accepted: int | None
    deduplicated: int | None
    rejected: int | None
    out_of_scope: int | None
    reject_rate_new: float | None
    fatal_issues: int
    error_issues: int
    warning_issues: int


class IssueCount(BaseModel):
    check_id: str
    severity: str
    issues: int


class Quality(BaseModel):
    release_id: str
    catalog_version: str
    release_checks: list[CheckResult]
    processings: list[ProcessingQuality]
    issues: list[IssueCount]


class PipelineRun(BaseModel):
    attempt_id: str
    orchestrator_run_id: str | None
    source_id: str
    source_revision: int
    batch_id: str
    processing_id: str
    status: str
    processing_status: str
    current_step: str | None
    error_code: str | None
    started_at: datetime
    finished_at: datetime | None
    duration_seconds: float | None
    received: int | None
    accepted: int | None
    rejected: int | None
