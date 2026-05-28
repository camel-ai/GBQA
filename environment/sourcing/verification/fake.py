from __future__ import annotations

from ..models import EnvironmentVerificationResult, ProbeResult, SubEnvironmentCandidate, VerificationArtifacts


class FakeEnvironmentVerifier:
    name = "fake"

    def verify(self, candidate: SubEnvironmentCandidate) -> EnvironmentVerificationResult:
        release_pair = candidate.release_pair
        baseline = release_pair.baseline_release if release_pair else ""
        deployment_method = _deployment_method(candidate)
        command = "curl -fsS http://127.0.0.1/health" if candidate.kind == "api" else "--help"
        return EnvironmentVerificationResult(
            candidate_id=candidate.candidate_id,
            status="passed",
            sandbox_provider=self.name,
            baseline_release=baseline,
            deployment_method=deployment_method,
            interaction_mode=candidate.kind,
            probe=ProbeResult(
                command=command,
                endpoint="http://127.0.0.1/health" if candidate.kind == "api" else None,
                exit_code=0,
                http_status=200 if candidate.kind == "api" else None,
            ),
            artifacts=VerificationArtifacts(logs=[f"fake verification passed for {candidate.candidate_id}"]),
        )


def _deployment_method(candidate: SubEnvironmentCandidate) -> str:
    if candidate.signals.has_dockerfile:
        return "dockerfile"
    if candidate.signals.has_compose:
        return "compose"
    if candidate.signals.has_makefile:
        return "makefile"
    if candidate.deployment_files:
        return "package_script"
    return "inferred"
