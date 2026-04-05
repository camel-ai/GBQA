"""Interactive credential setup for the Hub sourcing CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import getpass
import os
import sys
from typing import Callable, Dict, Iterable, Mapping, Optional, Sequence

from .fetcher import FetchError
from .providers.base import ProviderError


PromptFunc = Callable[[str], str]
PrintFunc = Callable[[str], None]


@dataclass(slots=True)
class CredentialField:
    """Single credential definition."""

    env_name: str
    display_name: str
    docs_url: str
    required_for: str
    acquisition_steps: Sequence[str]


GITHUB_FIELD = CredentialField(
    env_name="GITHUB_TOKEN",
    display_name="GitHub personal access token",
    docs_url="https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens",
    required_for="higher GitHub API rate limits during repository, release, and tag discovery",
    acquisition_steps=(
        "Sign in to GitHub and open Settings.",
        "Go to Developer settings -> Personal access tokens.",
        "Prefer a fine-grained token when possible. GitHub recommends fine-grained tokens.",
        "Create a token that can read public repository metadata for the repos you want to inspect.",
        "Copy the token once and paste it into this CLI when prompted.",
    ),
)

STEAM_FIELD = CredentialField(
    env_name="STEAM_WEB_API_KEY",
    display_name="Steam Web API key",
    docs_url="https://partner.steamgames.com/doc/webapi_overview/auth",
    required_for="Steam discovery via partner.steam-api.com",
    acquisition_steps=(
        "Sign in to Steamworks with an administrator-capable account.",
        "Open Users & Permissions -> Manage Groups.",
        "Create or select a group for Web API access.",
        "Choose Create WebAPI Key and save the desired permissions.",
        "Copy the key shown in the group page sidebar and paste it into this CLI.",
    ),
)


class CredentialStore:
    """Simple `.env` store scoped to `hub/sourcing`."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or Path(__file__).resolve().with_name(".env")

    def load(self) -> Dict[str, str]:
        if not self.path.exists():
            return {}
        values: Dict[str, str] = {}
        for line in self.path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            values[key.strip()] = value.strip()
        return values

    def apply(self) -> Dict[str, str]:
        values = self.load()
        for key, value in values.items():
            os.environ.setdefault(key, value)
        return values

    def write(self, updates: Mapping[str, str]) -> None:
        current = self.load()
        current.update({key: value for key, value in updates.items() if value})
        lines = [f"{key}={value}" for key, value in sorted(current.items())]
        self.path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    def delete(self, keys: Iterable[str]) -> None:
        current = self.load()
        for key in keys:
            current.pop(key, None)
        lines = [f"{key}={value}" for key, value in sorted(current.items())]
        self.path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


class InteractiveAuthFlow:
    """Terminal-driven credential setup and retry assistance."""

    def __init__(
        self,
        *,
        store: Optional[CredentialStore] = None,
        prompt: PromptFunc = input,
        secret_prompt: PromptFunc = getpass.getpass,
        printer: PrintFunc = print,
    ) -> None:
        self.store = store or CredentialStore()
        self._prompt = prompt
        self._secret_prompt = secret_prompt
        self._print = printer

    @staticmethod
    def is_interactive() -> bool:
        return sys.stdin.isatty() and sys.stdout.isatty()

    def bootstrap(self, providers: Sequence[str]) -> None:
        self.store.apply()
        if not self.is_interactive():
            return
        if "github" in providers and not os.getenv(GITHUB_FIELD.env_name):
            self._print("")
            self._print("GitHub discovery works without a token, but it is easy to hit the unauthenticated rate limit.")
            self._offer_setup(GITHUB_FIELD, required=False)
        if "steam" in providers and not os.getenv(STEAM_FIELD.env_name):
            self._print("")
            self._print("Steam discovery uses the partner Steam Web API and needs a Steam Web API key.")
            self._offer_setup(STEAM_FIELD, required=False)

    def configure(self, providers: Iterable[str]) -> None:
        """Explicitly prompt for credential setup for selected providers."""
        self.store.apply()
        if not self.is_interactive():
            return
        for provider in providers:
            if provider == "github":
                self._offer_setup(GITHUB_FIELD, required=False)
            elif provider == "steam":
                self._offer_setup(STEAM_FIELD, required=False)

    def recoverable_auth_error(self, exc: Exception) -> bool:
        if not self.is_interactive():
            return False
        if self._is_github_bad_credentials(exc):
            self._print("")
            self._print("GitHub rejected the configured token with `401 Bad credentials`.")
            return self._replace_credential(GITHUB_FIELD)
        if self._is_github_rate_limit(exc):
            self._print("")
            self._print("GitHub returned an API rate-limit response.")
            return self._offer_setup(GITHUB_FIELD, required=True)
        if self._is_missing_steam_key(exc):
            self._print("")
            self._print("Steam discovery cannot continue without `STEAM_WEB_API_KEY`.")
            return self._offer_setup(STEAM_FIELD, required=True)
        return False

    def _offer_setup(
        self,
        field: CredentialField,
        *,
        required: bool,
        force: bool = False,
    ) -> bool:
        if os.getenv(field.env_name) and not force:
            return True
        self._print(f"{field.display_name} setup")
        self._print(f"Why it is needed: {field.required_for}")
        self._print(f"Docs: {field.docs_url}")
        if self._yes_no("Show step-by-step instructions now?", default=True):
            for index, step in enumerate(field.acquisition_steps, start=1):
                self._print(f"{index}. {step}")
        if not self._yes_no("Enter the key in this terminal now?", default=required):
            if required:
                self._print(f"Skipping {field.env_name} leaves this provider unavailable.")
            return False
        value = self._secret_prompt(f"Paste {field.env_name}: ").strip()
        if not value:
            self._print("No value was entered.")
            return False
        os.environ[field.env_name] = value
        if self._yes_no(
            f"Save {field.env_name} to {self.store.path} for future runs?",
            default=True,
        ):
            self.store.write({field.env_name: value})
            self._print(f"Saved {field.env_name} to {self.store.path}.")
        else:
            self._print(f"Using {field.env_name} only for this process.")
        return True

    def _replace_credential(self, field: CredentialField) -> bool:
        current = os.getenv(field.env_name, "")
        if current:
            self._print(f"An existing value is set for {field.env_name}.")
        if self._yes_no("Remove the saved local value before re-entering it?", default=True):
            self.store.delete([field.env_name])
            os.environ.pop(field.env_name, None)
            self._print(f"Cleared saved {field.env_name} from {self.store.path}.")
        return self._offer_setup(field, required=True, force=True)

    def _yes_no(self, prompt_text: str, *, default: bool) -> bool:
        suffix = "[Y/n]" if default else "[y/N]"
        raw = self._prompt(f"{prompt_text} {suffix} ").strip().lower()
        if not raw:
            return default
        return raw in {"y", "yes"}

    @staticmethod
    def _is_github_rate_limit(exc: Exception) -> bool:
        if not isinstance(exc, FetchError):
            return False
        if exc.status_code != 403:
            return False
        haystack = f"{exc.url}\n{exc.body}".lower()
        return "api.github.com" in haystack and "rate limit" in haystack

    @staticmethod
    def _is_github_bad_credentials(exc: Exception) -> bool:
        if not isinstance(exc, FetchError):
            return False
        if exc.status_code != 401:
            return False
        haystack = f"{exc.url}\n{exc.body}".lower()
        return "api.github.com" in haystack and "bad credentials" in haystack

    @staticmethod
    def _is_missing_steam_key(exc: Exception) -> bool:
        return isinstance(exc, ProviderError) and "STEAM_WEB_API_KEY" in str(exc)
