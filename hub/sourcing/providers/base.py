"""Base provider helpers for Hub software-project sourcing."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Callable, Dict, List, Optional

from ..fetcher import FetchError, Fetcher, FetchResponse, UrllibFetcher
from ..models import ProvenanceRecord, SoftwareProjectCandidate


class ProviderError(RuntimeError):
    """Raised when a provider cannot complete discovery."""


@dataclass(frozen=True)
class ProviderConfig:
    """Store shared provider settings."""

    limit: int = 10
    github_query: str = "archived:false fork:false stars:>=5 mirror:false"
    github_search_sort: str = "updated"
    github_page_size: int = 30


class ProviderAdapter:
    """Base class for source providers."""

    name = "provider"

    def __init__(
        self,
        *,
        fetcher: Optional[Fetcher] = None,
        config: Optional[ProviderConfig] = None,
    ) -> None:
        self.fetcher = fetcher or UrllibFetcher()
        self.config = config or ProviderConfig()

    def discover(
        self,
        limit: Optional[int] = None,
        *,
        page: int = 1,
    ) -> List[SoftwareProjectCandidate]:
        """Discover candidate software projects."""
        del page
        raise NotImplementedError

    @staticmethod
    def env(name: str, default: str = "") -> str:
        """Read one environment variable."""
        return os.getenv(name, default)

    def fetch_json(self, url: str, provenance: List[ProvenanceRecord]) -> Any:
        """Fetch one JSON resource and append provenance metadata."""
        response = self.fetcher.fetch(url, headers=self.default_headers())
        provenance.append(response.provenance())
        return response.json()

    def fetch_json_or_default(
        self,
        url: str,
        provenance: List[ProvenanceRecord],
        *,
        default: Any,
        suppress: Optional[Callable[[FetchError], bool]] = None,
    ) -> Any:
        """Fetch one JSON resource and return a fallback on allowed errors."""
        try:
            return self.fetch_json(url, provenance)
        except FetchError as exc:
            if suppress is not None and suppress(exc):
                return default
            raise

    def fetch_text(self, url: str, provenance: List[ProvenanceRecord]) -> str:
        """Fetch one text resource and append provenance metadata."""
        response = self.fetcher.fetch(url, headers=self.default_headers())
        provenance.append(response.provenance())
        return response.text

    def default_headers(self) -> Dict[str, str]:
        """Return default HTTP headers for the provider."""
        return {"Accept": "application/json"}

    @staticmethod
    def response_to_provenance(response: FetchResponse) -> ProvenanceRecord:
        """Convert a fetch response into a provenance record."""
        return response.provenance()
