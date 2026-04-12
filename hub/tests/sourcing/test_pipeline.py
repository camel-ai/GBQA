"""Pipeline tests for GitHub software-project sourcing."""

from __future__ import annotations

from pathlib import Path
import json
import tempfile
import unittest

from hub.sourcing.fetcher import FetchError
from hub.sourcing.ground_truth import GroundTruthGenerator
from hub.sourcing.pipeline import SourcingPipeline

from hub.tests.sourcing.test_github_provider import _build_fetcher


class PipelineTests(unittest.TestCase):
    """Cover release-pair selection, dedupe, and catalog publication."""

    def test_ground_truth_contains_taxonomy_metadata(self) -> None:
        pipeline = SourcingPipeline(fetcher=_build_fetcher(limit=1))
        discovered = pipeline.discover(providers=("github",), limit=1)
        scored = pipeline.score(discovered)
        candidate = scored[0]

        bundle = GroundTruthGenerator(llm_client=None).generate(
            candidate,
            candidate.selected_release_pair,
        )

        self.assertEqual(bundle.total_bugs, 3)
        bug = bundle.bugs[0]
        self.assertIn("primary_category", bug)
        self.assertIn("taxonomy_source", bug)
        self.assertIn("minimal_reproduction", bug)
        self.assertEqual(
            bug["source_patch_url"],
            "https://github.com/acme/flow-ui/pull/145",
        )
        self.assertNotIn(
            "Added exports center.",
            [entry["source_excerpt"] for entry in bundle.bugs],
        )

    def test_latest_release_is_used_for_release_pair_and_ground_truth(self) -> None:
        pipeline = SourcingPipeline(fetcher=_build_fetcher(limit=1))
        discovered = pipeline.discover(providers=("github",), limit=1)
        scored = pipeline.score(discovered)
        candidate = scored[0]

        self.assertIsNotNone(candidate.selected_release_pair)
        self.assertEqual(candidate.selected_release_pair.baseline_version, "1.1.0")
        self.assertEqual(candidate.selected_release_pair.fix_version, "1.2.0")
        self.assertEqual(candidate.selected_release_pair.release_id, "v1.2.0")
        self.assertEqual(
            candidate.release_notes_url,
            "https://github.com/acme/flow-ui/releases/tag/v1.2.0",
        )

    def test_issue_verification_can_be_disabled_explicitly(self) -> None:
        pipeline = SourcingPipeline(
            fetcher=_build_fetcher(limit=1),
            verify_issue_closure=False,
        )
        discovered = pipeline.discover(providers=("github",), limit=1)
        scored = pipeline.score(discovered)

        candidate = scored[0]
        self.assertFalse(candidate.capabilities.has_tracked_issue_closure)
        self.assertEqual(
            candidate.extra["issue_verification"]["reason"],
            "verification_disabled",
        )

    def test_pipeline_publishes_two_selected_projects_and_rejects_one(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pipeline = SourcingPipeline(
                output_dir=Path(temp_dir),
                fetcher=_build_fetcher(limit=3),
            )

            selected = pipeline.run(
                providers=("github",),
                limit=3,
                allow_partial=False,
                minimum_score=60.0,
            )

            self.assertEqual(len(selected), 2)
            catalog_rows = [
                json.loads(line)
                for line in (Path(temp_dir) / "candidates.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(len(catalog_rows), 3)
            self.assertTrue((Path(temp_dir) / "index.json").exists())
            self.assertTrue((Path(temp_dir) / "selected" / "acme-flow-ui" / "manifest.json").exists())
            self.assertTrue((Path(temp_dir) / "selected" / "acme-api-service" / "manifest.json").exists())
            rejected = next(item for item in catalog_rows if item["repo_full_name"] == "acme/widget-lib")
            self.assertIn("missing_release_history", rejected["rejection_reasons"])

    def test_second_run_skips_same_repo_and_release_pair(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pipeline = SourcingPipeline(
                output_dir=Path(temp_dir),
                fetcher=_build_fetcher(limit=2),
            )
            pipeline.run(
                providers=("github",),
                limit=2,
                allow_partial=False,
                minimum_score=60.0,
            )

            rerun_pipeline = SourcingPipeline(
                output_dir=Path(temp_dir),
                fetcher=_build_fetcher(limit=2),
            )
            discovered = rerun_pipeline.discover(providers=("github",), limit=2)
            scored = rerun_pipeline.score(discovered)

            for candidate in scored:
                self.assertIn("already_saved_pair", candidate.rejection_reasons)

    def test_run_can_continue_until_minimum_selected_is_reached(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pipeline = SourcingPipeline(
                output_dir=Path(temp_dir),
                fetcher=_build_fetcher(limit=1),
            )

            selected = pipeline.run(
                providers=("github",),
                limit=1,
                allow_partial=False,
                minimum_score=60.0,
                minimum_selected=2,
            )

            self.assertEqual(len(selected), 2)
            catalog_rows = [
                json.loads(line)
                for line in (Path(temp_dir) / "candidates.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(len(catalog_rows), 2)
            self.assertEqual(
                [item["repo_full_name"] for item in catalog_rows],
                ["acme/flow-ui", "acme/api-service"],
            )

    def test_run_allow_partial_tolerates_paginated_fetch_failure(self) -> None:
        base_fetcher = _build_fetcher(limit=1)

        class SecondPageFailureFetcher:
            def __init__(self, wrapped) -> None:
                self._wrapped = wrapped

            def fetch(self, url: str, *, headers=None):
                if url.endswith("&per_page=1&page=2"):
                    raise FetchError(
                        "search page timed out",
                        url=url,
                        status_code=None,
                        body="",
                    )
                return self._wrapped.fetch(url, headers=headers)

        with tempfile.TemporaryDirectory() as temp_dir:
            pipeline = SourcingPipeline(
                output_dir=Path(temp_dir),
                fetcher=SecondPageFailureFetcher(base_fetcher),
            )

            selected = pipeline.run(
                providers=("github",),
                limit=1,
                allow_partial=True,
                minimum_score=60.0,
                minimum_selected=2,
            )

            self.assertEqual(len(selected), 1)
            self.assertEqual(selected[0].repo_full_name, "acme/flow-ui")
