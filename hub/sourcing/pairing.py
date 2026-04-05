"""Version-pair selection logic."""

from __future__ import annotations

from typing import List, Optional

from .models import CandidateGame, PatchRecord, VersionPair, VersionRecord
from .utils import parse_datetime, version_sort_key


def resolve_version_pair(candidate: CandidateGame) -> Optional[VersionPair]:
    """Select a recoverable baseline/fix version pair for a candidate."""
    if candidate.provider == "github":
        return _resolve_adjacent_pair(candidate, prefer_release_assets=True)
    if candidate.provider == "itch":
        return _resolve_adjacent_pair(candidate, prefer_release_assets=False)
    if candidate.provider == "steam":
        if not (
            candidate.capabilities.has_public_source
            or candidate.capabilities.has_historical_builds
        ):
            return None
        return _resolve_adjacent_pair(candidate, prefer_release_assets=False)
    return _resolve_adjacent_pair(candidate, prefer_release_assets=False)


def _resolve_adjacent_pair(
    candidate: CandidateGame,
    *,
    prefer_release_assets: bool,
) -> Optional[VersionPair]:
    versions = _sorted_versions(candidate.versions)
    patches = _sorted_patches(candidate.patches)
    if len(versions) < 2 or not patches:
        return None
    for patch in patches:
        match_index = _find_matching_version_index(versions, patch)
        if match_index is None or match_index == 0:
            continue
        baseline = versions[match_index - 1]
        fix = versions[match_index]
        if not baseline.accessible or not baseline.artifact_url:
            continue
        recovery_method = baseline.artifact_kind or "archive"
        if prefer_release_assets and baseline.artifact_kind == "source_archive":
            recovery_method = "release_asset_fallback"
        return VersionPair(
            baseline_version=baseline.version,
            baseline_artifact=baseline.artifact_url,
            fix_version=fix.version,
            patch_id=patch.patch_id,
            patch_published_at=patch.published_at,
            recovery_method=recovery_method,
        )
    fallback_patch = patches[0]
    baseline = versions[-2]
    fix = versions[-1]
    if not baseline.artifact_url:
        return None
    return VersionPair(
        baseline_version=baseline.version,
        baseline_artifact=baseline.artifact_url,
        fix_version=fix.version,
        patch_id=fallback_patch.patch_id,
        patch_published_at=fallback_patch.published_at,
        recovery_method=baseline.artifact_kind or "archive",
    )


def _sorted_versions(versions: List[VersionRecord]) -> List[VersionRecord]:
    return sorted(
        versions,
        key=lambda item: (
            parse_datetime(item.published_at) or parse_datetime("1970-01-01T00:00:00+00:00"),
            version_sort_key(item.version),
        ),
    )


def _sorted_patches(patches: List[PatchRecord]) -> List[PatchRecord]:
    return sorted(
        patches,
        key=lambda item: (
            parse_datetime(item.published_at) or parse_datetime("1970-01-01T00:00:00+00:00"),
            version_sort_key(item.version),
        ),
        reverse=True,
    )


def _find_matching_version_index(
    versions: List[VersionRecord],
    patch: PatchRecord,
) -> Optional[int]:
    for index, version in enumerate(versions):
        if patch.version and version.version == patch.version:
            return index
    for index, version in enumerate(versions):
        if patch.version and patch.version in version.version:
            return index
    return None
