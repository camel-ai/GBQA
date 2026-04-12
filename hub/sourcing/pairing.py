"""Release-pair selection logic for software-project sourcing."""

from __future__ import annotations

from .models import ReleasePair, SoftwareProjectCandidate
from .utils import extract_version


def resolve_release_pair(candidate: SoftwareProjectCandidate) -> ReleasePair | None:
    """Select the latest release and its immediate predecessor as the default pair."""
    releases = sorted(candidate.releases, key=lambda item: item.published_at)
    if len(releases) < 2:
        return None
    fix_release = releases[-1]
    baseline_release = releases[-2]
    if not fix_release.has_bug_fix_evidence:
        return None
    baseline_artifact = _baseline_artifact(baseline_release)
    if not baseline_artifact:
        return None
    return ReleasePair(
        baseline_version=_release_version(baseline_release),
        baseline_artifact=baseline_artifact,
        fix_version=_release_version(fix_release),
        release_id=fix_release.release_id,
        patch_published_at=fix_release.published_at,
        recovery_method="release_asset",
    )


def _baseline_artifact(release) -> str:
    for artifact_url in release.artifact_urls:
        if artifact_url:
            return artifact_url
    return ""


def _release_version(release) -> str:
    version = extract_version(release.tag_name or release.title)
    return version or release.release_id
