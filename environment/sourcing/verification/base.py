from __future__ import annotations

from typing import Protocol

from ..models import EnvironmentVerificationResult, SubEnvironmentCandidate


class EnvironmentVerifier(Protocol):
    name: str

    def verify(self, candidate: SubEnvironmentCandidate) -> EnvironmentVerificationResult:
        ...
