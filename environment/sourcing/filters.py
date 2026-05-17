from __future__ import annotations

from .models import SubEnvironmentCandidate


def filter_candidate(candidate: SubEnvironmentCandidate) -> list[str]:
    repo = candidate.repository
    failures: list[str] = []
    if repo.archived:
        failures.append("archived")
    if repo.fork:
        failures.append("fork")
    if repo.template:
        failures.append("template_repo")
    if not repo.releases:
        failures.append("insufficient_releases")
    elif len(repo.stable_releases()) < 2:
        if any(not release.is_stable for release in repo.releases):
            failures.append("only_prereleases")
        else:
            failures.append("insufficient_releases")
    if not candidate.signals.linux_candidate:
        failures.append("no_linux_deploy_signal")
    if not (candidate.signals.has_api_surface or candidate.signals.has_cli_surface):
        failures.append("no_api_or_cli_surface")
    if _requires_paid_external_service(candidate):
        failures.append("requires_paid_external_service")
    return failures


def _requires_paid_external_service(candidate: SubEnvironmentCandidate) -> bool:
    haystack = " ".join(
        [
            candidate.repository.description,
            " ".join(candidate.repository.topics),
            " ".join(candidate.repository.file_paths),
        ]
    ).lower()
    paid_markers = (
        "stripe_secret",
        "aws_access_key",
        "google_application_credentials",
        "openai_api_key",
        "requires api key",
    )
    return any(marker in haystack for marker in paid_markers)
