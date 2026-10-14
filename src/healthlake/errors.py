"""Error taxonomy mapped to stable CLI exit codes and Airflow retry policy."""

from __future__ import annotations

from enum import IntEnum
from typing import Any


class ExitCode(IntEnum):
    OK = 0
    UNEXPECTED = 1
    CONTRACT = 2
    QUALITY = 3
    TRANSIENT = 4
    CONFLICT = 5


class HealthLakeError(Exception):
    exit_code: ExitCode = ExitCode.UNEXPECTED
    code: str = "error"

    def __init__(self, message: str, code: str | None = None, **details: Any) -> None:
        super().__init__(message)
        if code:
            self.code = code
        self.details = details


class ContractError(HealthLakeError):
    exit_code = ExitCode.CONTRACT
    code = "contract_invalid"


class QualityBlockedError(HealthLakeError):
    exit_code = ExitCode.QUALITY
    code = "quality_blocked"


class TransientError(HealthLakeError):
    exit_code = ExitCode.TRANSIENT
    code = "transient"


class ConflictError(HealthLakeError):
    exit_code = ExitCode.CONFLICT
    code = "conflict"
