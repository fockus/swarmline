"""Types for code verification pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class VerificationStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"


@dataclass(frozen=True, slots=True)
class CheckDetail:
    """Result of a single check in the verification pipeline."""

    name: str
    status: VerificationStatus
    message: str = ""


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Aggregated result of the verification pipeline."""

    status: VerificationStatus
    checks: tuple[CheckDetail, ...] = ()
    summary: str = ""

    @property
    def passed(self) -> bool:
        return self.status == VerificationStatus.PASS
