"""Pipeline orchestration for Hub sourcing."""

from __future__ import annotations

from pathlib import Path
import json
from typing import Iterable, List, Optional, Sequence

from .ground_truth import GroundTruthGenerator, PatchNoteLlmClient
from .models import CandidateGame, CandidateManifest
from .pairing import resolve_version_pair
from .providers import PROVIDER_TYPES
from .providers.base import ProviderConfig, ProviderError
from .scoring import score_candidate
from .utils import now_iso, pretty_json


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
        self.output_dir = output_dir or Path(__file__).resolve().parents[1] / "catalog"
        self.fetcher = fetcher
        self.provider_config = provider_config or ProviderConfig()
        self._ground_truth = GroundTruthGenerator(llm_client=llm_client)

    def discover(
        self,
        *,
        providers: Sequence[str],
        limit: int,
        allow_partial: bool = False,
    ) -> List[CandidateGame]:
        discovered: List[CandidateGame] = []
        errors: List[str] = []
        for provider_name in providers:
            provider_cls = PROVIDER_TYPES[provider_name]
            provider = provider_cls(fetcher=self.fetcher, config=self.provider_config)
            try:
                discovered.extend(provider.discover(limit=limit))
            except ProviderError as exc:
                if not allow_partial:
                    raise
                errors.append(f"{provider_name}: {exc}")
        if errors and not discovered:
            raise ProviderError("; ".join(errors))
        return discovered

    def score(self, candidates: Iterable[CandidateGame]) -> List[CandidateGame]:
        scored: List[CandidateGame] = []
        for candidate in candidates:
            candidate.selected_version_pair = resolve_version_pair(candidate)
            breakdown = score_candidate(candidate)
            if candidate.complexity != "medium":
                breakdown.hard_filter_failures.append("complexity_not_medium")
            if candidate.selected_version_pair is None:
                breakdown.hard_filter_failures.append("no_recoverable_version_pair")
            breakdown.accepted = not breakdown.hard_filter_failures
            candidate.score_breakdown = breakdown
            candidate.score = breakdown.total
            candidate.rejection_reasons = breakdown.hard_filter_failures[:]
            scored.append(candidate)
        return scored

    def select(
        self,
        candidates: Iterable[CandidateGame],
        *,
        minimum_score: float = 60.0,
        max_candidates: Optional[int] = None,
    ) -> List[CandidateGame]:
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
        all_candidates: Sequence[CandidateGame],
        selected: Sequence[CandidateGame],
    ) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._write_jsonl(self.output_dir / "candidates.jsonl", all_candidates)
        selected_root = self.output_dir / "selected"
        for candidate in selected:
            if candidate.selected_version_pair is None or candidate.score_breakdown is None:
                continue
            candidate_root = selected_root / candidate.slug
            bugs_dir = candidate_root / "bugs"
            bugs_dir.mkdir(parents=True, exist_ok=True)
            bundle = self._ground_truth.generate(candidate, candidate.selected_version_pair)
            bug_path = bugs_dir / f"{candidate.selected_version_pair.patch_id}.json"
            bug_path.write_text(pretty_json(bundle.to_dict()), encoding="utf-8")
            manifest = CandidateManifest(
                game_id=candidate.game_id,
                title=candidate.title,
                provider=candidate.provider,
                runtime_kind=candidate.runtime_kind,
                homepage_url=candidate.homepage_url,
                source_repo_url=candidate.source_repo_url,
                license=candidate.license,
                free_access=candidate.capabilities.is_free,
                historical_build_access=(
                    candidate.capabilities.has_historical_builds
                    or candidate.capabilities.has_public_source
                ),
                selected_version_pair=candidate.selected_version_pair,
                score=candidate.score,
                score_breakdown=candidate.score_breakdown,
                patch_notes_url=candidate.patch_notes_url,
                artifact_urls=candidate.artifact_urls,
                ground_truth_path=str(
                    Path("selected") / candidate.slug / "bugs" / bug_path.name
                ).replace("\\", "/"),
            )
            (candidate_root / "manifest.json").write_text(
                pretty_json(manifest.to_dict()), encoding="utf-8"
            )
            provenance_payload = {
                "generated_at": now_iso(),
                "candidate_id": candidate.game_id,
                "sources": [item.to_dict() for item in candidate.provenance],
            }
            (candidate_root / "provenance.json").write_text(
                pretty_json(provenance_payload), encoding="utf-8"
            )

    def run(
        self,
        *,
        providers: Sequence[str],
        limit: int,
        allow_partial: bool = False,
        minimum_score: float = 60.0,
        max_candidates: Optional[int] = None,
    ) -> List[CandidateGame]:
        discovered = self.discover(
            providers=providers, limit=limit, allow_partial=allow_partial
        )
        scored = self.score(discovered)
        selected = self.select(
            scored, minimum_score=minimum_score, max_candidates=max_candidates
        )
        self.publish(all_candidates=scored, selected=selected)
        return selected

    @staticmethod
    def _write_jsonl(path: Path, candidates: Sequence[CandidateGame]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(candidate.to_dict(), ensure_ascii=True) for candidate in candidates]
        payload = "\n".join(lines)
        if payload:
            payload += "\n"
        path.write_text(payload, encoding="utf-8")

    @staticmethod
    def load_candidates(path: Path) -> List[CandidateGame]:
        candidates: List[CandidateGame] = []
        if not path.exists():
            return candidates
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            candidates.append(CandidateGame.from_dict(json.loads(stripped)))
        return candidates
