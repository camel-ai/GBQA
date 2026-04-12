"""Pipeline orchestration for Hub software-project sourcing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from .ground_truth import GroundTruthGenerator, PatchNoteLlmClient
from .issue_verification import verify_issue_closure_chain
from .models import DedupeRecord, SoftwareProjectCandidate, SoftwareProjectManifest
from .pairing import resolve_release_pair
from .providers import PROVIDER_TYPES
from .providers.base import ProviderConfig, ProviderError
from .providers.github import GithubSoftwareProjectProvider
from .scoring import score_candidate
from .state import CatalogStateStore
from .utils import build_dedupe_key, now_iso, pretty_json


class SourcingPipeline:
    """End-to-end catalog generation and publication pipeline."""

    def __init__(
        self,
        *,
        output_dir: Optional[Path] = None,
        fetcher=None,
        provider_config: Optional[ProviderConfig] = None,
        llm_client: Optional[PatchNoteLlmClient] = None,
    ) -> None:
        self.output_dir = output_dir or Path(__file__).resolve().parents[1] / "environment"
        self.fetcher = fetcher
        self.provider_config = provider_config or ProviderConfig()
        self._ground_truth = GroundTruthGenerator(llm_client=llm_client)
        self._state = CatalogStateStore(self.output_dir)

    def discover(
        self,
        *,
        providers: Sequence[str],
        limit: int,
        allow_partial: bool = False,
        provider_pages: Optional[Dict[str, int]] = None,
    ) -> List[SoftwareProjectCandidate]:
        """Discover candidate software projects."""
        discovered: List[SoftwareProjectCandidate] = []
        errors: List[str] = []
        for provider_name in providers:
            provider_cls = PROVIDER_TYPES[provider_name]
            provider = provider_cls(fetcher=self.fetcher, config=self.provider_config)
            try:
                discovered.extend(
                    provider.discover(
                        limit=limit,
                        page=(provider_pages or {}).get(provider_name, 1),
                    )
                )
            except ProviderError as exc:
                if not allow_partial:
                    raise
                errors.append(f"{provider_name}: {exc}")
        if errors and not discovered:
            raise ProviderError("; ".join(errors))
        return discovered

    def discover_round(
        self,
        *,
        providers: Sequence[str],
        limit: int,
        allow_partial: bool = False,
        provider_pages: Dict[str, int],
    ) -> tuple[List[SoftwareProjectCandidate], Dict[str, int]]:
        """Discover one paginated batch per provider and report batch sizes."""
        discovered: List[SoftwareProjectCandidate] = []
        counts: Dict[str, int] = {}
        errors: List[str] = []
        for provider_name in providers:
            provider_cls = PROVIDER_TYPES[provider_name]
            provider = provider_cls(fetcher=self.fetcher, config=self.provider_config)
            try:
                batch = provider.discover(
                    limit=limit,
                    page=provider_pages.get(provider_name, 1),
                )
            except ProviderError as exc:
                if not allow_partial:
                    raise
                errors.append(f"{provider_name}: {exc}")
                counts[provider_name] = 0
                continue
            discovered.extend(batch)
            counts[provider_name] = len(batch)
        if errors and not discovered:
            raise ProviderError("; ".join(errors))
        return discovered, counts

    def score(
        self,
        candidates: Iterable[SoftwareProjectCandidate],
    ) -> List[SoftwareProjectCandidate]:
        """Score candidates and apply dedupe-aware hard filters."""
        scored: List[SoftwareProjectCandidate] = []
        for candidate in candidates:
            candidate.capabilities.has_fix_releases = bool(
                candidate.releases and candidate.releases[-1].has_bug_fix_evidence
            )
            candidate.selected_release_pair = resolve_release_pair(candidate)
            if candidate.selected_release_pair is not None:
                candidate.capabilities.has_recoverable_baseline = True
                candidate.release_notes_url = next(
                    (
                        release.notes_url
                        for release in candidate.releases
                        if release.release_id == candidate.selected_release_pair.release_id
                    ),
                    candidate.release_notes_url,
                )
                candidate.dedupe_key = build_dedupe_key(
                    candidate.repo_full_name,
                    candidate.selected_release_pair.release_id,
                )
            candidate.capabilities.has_tracked_issue_closure = False
            if candidate.selected_release_pair is not None:
                if self.fetcher is None:
                    candidate.capabilities.has_tracked_issue_closure = True
                    candidate.extra["issue_verification"] = {
                        "skipped": True,
                        "reason": "no_fetcher",
                    }
                else:
                    releases_sorted = sorted(
                        candidate.releases,
                        key=lambda item: item.published_at,
                    )
                    baseline_release = releases_sorted[-2]
                    fix_release = next(
                        item
                        for item in releases_sorted
                        if item.release_id
                        == candidate.selected_release_pair.release_id
                    )
                    provider = GithubSoftwareProjectProvider(
                        fetcher=self.fetcher,
                        config=self.provider_config,
                    )
                    verification = verify_issue_closure_chain(
                        repo_full_name=candidate.repo_full_name,
                        baseline_release=baseline_release,
                        fix_release=fix_release,
                        fetch_json=lambda url: provider.fetch_json(
                            url,
                            candidate.provenance,
                        ),
                    )
                    candidate.extra["issue_verification"] = verification.to_dict()
                    candidate.capabilities.has_tracked_issue_closure = verification.ok
            breakdown = score_candidate(candidate)
            if candidate.dedupe_key and self._state.contains(candidate.dedupe_key):
                breakdown.hard_filter_failures.append("already_saved_pair")
            breakdown.accepted = not breakdown.hard_filter_failures
            candidate.score_breakdown = breakdown
            candidate.score = breakdown.total
            candidate.rejection_reasons = breakdown.hard_filter_failures[:]
            scored.append(candidate)
        return scored

    def select(
        self,
        candidates: Iterable[SoftwareProjectCandidate],
        *,
        minimum_score: float = 60.0,
        max_candidates: Optional[int] = None,
    ) -> List[SoftwareProjectCandidate]:
        """Select candidates that pass hard filters and score threshold."""
        selected = [
            candidate
            for candidate in candidates
            if candidate.score_breakdown
            and candidate.score_breakdown.accepted
            and candidate.score >= minimum_score
        ]
        selected.sort(key=lambda item: item.score, reverse=True)
        if max_candidates is not None:
            selected = selected[:max_candidates]
        return selected

    def publish(
        self,
        *,
        all_candidates: Sequence[SoftwareProjectCandidate],
        selected: Sequence[SoftwareProjectCandidate],
    ) -> None:
        """Publish the catalog, manifests, bug bundles, and dedupe ledger."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._write_jsonl(self.output_dir / "candidates.jsonl", all_candidates)
        selected_root = self.output_dir / "selected"
        for candidate in selected:
            if candidate.selected_release_pair is None or candidate.score_breakdown is None:
                continue
            candidate_root = selected_root / candidate.environment_id
            bugs_dir = candidate_root / "bugs"
            bugs_dir.mkdir(parents=True, exist_ok=True)
            bundle = self._ground_truth.generate(candidate, candidate.selected_release_pair)
            bug_path = bugs_dir / f"{candidate.selected_release_pair.release_id}.json"
            bug_path.write_text(pretty_json(bundle.to_dict()), encoding="utf-8")

            manifest = SoftwareProjectManifest(
                environment_id=candidate.environment_id,
                project_name=candidate.project_name,
                provider=candidate.provider,
                repo_full_name=candidate.repo_full_name,
                github_url=candidate.github_url,
                clone_url=candidate.clone_url,
                owner=candidate.owner,
                default_branch=candidate.default_branch,
                about=candidate.about,
                topics=candidate.topics,
                license=candidate.license,
                languages=candidate.languages,
                capabilities=candidate.capabilities,
                engagement=candidate.engagement,
                selected_release_pair=candidate.selected_release_pair,
                score=candidate.score,
                score_breakdown=candidate.score_breakdown,
                release_notes_url=candidate.release_notes_url,
                artifact_urls=candidate.artifact_urls,
                ground_truth_path=str(
                    Path("selected") / candidate.environment_id / "bugs" / bug_path.name
                ).replace("\\", "/"),
                clone_hint=(
                    f"Clone {candidate.clone_url} and check out the baseline version "
                    f"{candidate.selected_release_pair.baseline_version}."
                ),
                sandbox_hint=(
                    "Move the checked-out code into an isolated sandbox and choose "
                    f"{candidate.capabilities.interaction_mode} interaction mode."
                ),
                dedupe_key=candidate.dedupe_key,
                issue_verification=(
                    candidate.extra.get("issue_verification")
                    if isinstance(candidate.extra.get("issue_verification"), dict)
                    else None
                ),
            )
            manifest_path = candidate_root / "manifest.json"
            manifest_path.write_text(pretty_json(manifest.to_dict()), encoding="utf-8")
            provenance_payload = {
                "generated_at": now_iso(),
                "environment_id": candidate.environment_id,
                "sources": [item.to_dict() for item in candidate.provenance],
            }
            (candidate_root / "provenance.json").write_text(
                pretty_json(provenance_payload),
                encoding="utf-8",
            )
            self._state.append(
                DedupeRecord(
                    dedupe_key=candidate.dedupe_key,
                    repo_full_name=candidate.repo_full_name,
                    project_name=candidate.project_name,
                    release_id=candidate.selected_release_pair.release_id,
                    baseline_version=candidate.selected_release_pair.baseline_version,
                    fix_version=candidate.selected_release_pair.fix_version,
                    manifest_path=str(manifest_path.relative_to(self.output_dir)).replace(
                        "\\",
                        "/",
                    ),
                    saved_at=now_iso(),
                )
            )

    def run(
        self,
        *,
        providers: Sequence[str],
        limit: int,
        allow_partial: bool = False,
        minimum_score: float = 60.0,
        max_candidates: Optional[int] = None,
        minimum_selected: Optional[int] = None,
    ) -> List[SoftwareProjectCandidate]:
        """Run the full discovery, scoring, selection, and publication pipeline."""
        if minimum_selected is not None and minimum_selected < 1:
            raise ValueError("minimum_selected must be at least 1 when provided")
        if (
            minimum_selected is not None
            and max_candidates is not None
            and minimum_selected > max_candidates
        ):
            raise ValueError(
                "minimum_selected cannot be greater than max_candidates"
            )

        target_selected = minimum_selected or 0
        provider_pages = {provider_name: 1 for provider_name in providers}
        active_providers = list(providers)
        seen_repositories: set[str] = set()
        discovered: List[SoftwareProjectCandidate] = []
        scored: List[SoftwareProjectCandidate] = []
        selected: List[SoftwareProjectCandidate] = []

        while active_providers:
            batch, counts = self.discover_round(
                providers=active_providers,
                limit=limit,
                allow_partial=allow_partial,
                provider_pages=provider_pages,
            )
            batch_new_items = self._collect_new_candidates(
                batch,
                seen_repositories=seen_repositories,
            )
            discovered.extend(batch_new_items)
            if discovered:
                scored = self.score(discovered)
                selected = self.select(
                    scored,
                    minimum_score=minimum_score,
                    max_candidates=max_candidates,
                )
            if target_selected and len(selected) >= target_selected:
                break

            next_active_providers: List[str] = []
            for provider_name in active_providers:
                if counts.get(provider_name, 0) >= limit:
                    provider_pages[provider_name] = provider_pages.get(provider_name, 1) + 1
                    next_active_providers.append(provider_name)
            if not next_active_providers:
                break
            active_providers = next_active_providers

        if not scored:
            scored = self.score(discovered)
            selected = self.select(
                scored,
                minimum_score=minimum_score,
                max_candidates=max_candidates,
            )
        self.publish(all_candidates=scored, selected=selected)
        return selected

    @staticmethod
    def _collect_new_candidates(
        candidates: Sequence[SoftwareProjectCandidate],
        *,
        seen_repositories: set[str],
    ) -> List[SoftwareProjectCandidate]:
        """Keep only repositories that have not been seen earlier in this run."""
        new_candidates: List[SoftwareProjectCandidate] = []
        for candidate in candidates:
            if candidate.repo_full_name in seen_repositories:
                continue
            seen_repositories.add(candidate.repo_full_name)
            new_candidates.append(candidate)
        return new_candidates

    @staticmethod
    def _write_jsonl(path: Path, candidates: Sequence[SoftwareProjectCandidate]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = "\n".join(
            json.dumps(candidate.to_dict(), ensure_ascii=True) for candidate in candidates
        )
        if payload:
            payload += "\n"
        path.write_text(payload, encoding="utf-8")

    @staticmethod
    def load_candidates(path: Path) -> List[SoftwareProjectCandidate]:
        """Load serialized candidates from a JSONL catalog."""
        candidates: List[SoftwareProjectCandidate] = []
        if not path.exists():
            return candidates
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            candidates.append(SoftwareProjectCandidate.from_dict(json.loads(stripped)))
        return candidates
