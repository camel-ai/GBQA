"""Scoring and hard-filter logic for candidate selection."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from .models import CandidateGame, ScoreBreakdown
from .utils import parse_datetime


def classify_complexity(candidate: CandidateGame) -> str:
    """Classify gameplay/system complexity into low, medium, or high."""
    text = " ".join(
        [candidate.title, candidate.summary, " ".join(candidate.tags)]
    ).lower()
    if candidate.capabilities.blocks_archival_replay:
        return "high"
    if any(
        token in text
        for token in (
            "multiplayer",
            "mmo",
            "anti-cheat",
            "always online",
            "live service",
            "server browser",
            "dedicated server",
        )
    ):
        return "high"
    if len(candidate.versions) < 2 or len(candidate.patches) < 1:
        return "low"
    if any(token in text for token in ("jam", "prototype", "tutorial", "tiny", "micro")):
        return "low"
    return "medium"


def hard_filter_failures(candidate: CandidateGame) -> List[str]:
    """Return the hard-filter rejection reasons for a candidate."""
    failures: List[str] = []
    capabilities = candidate.capabilities
    if not capabilities.is_free:
        failures.append("not_free")
    if not (capabilities.has_public_source or capabilities.has_historical_builds):
        failures.append("no_public_source_or_historical_build")
    if not capabilities.has_version_trail:
        failures.append("missing_version_trail")
    if not capabilities.has_patch_notes:
        failures.append("missing_patch_notes")
    if not capabilities.has_official_patch_notes:
        failures.append("missing_official_patch_notes")
    if not capabilities.runnable_locally:
        failures.append("not_runnable_locally")
    if capabilities.blocks_archival_replay:
        failures.append("archival_replay_blocked")
    return failures


def score_candidate(candidate: CandidateGame) -> ScoreBreakdown:
    """Score a candidate using fixed weighted categories."""
    candidate.complexity = classify_complexity(candidate)
    failures = hard_filter_failures(candidate)
    access = 0.0
    if candidate.capabilities.is_free:
        access += 10.0
    if candidate.capabilities.has_public_source or candidate.license:
        access += 10.0
    if candidate.capabilities.runnable_locally:
        access += 5.0

    version_quality = 0.0
    if candidate.capabilities.has_version_trail:
        version_quality += 10.0
    if candidate.capabilities.has_official_patch_notes:
        version_quality += 10.0
    version_quality += min(float(len(candidate.patches)), 5.0)

    historical = 0.0
    if candidate.capabilities.has_historical_builds:
        historical = 20.0
    elif candidate.capabilities.has_public_source:
        historical = 16.0

    complexity = 15.0 if candidate.complexity == "medium" else 4.0 if candidate.complexity == "high" else 6.0

    maintenance = _maintenance_score(candidate)
    documentation = 0.0
    if candidate.summary:
        documentation += 2.0
    if candidate.homepage_url:
        documentation += 1.5
    if candidate.patch_notes_url:
        documentation += 1.5

    total = access + version_quality + historical + complexity + maintenance + documentation
    breakdown = ScoreBreakdown(
        access_licensing=access,
        version_patch_quality=version_quality,
        historical_build_recoverability=historical,
        complexity_fit=complexity,
        maintenance_cadence=maintenance,
        documentation_quality=documentation,
        total=total,
        accepted=False,
        hard_filter_failures=failures,
    )
    return breakdown


def _maintenance_score(candidate: CandidateGame) -> float:
    score = min(float(len(candidate.patches)), 6.0)
    latest_patch = None
    for patch in candidate.patches:
        parsed = parse_datetime(patch.published_at)
        if parsed is None:
            continue
        latest_patch = max(latest_patch, parsed) if latest_patch is not None else parsed
    if latest_patch is None:
        return score
    age_days = (datetime.now(timezone.utc) - latest_patch).days
    if age_days <= 365:
        score += 4.0
    elif age_days <= 730:
        score += 2.0
    return min(score, 10.0)
