from __future__ import annotations

from pathlib import Path
from typing import Sequence

from .detection import detect_sub_environments
from .filters import filter_candidate
from .models import (
    EnvironmentVerificationResult,
    PipelineResult,
    RepositoryCandidate,
    SubEnvironmentCandidate,
)
from .providers import PROVIDER_TYPES
from .providers.base import ProviderConfig, RepositoryProvider
from .scoring import score_candidate
from .state import SourcingState, repository_key
from .tagging import tag_candidate
from .utils import now_iso, read_jsonl, stable_json, write_jsonl
from .verification.base import EnvironmentVerifier
from .verification.fake import FakeEnvironmentVerifier


DEFAULT_STATE_DIR = Path("environment/catalog/state")


class SourcingPipeline:
    def __init__(
        self,
        *,
        output_dir: Path,
        provider: RepositoryProvider | None = None,
        verifier: EnvironmentVerifier | None = None,
        state_dir: Path | None = DEFAULT_STATE_DIR,
        resume: bool = True,
    ) -> None:
        self.output_dir = output_dir
        self.provider = provider
        self.verifier = verifier or FakeEnvironmentVerifier()
        self.state_dir = state_dir
        self.resume = resume
        self.state = SourcingState(state_dir) if state_dir is not None else None

    def run(
        self,
        *,
        query: str,
        limit: int,
        top_k: int,
        page: int = 1,
    ) -> PipelineResult:
        provider = self.provider or PROVIDER_TYPES["github"](config=ProviderConfig(github_query=query))
        seen_repository_keys = (
            self.state.repository_keys
            if self.resume and self.state is not None
            else set()
        )
        repositories, skipped_repositories = self.discover_repositories(
            provider=provider,
            query=query,
            limit=limit,
            start_page=page,
            seen_repository_keys=seen_repository_keys,
        )
        sub_environments = self.detect(repositories)
        filtered, rejected = self.filter(sub_environments)
        ranked = self.rank(filtered, top_k=top_k)
        self.write_catalog(
            repositories=repositories,
            sub_environments=sub_environments,
            filtered=filtered,
            ranked=ranked,
            rejected=rejected,
            skipped_repositories=skipped_repositories,
            resume=self.resume,
        )
        if self.state is not None:
            self.state.merge_run(
                repositories=repositories,
                sub_environments=sub_environments,
                ranked=ranked,
                rejected=rejected,
            )
        return PipelineResult(
            repositories=repositories,
            sub_environments=sub_environments,
            filtered=filtered,
            ranked=ranked,
            rejected=rejected,
            skipped_repositories=skipped_repositories,
        )

    @staticmethod
    def discover_repositories(
        *,
        provider: RepositoryProvider,
        query: str,
        limit: int,
        start_page: int = 1,
        seen_repository_keys: set[str] | None = None,
    ) -> tuple[list[RepositoryCandidate], int]:
        repositories: list[RepositoryCandidate] = []
        skipped_repositories = 0
        seen: set[str] = set()
        skipped = seen_repository_keys or set()
        page = start_page
        while len(repositories) < limit:
            remaining = limit - len(repositories)
            try:
                batch = provider.discover(query=query, limit=remaining, page=page)
            except Exception:
                if repositories:
                    break
                raise
            if not batch:
                break
            added_this_page = 0
            skipped_this_page = 0
            for repository in batch:
                key = repository.full_name.lower() or repository.repository_id.lower()
                state_key = repository_key(repository)
                if key in seen:
                    continue
                seen.add(key)
                if state_key in skipped:
                    skipped_repositories += 1
                    skipped_this_page += 1
                    continue
                repositories.append(repository)
                added_this_page += 1
                if len(repositories) >= limit:
                    break
            if len(batch) == 0:
                break
            if added_this_page == 0 and skipped_this_page == 0:
                break
            page += 1
        return repositories, skipped_repositories

    @staticmethod
    def detect(repositories: Sequence[RepositoryCandidate]) -> list[SubEnvironmentCandidate]:
        candidates: list[SubEnvironmentCandidate] = []
        for repository in repositories:
            candidates.extend(detect_sub_environments(repository))
        return candidates

    @staticmethod
    def filter(
        candidates: Sequence[SubEnvironmentCandidate],
    ) -> tuple[list[SubEnvironmentCandidate], list[SubEnvironmentCandidate]]:
        accepted: list[SubEnvironmentCandidate] = []
        rejected: list[SubEnvironmentCandidate] = []
        for candidate in candidates:
            candidate.rejection_reasons = filter_candidate(candidate)
            candidate.tags = tag_candidate(candidate)
            if candidate.rejection_reasons:
                rejected.append(candidate)
            else:
                accepted.append(candidate)
        return accepted, rejected

    @staticmethod
    def rank(
        candidates: Sequence[SubEnvironmentCandidate],
        *,
        top_k: int,
    ) -> list[SubEnvironmentCandidate]:
        ranked: list[SubEnvironmentCandidate] = []
        for candidate in candidates:
            candidate.score = score_candidate(candidate)
            ranked.append(candidate)
        ranked.sort(key=lambda item: item.score.total if item.score else 0.0, reverse=True)
        return ranked[:top_k]

    def verify(self, *, top_k: int | None = None) -> list[EnvironmentVerificationResult]:
        ranked = [
            SubEnvironmentCandidate.from_dict(row)
            for row in read_jsonl(self.output_dir / "ranked.jsonl")
        ]
        selected = ranked[:top_k] if top_k is not None else ranked
        results: list[EnvironmentVerificationResult] = []
        for candidate in selected:
            cached = (
                self.state.get_verification(candidate, provider=self.verifier.name)
                if self.resume and self.state is not None
                else None
            )
            results.append(cached if cached is not None else self.verifier.verify(candidate))
        write_jsonl(self.output_dir / "verified.jsonl", [result.to_dict() for result in results])
        if self.state is not None:
            self.state.merge_verifications(
                candidates=selected,
                results=results,
                provider=self.verifier.name,
            )
        return results

    def write_catalog(
        self,
        *,
        repositories: Sequence[RepositoryCandidate],
        sub_environments: Sequence[SubEnvironmentCandidate],
        filtered: Sequence[SubEnvironmentCandidate],
        ranked: Sequence[SubEnvironmentCandidate],
        rejected: Sequence[SubEnvironmentCandidate],
        skipped_repositories: int = 0,
        resume: bool = False,
    ) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        write_jsonl(
            self.output_dir / "repositories.jsonl",
            [repository.to_dict() for repository in repositories],
        )
        write_jsonl(
            self.output_dir / "sub_environments.jsonl",
            [candidate.to_dict() for candidate in sub_environments],
        )
        write_jsonl(
            self.output_dir / "filtered.jsonl",
            [candidate.to_dict() for candidate in filtered],
        )
        write_jsonl(
            self.output_dir / "ranked.jsonl",
            [candidate.to_dict() for candidate in ranked],
        )
        write_jsonl(
            self.output_dir / "rejected.jsonl",
            [candidate.to_dict() for candidate in rejected],
        )
        provenance_rows = [
            {
                "repository_id": repository.repository_id,
                "sources": [item.to_dict() for item in repository.provenance],
            }
            for repository in repositories
        ]
        write_jsonl(self.output_dir / "provenance.jsonl", provenance_rows)
        summary = {
            "generated_at": now_iso(),
            "repositories": len(repositories),
            "sub_environments": len(sub_environments),
            "filtered": len(filtered),
            "ranked": len(ranked),
            "rejected": len(rejected),
            "resume": resume,
            "skipped_repositories": skipped_repositories,
            "state_dir": str(self.state_dir) if self.state_dir is not None else "",
        }
        (self.output_dir / "summary.json").write_text(stable_json(summary), encoding="utf-8")
