"""Authentication flow tests."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from hub.sourcing.auth import CredentialStore, InteractiveAuthFlow
from hub.sourcing.fetcher import FetchError
from hub.sourcing.providers.base import ProviderError


class AuthTests(unittest.TestCase):
    def test_credential_store_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            store = CredentialStore(path=env_path)

            store.write({"GITHUB_TOKEN": "abc", "STEAM_WEB_API_KEY": "def"})

            self.assertEqual(
                store.load(),
                {"GITHUB_TOKEN": "abc", "STEAM_WEB_API_KEY": "def"},
            )

    def test_github_rate_limit_error_is_detected(self) -> None:
        error = FetchError(
            "rate limit",
            url="https://api.github.com/repos/example/example/releases",
            status_code=403,
            body='{"message":"API rate limit exceeded"}',
        )

        self.assertTrue(InteractiveAuthFlow._is_github_rate_limit(error))

    def test_github_bad_credentials_error_is_detected(self) -> None:
        error = FetchError(
            "bad credentials",
            url="https://api.github.com/search/repositories?q=game",
            status_code=401,
            body='{"message":"Bad credentials"}',
        )

        self.assertTrue(InteractiveAuthFlow._is_github_bad_credentials(error))

    def test_missing_steam_key_error_is_detected(self) -> None:
        error = ProviderError("STEAM_WEB_API_KEY is required for Steam discovery")

        self.assertTrue(InteractiveAuthFlow._is_missing_steam_key(error))
