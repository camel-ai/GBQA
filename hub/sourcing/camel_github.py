"""Optional CAMEL GitHub toolkit integration for metadata reuse."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class CamelGithubToolkitAdapter:
    """Wrap the optional CAMEL ``GithubToolkit`` for file-path discovery."""

    toolkit: object | None
    availability_reason: str = ""

    @classmethod
    def create(cls, access_token: Optional[str]) -> "CamelGithubToolkitAdapter":
        """Create an adapter if CAMEL GitHub dependencies are available."""
        try:
            from camel.toolkits import GithubToolkit
        except ImportError as exc:  # pragma: no cover - environment dependent.
            return cls(toolkit=None, availability_reason=str(exc))
        try:
            toolkit = GithubToolkit(access_token=access_token or None)
        except Exception as exc:  # noqa: BLE001
            return cls(toolkit=None, availability_reason=str(exc))
        return cls(toolkit=toolkit, availability_reason="")

    @property
    def is_available(self) -> bool:
        """Return whether the CAMEL GitHub toolkit can be used."""
        return self.toolkit is not None

    def get_all_file_paths(self, repo_full_name: str) -> List[str]:
        """Return repository file paths when CAMEL toolkit support is available."""
        if self.toolkit is None:
            return []
        getter = getattr(self.toolkit, "get_all_file_paths", None)
        if getter is None:
            return []
        try:
            return list(getter(repo_full_name))
        except Exception:  # noqa: BLE001
            return []
