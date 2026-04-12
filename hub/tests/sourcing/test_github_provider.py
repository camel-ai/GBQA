"""GitHub software-project provider tests."""

from __future__ import annotations

from pathlib import Path
import json
import unittest

from hub.sourcing.fetcher import FetchError, StaticFetcher
from hub.sourcing.providers.github import GithubSoftwareProjectProvider


FIXTURE_ROOT = Path(__file__).with_name("fixtures")


def _bundle() -> dict:
    return json.loads((FIXTURE_ROOT / "github_bundle.json").read_text(encoding="utf-8"))


def _search_url(limit: int, page: int = 1) -> str:
    return (
        "https://api.github.com/search/repositories?"
        "q=archived%3Afalse%20fork%3Afalse%20stars%3A%3E%3D5%20mirror%3Afalse"
        f"&sort=updated&order=desc&per_page={limit}&page={page}"
    )


def _build_fetcher(limit: int = 3) -> StaticFetcher:
    bundle = _bundle()
    mapping = {}
    total_items = bundle["search_items"]
    page = 1
    while True:
        start_index = (page - 1) * limit
        page_items = total_items[start_index : start_index + limit]
        mapping[_search_url(limit, page=page)] = {"items": page_items}
        if len(page_items) < limit:
            break
        page += 1
    for repo_full_name, payload in bundle["repos"].items():
        mapping[f"https://api.github.com/repos/{repo_full_name}"] = payload
        mapping[f"https://api.github.com/repos/{repo_full_name}/releases?per_page=30"] = bundle["releases"][repo_full_name]
        mapping[f"https://api.github.com/repos/{repo_full_name}/tags?per_page=30"] = bundle["tags"][repo_full_name]
        mapping[f"https://api.github.com/repos/{repo_full_name}/languages"] = bundle["languages"][repo_full_name]
        mapping[f"https://api.github.com/repos/{repo_full_name}/contributors?per_page=30&anon=1"] = bundle["contributors"][repo_full_name]
        mapping[
            "https://api.github.com/search/issues?"
            f"q=repo%3A{repo_full_name.replace('/', '%2F')}%20is%3Aissue"
        ] = bundle["issue_counts"][repo_full_name]
        mapping[
            "https://api.github.com/search/issues?"
            f"q=repo%3A{repo_full_name.replace('/', '%2F')}%20is%3Apr"
        ] = bundle["pull_request_counts"][repo_full_name]
        mapping[
            f"https://api.github.com/repos/{repo_full_name}/git/trees/main?recursive=1"
        ] = bundle["trees"][repo_full_name]
    _register_issue_verification_fixtures(mapping)
    return StaticFetcher(mapping)


def _register_issue_verification_fixtures(mapping: dict) -> None:
    """Register compare/issues responses for pipeline issue-closure verification."""
    mapping[
        "https://api.github.com/repos/acme/flow-ui/compare/v1.1.0...v1.2.0"
    ] = {
        "commits": [
            {"commit": {"message": "Fix dashboard (#145)"}},
        ],
    }
    for number in (145, 146, 147):
        mapping[f"https://api.github.com/repos/acme/flow-ui/issues/{number}"] = {
            "state": "closed",
        }
    mapping[
        "https://api.github.com/repos/acme/api-service/compare/v2.4.1...v2.5.0"
    ] = {"commits": []}
    for number in (244, 245):
        mapping[f"https://api.github.com/repos/acme/api-service/issues/{number}"] = {
            "state": "closed",
        }


class GithubProviderTests(unittest.TestCase):
    """Cover GitHub metadata extraction and architecture inference."""

    def test_provider_extracts_project_metadata(self) -> None:
        provider = GithubSoftwareProjectProvider(fetcher=_build_fetcher(limit=1))

        candidates = provider.discover(limit=1)

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.repo_full_name, "acme/flow-ui")
        self.assertEqual(candidate.engagement.issue_count, 42)
        self.assertEqual(candidate.engagement.pull_request_count, 18)
        self.assertTrue(candidate.capabilities.has_frontend)
        self.assertTrue(candidate.capabilities.has_backend)
        self.assertTrue(candidate.capabilities.has_database)
        self.assertEqual(candidate.capabilities.interaction_mode, "mixed")
        self.assertEqual(candidate.release_notes_url, "https://github.com/acme/flow-ui/releases/tag/v1.2.0")

    def test_provider_identifies_backend_only_repository(self) -> None:
        provider = GithubSoftwareProjectProvider(fetcher=_build_fetcher(limit=2))

        candidates = provider.discover(limit=2)

        candidate = next(item for item in candidates if item.repo_full_name == "acme/api-service")
        self.assertFalse(candidate.capabilities.has_frontend)
        self.assertTrue(candidate.capabilities.has_backend)
        self.assertTrue(candidate.capabilities.has_database)
        self.assertEqual(candidate.capabilities.interaction_mode, "api_cli")

    def test_provider_supports_paginated_discovery(self) -> None:
        provider = GithubSoftwareProjectProvider(fetcher=_build_fetcher(limit=1))

        candidates = provider.discover(limit=1, page=2)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].repo_full_name, "acme/api-service")

    def test_provider_tolerates_large_contributor_endpoint_overflow(self) -> None:
        base_fetcher = _build_fetcher(limit=1)

        class ContributorOverflowFetcher:
            def __init__(self, wrapped: StaticFetcher) -> None:
                self._wrapped = wrapped

            def fetch(self, url: str, *, headers=None):
                if (
                    url
                    == "https://api.github.com/repos/acme/flow-ui/contributors?per_page=30&anon=1"
                ):
                    raise FetchError(
                        "contributors too large",
                        url=url,
                        status_code=403,
                        body=(
                            '{"message":"The history or contributor list is too large to '
                            'list contributors for this repository via the API."}'
                        ),
                    )
                return self._wrapped.fetch(url, headers=headers)

        provider = GithubSoftwareProjectProvider(
            fetcher=ContributorOverflowFetcher(base_fetcher)
        )

        candidates = provider.discover(limit=1)

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.repo_full_name, "acme/flow-ui")
        self.assertEqual(candidate.engagement.contributor_count, 0)
        self.assertFalse(candidate.extra["contributors_metadata_complete"])

    def test_provider_tolerates_pull_search_timeout(self) -> None:
        base_fetcher = _build_fetcher(limit=1)

        class PullTimeoutFetcher:
            def __init__(self, wrapped: StaticFetcher) -> None:
                self._wrapped = wrapped

            def fetch(self, url: str, *, headers=None):
                if (
                    url
                    == "https://api.github.com/search/issues?q=repo%3Aacme%2Fflow-ui%20is%3Apr"
                ):
                    raise FetchError(
                        "failed to fetch pull totals: ssl handshake timed out",
                        url=url,
                        status_code=None,
                        body="",
                    )
                return self._wrapped.fetch(url, headers=headers)

        provider = GithubSoftwareProjectProvider(
            fetcher=PullTimeoutFetcher(base_fetcher)
        )

        candidates = provider.discover(limit=1)

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.repo_full_name, "acme/flow-ui")
        self.assertEqual(candidate.engagement.issue_count, 42)
        self.assertEqual(candidate.engagement.pull_request_count, 0)
        self.assertFalse(candidate.extra["pulls_metadata_complete"])
