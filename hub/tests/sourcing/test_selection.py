"""Selection and publication tests."""

from __future__ import annotations

from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from hub.sourcing.ground_truth import GroundTruthGenerator
from hub.sourcing.models import CandidateGame, CapabilityMatrix, PatchRecord, VersionRecord
from hub.sourcing.pipeline import SourcingPipeline
from hub.sourcing.pairing import resolve_version_pair
from hub.sourcing.scoring import score_candidate

from hub.sourcing.fetcher import StaticFetcher
from hub.tests.sourcing.test_providers import _json_fixture, _text_fixture


class SelectionTests(unittest.TestCase):
    def test_scoring_rejects_hard_filter_failures(self) -> None:
        candidate = CandidateGame(
            game_id="bad-game",
            title="Bad Game",
            provider="github",
            provider_id="bad",
            slug="bad-game",
            summary="Prototype jam game.",
            homepage_url="",
            source_repo_url="",
            license="",
            runtime_kind="web",
            capabilities=CapabilityMatrix(
                is_free=False,
                has_public_source=False,
                has_historical_builds=False,
                has_version_trail=False,
                has_patch_notes=False,
                has_official_patch_notes=False,
                runnable_locally=False,
                blocks_archival_replay=True,
            ),
        )

        breakdown = score_candidate(candidate)

        self.assertIn("not_free", breakdown.hard_filter_failures)
        self.assertIn("archival_replay_blocked", breakdown.hard_filter_failures)

    def test_ground_truth_generation_preserves_required_bug_fields(self) -> None:
        candidate = CandidateGame(
            game_id="retro-blaster",
            title="Retro Blaster",
            provider="github",
            provider_id="101",
            slug="retro-blaster",
            summary="Arcade shooter.",
            homepage_url="https://retro.example.com",
            source_repo_url="https://github.com/acme/retro-blaster",
            license="MIT",
            runtime_kind="native_desktop",
            versions=[
                VersionRecord(
                    version="1.1.0",
                    published_at="2025-11-01T00:00:00Z",
                    artifact_url="https://downloads.example.com/retro-1.1.zip",
                ),
                VersionRecord(
                    version="1.2.0",
                    published_at="2026-02-01T00:00:00Z",
                    artifact_url="https://downloads.example.com/retro-1.2.zip",
                ),
            ],
            patches=[
                PatchRecord(
                    patch_id="github-v1-2-0",
                    version="1.2.0",
                    title="Version 1.2.0",
                    published_at="2026-02-01T00:00:00Z",
                    notes_url="https://github.com/acme/retro-blaster/releases/tag/v1.2.0",
                    body="- Fixed save file corruption after boss fights.\n- Fixed the inventory UI overlapping mission text.",
                )
            ],
            capabilities=CapabilityMatrix(
                is_free=True,
                has_public_source=True,
                has_historical_builds=True,
                has_version_trail=True,
                has_patch_notes=True,
                has_official_patch_notes=True,
                runnable_locally=True,
                blocks_archival_replay=False,
            ),
        )
        pair = resolve_version_pair(candidate)
        generator = GroundTruthGenerator(llm_client=None)

        bundle = generator.generate(candidate, pair)

        self.assertEqual(bundle.total_bugs, 2)
        bug = bundle.bugs[0]
        self.assertIn("id", bug)
        self.assertIn("bug_type", bug)
        self.assertIn("difficulty", bug)
        self.assertIn("minimal_reproduction", bug)
        self.assertIn("observed_fault", bug)
        self.assertIn("source_patch_url", bug)

    def test_pipeline_run_publishes_catalog_for_each_provider(self) -> None:
        github_query = "topic%3Agame%20archived%3Afalse%20fork%3Afalse%20stars%3A%3E%3D5"
        responses = {
            f"https://api.github.com/search/repositories?q={github_query}&sort=updated&order=desc&per_page=1": _json_fixture(
                "github_search.json"
            ),
            "https://api.github.com/repos/acme/retro-blaster/releases?per_page=20": _json_fixture(
                "github_releases.json"
            ),
            "https://api.github.com/repos/acme/retro-blaster/tags?per_page=20": _json_fixture(
                "github_tags.json"
            ),
            "https://itch.io/browse/price-free.xml": _text_fixture("itch_feed.xml"),
            "https://acme.itch.io/pixel-forge": _text_fixture("itch_game_page.html"),
            "https://acme.itch.io/pixel-forge/devlog/120/update-1-2": _text_fixture(
                "itch_devlog_1_2.html"
            ),
            "https://acme.itch.io/pixel-forge/devlog/110/update-1-1": _text_fixture(
                "itch_devlog_1_1.html"
            ),
            "https://partner.steam-api.com/IStoreService/GetAppList/v1/?key=test-key&max_results=1&include_games=true": _json_fixture(
                "steam_app_list.json"
            ),
            "https://store.steampowered.com/app/12345/?l=english": _text_fixture(
                "steam_store_page.html"
            ),
            "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid=12345&count=10&maxlength=5000&format=json": _json_fixture(
                "steam_news.json"
            ),
        }
        fetcher = StaticFetcher(responses)
        with tempfile.TemporaryDirectory() as temp_dir:
            pipeline = SourcingPipeline(output_dir=Path(temp_dir), fetcher=fetcher)
            with patch.dict("os.environ", {"STEAM_WEB_API_KEY": "test-key"}, clear=False):
                selected = pipeline.run(
                    providers=("github", "itch", "steam"),
                    limit=1,
                    allow_partial=False,
                    minimum_score=60.0,
                )

            self.assertEqual(len(selected), 3)
            catalog = Path(temp_dir) / "candidates.jsonl"
            self.assertTrue(catalog.exists())
            lines = [json.loads(line) for line in catalog.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(lines), 3)
            for game_id in ("retro-blaster", "pixel-forge", "open-factory"):
                manifest_path = Path(temp_dir) / "selected" / game_id / "manifest.json"
                self.assertTrue(manifest_path.exists())
                bug_dir = Path(temp_dir) / "selected" / game_id / "bugs"
                self.assertTrue(any(bug_dir.iterdir()))
