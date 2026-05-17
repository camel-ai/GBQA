from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from environment.sourcing.models import ReleaseRecord, RepositoryCandidate
from environment.sourcing.pipeline import SourcingPipeline
from environment.sourcing.providers.base import RepositoryProvider
from environment.sourcing.verification.fake import FakeEnvironmentVerifier


class FixtureProvider(RepositoryProvider):
    name = "fixture"

    def discover(self, *, query: str, limit: int, page: int = 1):
        del query, page
        return _fixture_repositories()[:limit]


class FixtureProviderWithRepositories(RepositoryProvider):
    name = "fixture"

    def __init__(self, repositories: list[RepositoryCandidate]) -> None:
        self._repositories = repositories

    def discover(self, *, query: str, limit: int, page: int = 1):
        del query, page
        return self._repositories[:limit]


class PaginatedFixtureProvider(RepositoryProvider):
    name = "fixture"

    def __init__(self, repositories: list[RepositoryCandidate], page_size: int) -> None:
        self._repositories = repositories
        self._page_size = page_size

    def discover(self, *, query: str, limit: int, page: int = 1):
        del query
        start = (page - 1) * self._page_size
        return self._repositories[start : start + min(limit, self._page_size)]


class SecondPageFailureProvider(PaginatedFixtureProvider):
    def discover(self, *, query: str, limit: int, page: int = 1):
        if page == 2:
            raise RuntimeError("page 2 failed")
        return super().discover(query=query, limit=limit, page=page)


class RaisingVerifier:
    name = "fake"

    def verify(self, candidate):
        raise AssertionError(f"verification should have resumed for {candidate.candidate_id}")


class SourcingPipelineTests(unittest.TestCase):
    def test_pipeline_filters_ranks_and_writes_catalog_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pipeline = SourcingPipeline(
                output_dir=Path(temp_dir),
                provider=FixtureProvider(),
                state_dir=None,
            )

            result = pipeline.run(query="ignored", limit=3, top_k=10)

            self.assertEqual([item.candidate_id for item in result.ranked], ["acme-flow-ui-root"])
            self.assertIn("insufficient_releases", result.rejected[0].rejection_reasons)
            self.assertTrue((Path(temp_dir) / "repositories.jsonl").exists())
            self.assertTrue((Path(temp_dir) / "sub_environments.jsonl").exists())
            self.assertTrue((Path(temp_dir) / "filtered.jsonl").exists())
            self.assertTrue((Path(temp_dir) / "ranked.jsonl").exists())
            self.assertTrue((Path(temp_dir) / "rejected.jsonl").exists())
            summary = json.loads((Path(temp_dir) / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["repositories"], 2)
            self.assertEqual(summary["ranked"], 1)

    def test_pipeline_verifies_top_ranked_candidates_with_fake_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pipeline = SourcingPipeline(
                output_dir=Path(temp_dir),
                provider=FixtureProvider(),
                verifier=FakeEnvironmentVerifier(),
                state_dir=None,
            )
            pipeline.run(query="ignored", limit=3, top_k=10)

            results = pipeline.verify(top_k=5)

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].status, "passed")
            self.assertEqual(results[0].sandbox_provider, "fake")
            verified_rows = [
                json.loads(line)
                for line in (Path(temp_dir) / "verified.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(verified_rows[0]["candidate_id"], "acme-flow-ui-root")

    def test_missing_license_does_not_block_human_review_queue(self) -> None:
        repository = _fixture_repositories()[0]
        repository.license = ""
        with tempfile.TemporaryDirectory() as temp_dir:
            pipeline = SourcingPipeline(
                output_dir=Path(temp_dir),
                provider=FixtureProviderWithRepositories([repository]),
                state_dir=None,
            )

            result = pipeline.run(query="ignored", limit=1, top_k=1)

            self.assertEqual([item.candidate_id for item in result.ranked], ["acme-flow-ui-root"])

    def test_pipeline_collects_multiple_provider_pages_until_limit(self) -> None:
        repositories = _fixture_repositories()
        repositories.append(
            RepositoryCandidate(
                repository_id="acme-api-worker",
                provider="github",
                owner="acme",
                name="api-worker",
                full_name="acme/api-worker",
                html_url="https://github.com/acme/api-worker",
                clone_url="https://github.com/acme/api-worker.git",
                default_branch="main",
                description="API worker with a package script.",
                topics=["api"],
                license="Apache-2.0",
                stars=50,
                forks=4,
                open_issues=2,
                languages={"Python": 5000},
                releases=[
                    ReleaseRecord(
                        tag_name="v0.1.0",
                        title="v0.1.0",
                        published_at="2025-01-01T00:00:00Z",
                        html_url="https://github.com/acme/api-worker/releases/tag/v0.1.0",
                        archive_url="https://github.com/acme/api-worker/archive/refs/tags/v0.1.0.tar.gz",
                        body="Initial release.",
                    ),
                    ReleaseRecord(
                        tag_name="v0.2.0",
                        title="v0.2.0",
                        published_at="2025-02-01T00:00:00Z",
                        html_url="https://github.com/acme/api-worker/releases/tag/v0.2.0",
                        archive_url="https://github.com/acme/api-worker/archive/refs/tags/v0.2.0.tar.gz",
                        body="Fixed API retry handling.",
                    ),
                ],
                file_paths=["requirements.txt", "api/routes.py"],
            )
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            pipeline = SourcingPipeline(
                output_dir=Path(temp_dir),
                provider=PaginatedFixtureProvider(repositories, page_size=1),
                state_dir=None,
            )

            result = pipeline.run(query="ignored", limit=3, top_k=10)

            self.assertEqual(len(result.repositories), 3)
            self.assertEqual(
                [item.candidate_id for item in result.ranked],
                ["acme-flow-ui-root", "acme-api-worker-root"],
            )

    def test_pipeline_keeps_partial_results_when_later_page_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pipeline = SourcingPipeline(
                output_dir=Path(temp_dir),
                provider=SecondPageFailureProvider(_fixture_repositories(), page_size=1),
                state_dir=None,
            )

            result = pipeline.run(query="ignored", limit=3, top_k=10)

            self.assertEqual(len(result.repositories), 1)
            self.assertEqual([item.candidate_id for item in result.ranked], ["acme-flow-ui-root"])

    def test_default_resume_skips_repositories_recorded_in_state(self) -> None:
        repositories = _fixture_repositories()
        repositories.append(
            RepositoryCandidate(
                repository_id="acme-api-worker",
                provider="github",
                owner="acme",
                name="api-worker",
                full_name="acme/api-worker",
                html_url="https://github.com/acme/api-worker",
                clone_url="https://github.com/acme/api-worker.git",
                default_branch="main",
                description="API worker with a package script.",
                topics=["api"],
                license="Apache-2.0",
                stars=50,
                forks=4,
                open_issues=2,
                languages={"Python": 5000},
                releases=[
                    ReleaseRecord(
                        tag_name="v0.1.0",
                        title="v0.1.0",
                        published_at="2025-01-01T00:00:00Z",
                        html_url="https://github.com/acme/api-worker/releases/tag/v0.1.0",
                        archive_url="https://github.com/acme/api-worker/archive/refs/tags/v0.1.0.tar.gz",
                        body="Initial release.",
                    ),
                    ReleaseRecord(
                        tag_name="v0.2.0",
                        title="v0.2.0",
                        published_at="2025-02-01T00:00:00Z",
                        html_url="https://github.com/acme/api-worker/releases/tag/v0.2.0",
                        archive_url="https://github.com/acme/api-worker/archive/refs/tags/v0.2.0.tar.gz",
                        body="Fixed API retry handling.",
                    ),
                ],
                file_paths=["requirements.txt", "api/routes.py"],
            )
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state_dir = root / "state"
            first = SourcingPipeline(
                output_dir=root / "run-001",
                state_dir=state_dir,
                provider=PaginatedFixtureProvider(repositories, page_size=1),
            )
            first_result = first.run(query="ignored", limit=1, top_k=10)
            self.assertEqual([item.full_name for item in first_result.repositories], ["acme/flow-ui"])

            second = SourcingPipeline(
                output_dir=root / "run-002",
                state_dir=state_dir,
                provider=PaginatedFixtureProvider(repositories, page_size=1),
            )
            second_result = second.run(query="ignored", limit=3, top_k=10)

            self.assertEqual(second_result.skipped_repositories, 1)
            self.assertEqual(
                [item.full_name for item in second_result.repositories],
                ["acme/widget-lib", "acme/api-worker"],
            )
            self.assertEqual([item.candidate_id for item in second_result.ranked], ["acme-api-worker-root"])
            self.assertTrue((state_dir / "repositories.jsonl").exists())
            self.assertTrue((state_dir / "sub_environments.jsonl").exists())

    def test_no_resume_reprocesses_repositories_recorded_in_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state_dir = root / "state"
            first = SourcingPipeline(
                output_dir=root / "run-001",
                state_dir=state_dir,
                provider=PaginatedFixtureProvider(_fixture_repositories(), page_size=1),
            )
            first.run(query="ignored", limit=1, top_k=10)

            second = SourcingPipeline(
                output_dir=root / "run-002",
                state_dir=state_dir,
                resume=False,
                provider=PaginatedFixtureProvider(_fixture_repositories(), page_size=1),
            )
            second_result = second.run(query="ignored", limit=1, top_k=10)

            self.assertEqual(second_result.skipped_repositories, 0)
            self.assertEqual([item.full_name for item in second_result.repositories], ["acme/flow-ui"])

    def test_verify_resumes_existing_verification_results_from_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state_dir = root / "state"
            output_dir = root / "run-001"
            pipeline = SourcingPipeline(
                output_dir=output_dir,
                state_dir=state_dir,
                provider=FixtureProvider(),
                verifier=FakeEnvironmentVerifier(),
            )
            pipeline.run(query="ignored", limit=2, top_k=10)
            first_results = pipeline.verify(top_k=1)
            self.assertEqual(first_results[0].status, "passed")

            resumed = SourcingPipeline(
                output_dir=output_dir,
                state_dir=state_dir,
                verifier=RaisingVerifier(),
            )
            resumed_results = resumed.verify(top_k=1)

            self.assertEqual(resumed_results[0].status, "passed")


def _fixture_repositories() -> list[RepositoryCandidate]:
    return [
        RepositoryCandidate(
            repository_id="acme-flow-ui",
            provider="github",
            owner="acme",
            name="flow-ui",
            full_name="acme/flow-ui",
            html_url="https://github.com/acme/flow-ui",
            clone_url="https://github.com/acme/flow-ui.git",
            default_branch="main",
            description="Workflow review app with an API and browser UI.",
            topics=["workflow", "api", "react"],
            license="Apache-2.0",
            stars=120,
            forks=12,
            open_issues=8,
            languages={"TypeScript": 8000, "Python": 2000},
            releases=[
                ReleaseRecord(
                    tag_name="v1.0.0",
                    title="v1.0.0",
                    published_at="2025-01-01T00:00:00Z",
                    html_url="https://github.com/acme/flow-ui/releases/tag/v1.0.0",
                    archive_url="https://github.com/acme/flow-ui/archive/refs/tags/v1.0.0.tar.gz",
                    body="Initial release.",
                ),
                ReleaseRecord(
                    tag_name="v1.1.0",
                    title="v1.1.0",
                    published_at="2025-02-01T00:00:00Z",
                    html_url="https://github.com/acme/flow-ui/releases/tag/v1.1.0",
                    archive_url="https://github.com/acme/flow-ui/archive/refs/tags/v1.1.0.tar.gz",
                    body="Bug fixes for API timeout and dashboard refresh.",
                ),
            ],
            file_paths=[
                "Dockerfile",
                "package.json",
                "src/routes/api.ts",
                "src/App.tsx",
                "README.md",
            ],
        ),
        RepositoryCandidate(
            repository_id="acme-widget-lib",
            provider="github",
            owner="acme",
            name="widget-lib",
            full_name="acme/widget-lib",
            html_url="https://github.com/acme/widget-lib",
            clone_url="https://github.com/acme/widget-lib.git",
            default_branch="main",
            description="Small widget library.",
            topics=["library"],
            license="MIT",
            stars=20,
            forks=2,
            open_issues=1,
            languages={"TypeScript": 4000},
            releases=[
                ReleaseRecord(
                    tag_name="v0.1.0",
                    title="v0.1.0",
                    published_at="2025-01-01T00:00:00Z",
                    html_url="https://github.com/acme/widget-lib/releases/tag/v0.1.0",
                    archive_url="https://github.com/acme/widget-lib/archive/refs/tags/v0.1.0.tar.gz",
                    body="Initial release.",
                )
            ],
            file_paths=["package.json", "src/index.ts"],
        ),
    ]


if __name__ == "__main__":
    unittest.main()
