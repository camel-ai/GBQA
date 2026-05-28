from __future__ import annotations

import unittest

from environment.sourcing.fetcher import FetchError, StaticFetcher
from environment.sourcing.providers.github import GitHubRepositoryProvider


class GitHubProviderTests(unittest.TestCase):
    def test_discover_skips_repository_detail_fetch_failures(self) -> None:
        fetcher = StaticFetcher(
            {
                "https://api.github.com/search/repositories?q=repo%3Atest&sort=updated&order=desc&per_page=2&page=1": {
                    "items": [
                        {"full_name": "acme/broken"},
                        {"full_name": "acme/working"},
                    ]
                },
                "https://api.github.com/repos/acme/broken": FetchError(
                    "transient network error",
                    url="https://api.github.com/repos/acme/broken",
                ),
                "https://api.github.com/repos/acme/working": {
                    "owner": {"login": "acme"},
                    "name": "working",
                    "full_name": "acme/working",
                    "html_url": "https://github.com/acme/working",
                    "clone_url": "https://github.com/acme/working.git",
                    "default_branch": "main",
                    "description": "Working API",
                    "topics": ["api"],
                    "license": {"spdx_id": "Apache-2.0"},
                    "stargazers_count": 1,
                    "forks_count": 0,
                    "open_issues_count": 0,
                    "archived": False,
                    "fork": False,
                    "is_template": False,
                },
                "https://api.github.com/repos/acme/working/releases?per_page=30": [],
                "https://api.github.com/repos/acme/working/languages": {"Python": 100},
                "https://api.github.com/repos/acme/working/git/trees/main?recursive=1": {
                    "tree": [{"type": "blob", "path": "app.py"}]
                },
            }
        )
        provider = GitHubRepositoryProvider(fetcher=fetcher)

        repositories = provider.discover(query="repo:test", limit=2)

        self.assertEqual([repository.full_name for repository in repositories], ["acme/working"])


if __name__ == "__main__":
    unittest.main()
