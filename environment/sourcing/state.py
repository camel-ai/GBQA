from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from .models import (
    EnvironmentVerificationResult,
    RepositoryCandidate,
    SubEnvironmentCandidate,
)
from .utils import now_iso, read_jsonl, write_jsonl


PROBE_VERSION = "probe-v1"


def repository_key(repository: RepositoryCandidate) -> str:
    identity = repository.full_name.lower() or repository.repository_id.lower()
    return f"{repository.provider}:{identity}"


def release_pair_key(candidate: SubEnvironmentCandidate) -> str:
    repo_key = repository_key(candidate.repository)
    if candidate.release_pair is None:
        return f"{repo_key}::no-release-pair"
    return (
        f"{repo_key}::{candidate.release_pair.baseline_release}"
        f"::{candidate.release_pair.fixed_release}"
    )


def sub_environment_key(candidate: SubEnvironmentCandidate) -> str:
    sub_path = candidate.sub_path.strip("/") or "root"
    return f"{release_pair_key(candidate)}::{sub_path}"


def verification_key(
    candidate: SubEnvironmentCandidate,
    *,
    provider: str,
    probe_version: str = PROBE_VERSION,
) -> str:
    return f"{sub_environment_key(candidate)}::{provider}::{probe_version}"


class SourcingState:
    """Persistent local ledger for incremental environment sourcing."""

    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir

    @property
    def repository_keys(self) -> set[str]:
        return set(self._read_keyed("repositories.jsonl"))

    def get_verification(
        self,
        candidate: SubEnvironmentCandidate,
        *,
        provider: str,
        probe_version: str = PROBE_VERSION,
    ) -> EnvironmentVerificationResult | None:
        row = self._read_keyed("verifications.jsonl").get(
            verification_key(candidate, provider=provider, probe_version=probe_version)
        )
        if not row:
            return None
        payload = row.get("result", row)
        return EnvironmentVerificationResult.from_dict(payload)

    def merge_run(
        self,
        *,
        repositories: Sequence[RepositoryCandidate],
        sub_environments: Sequence[SubEnvironmentCandidate],
        ranked: Sequence[SubEnvironmentCandidate],
        rejected: Sequence[SubEnvironmentCandidate],
    ) -> None:
        timestamp = now_iso()
        self._merge_keyed(
            "repositories.jsonl",
            [
                {
                    "key": repository_key(repository),
                    "provider": repository.provider,
                    "repository_id": repository.repository_id,
                    "full_name": repository.full_name,
                    "html_url": repository.html_url,
                    "last_seen_at": timestamp,
                }
                for repository in repositories
            ],
        )
        release_rows: dict[str, dict[str, Any]] = {}
        for candidate in sub_environments:
            if candidate.release_pair is None:
                continue
            key = release_pair_key(candidate)
            release_rows[key] = {
                "key": key,
                "repository_key": repository_key(candidate.repository),
                "baseline_release": candidate.release_pair.baseline_release,
                "fixed_release": candidate.release_pair.fixed_release,
                "baseline_archive_url": candidate.release_pair.baseline_archive_url,
                "fixed_release_url": candidate.release_pair.fixed_release_url,
                "selection_policy": candidate.release_pair.selection_policy,
                "last_seen_at": timestamp,
            }
        self._merge_keyed("release_pairs.jsonl", list(release_rows.values()))

        ranked_keys = {sub_environment_key(candidate) for candidate in ranked}
        rejected_keys = {sub_environment_key(candidate) for candidate in rejected}
        self._merge_keyed(
            "sub_environments.jsonl",
            [
                {
                    "key": sub_environment_key(candidate),
                    "repository_key": repository_key(candidate.repository),
                    "release_pair_key": release_pair_key(candidate),
                    "candidate_id": candidate.candidate_id,
                    "sub_path": candidate.sub_path,
                    "kind": candidate.kind,
                    "decision": (
                        "ranked"
                        if sub_environment_key(candidate) in ranked_keys
                        else "rejected"
                        if sub_environment_key(candidate) in rejected_keys
                        else "filtered"
                    ),
                    "rejection_reasons": candidate.rejection_reasons,
                    "last_seen_at": timestamp,
                }
                for candidate in sub_environments
            ],
        )

    def merge_verifications(
        self,
        *,
        candidates: Sequence[SubEnvironmentCandidate],
        results: Sequence[EnvironmentVerificationResult],
        provider: str,
        probe_version: str = PROBE_VERSION,
    ) -> None:
        by_candidate_id = {candidate.candidate_id: candidate for candidate in candidates}
        rows: list[dict[str, Any]] = []
        for result in results:
            candidate = by_candidate_id.get(result.candidate_id)
            if candidate is None:
                continue
            key = verification_key(
                candidate,
                provider=provider,
                probe_version=probe_version,
            )
            rows.append(
                {
                    "key": key,
                    "sub_environment_key": sub_environment_key(candidate),
                    "candidate_id": result.candidate_id,
                    "provider": provider,
                    "probe_version": probe_version,
                    "status": result.status,
                    "result": result.to_dict(),
                    "last_seen_at": now_iso(),
                }
            )
        self._merge_keyed("verifications.jsonl", rows)

    def _read_keyed(self, filename: str) -> dict[str, dict[str, Any]]:
        keyed: dict[str, dict[str, Any]] = {}
        for row in read_jsonl(self.state_dir / filename):
            key = str(row.get("key", ""))
            if key:
                keyed[key] = row
        return keyed

    def _merge_keyed(self, filename: str, rows: Sequence[dict[str, Any]]) -> None:
        if not rows:
            return
        current = self._read_keyed(filename)
        for row in rows:
            key = str(row.get("key", ""))
            if key:
                current[key] = dict(row)
        write_jsonl(
            self.state_dir / filename,
            [current[key] for key in sorted(current)],
        )
