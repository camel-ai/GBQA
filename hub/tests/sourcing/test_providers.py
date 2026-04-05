"""Fixture-backed provider tests."""

from __future__ import annotations

from pathlib import Path
import json
import os
import unittest
from unittest.mock import patch

from hub.sourcing.fetcher import StaticFetcher
from hub.sourcing.providers.github import GitHubProvider
from hub.sourcing.providers.itch import ItchProvider
from hub.sourcing.providers.steam import SteamProvider


FIXTURE_ROOT = Path(__file__).with_name("fixtures")


def _json_fixture(name: str):
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def _text_fixture(name: str) -> str:
    return (FIXTURE_ROOT / name).read_text(encoding="utf-8")


class ProviderTests(unittest.TestCase):
    def test_github_provider_normalizes_versions_and_patch_notes(self) -> None:
        query = "topic%3Agame%20archived%3Afalse%20fork%3Afalse%20stars%3A%3E%3D5"
        fetcher = StaticFetcher(
            {
                f"https://api.github.com/search/repositories?q={query}&sort=updated&order=desc&per_page=1": _json_fixture(
                    "github_search.json"
                ),
                "https://api.github.com/repos/acme/retro-blaster/releases?per_page=20": _json_fixture(
                    "github_releases.json"
                ),
                "https://api.github.com/repos/acme/retro-blaster/tags?per_page=20": _json_fixture(
                    "github_tags.json"
                ),
            }
        )
        provider = GitHubProvider(fetcher=fetcher)

        candidates = provider.discover(limit=1)

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.provider, "github")
        self.assertEqual(candidate.title, "retro-blaster")
        self.assertEqual(candidate.license, "MIT")
        self.assertEqual(len(candidate.versions), 2)
        self.assertEqual(candidate.versions[0].version, "1.1.0")
        self.assertEqual(candidate.patches[0].version, "1.2.0")
        self.assertTrue(candidate.capabilities.has_public_source)
        self.assertTrue(candidate.capabilities.has_patch_notes)

    def test_itch_provider_reads_feed_page_and_devlogs(self) -> None:
        fetcher = StaticFetcher(
            {
                "https://itch.io/browse/price-free.xml": _text_fixture("itch_feed.xml"),
                "https://acme.itch.io/pixel-forge": _text_fixture("itch_game_page.html"),
                "https://acme.itch.io/pixel-forge/devlog/120/update-1-2": _text_fixture(
                    "itch_devlog_1_2.html"
                ),
                "https://acme.itch.io/pixel-forge/devlog/110/update-1-1": _text_fixture(
                    "itch_devlog_1_1.html"
                ),
            }
        )
        provider = ItchProvider(fetcher=fetcher)

        candidates = provider.discover(limit=1)

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.provider, "itch")
        self.assertEqual(candidate.title, "Pixel Forge")
        self.assertEqual(candidate.source_repo_url, "https://github.com/acme/pixel-forge")
        self.assertGreaterEqual(len(candidate.versions), 2)
        self.assertEqual(candidate.patches[0].version, "1.2")
        self.assertTrue(candidate.capabilities.is_free)

    def test_steam_provider_requires_key_and_extracts_news(self) -> None:
        fetcher = StaticFetcher(
            {
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
        )
        with patch.dict(os.environ, {"STEAM_WEB_API_KEY": "test-key"}, clear=False):
            provider = SteamProvider(fetcher=fetcher)
            candidates = provider.discover(limit=1)

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.provider, "steam")
        self.assertTrue(candidate.capabilities.has_patch_notes)
        self.assertEqual(candidate.runtime_kind, "native_desktop")
        self.assertEqual(candidate.source_repo_url, "https://github.com/acme/open-factory")
