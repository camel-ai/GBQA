"""Scoring and hard-filter logic for software-project selection."""

from __future__ import annotations

from .models import ScoreBreakdown, SoftwareProjectCandidate


def hard_filter_failures(candidate: SoftwareProjectCandidate) -> list[str]:
    """Return hard-filter failures for one software project."""
    failures: list[str] = []
    capabilities = candidate.capabilities
    if not capabilities.has_public_source:
        failures.append("missing_public_source")
    if not capabilities.has_release_history:
        failures.append("missing_release_history")
    if not capabilities.has_fix_releases:
        failures.append("missing_bug_fix_release_evidence")
    if not capabilities.has_recoverable_baseline:
        failures.append("missing_recoverable_baseline")
    if candidate.selected_release_pair is not None:
        if not capabilities.has_tracked_issue_closure:
            failures.append("tracked_issues_not_closed")
    if capabilities.interaction_mode == "unknown":
        failures.append("unsupported_interaction_surface")
    if candidate.engagement.workability_score < 20.0:
        failures.append("insufficient_workability")
    return failures


def score_candidate(candidate: SoftwareProjectCandidate) -> ScoreBreakdown:
    """Score one software project with fixed weighted categories."""
    failures = hard_filter_failures(candidate)
    source_access = 25.0 if candidate.capabilities.has_public_source else 0.0

    release_evidence = 0.0
    if candidate.capabilities.has_release_history:
        release_evidence += 10.0
    release_evidence += min(float(candidate.engagement.release_count), 10.0)
    if candidate.capabilities.has_fix_releases:
        release_evidence += 10.0

    engineering_activity = min(candidate.engagement.workability_score / 100.0, 1.0) * 20.0

    interaction_mode = candidate.capabilities.interaction_mode
    if interaction_mode == "mixed":
        architecture_fit = 15.0
    elif interaction_mode in {"computer_use", "api_cli"}:
        architecture_fit = 12.0
    else:
        architecture_fit = 0.0

    metadata_quality = 0.0
    if candidate.about:
        metadata_quality += 3.0
    if candidate.topics:
        metadata_quality += 2.0
    if candidate.languages:
        metadata_quality += 2.0
    if candidate.release_notes_url:
        metadata_quality += 3.0

    total = (
        source_access
        + release_evidence
        + engineering_activity
        + architecture_fit
        + metadata_quality
    )
    return ScoreBreakdown(
        source_access=source_access,
        release_evidence=release_evidence,
        engineering_activity=engineering_activity,
        architecture_fit=architecture_fit,
        metadata_quality=metadata_quality,
        total=round(total, 2),
        accepted=False,
        hard_filter_failures=failures,
    )
