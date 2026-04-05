"""Base provider helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import os

from ..fetcher import Fetcher, FetchResponse, UrllibFetcher
from ..models import CandidateGame, ProvenanceRecord


class ProviderError(RuntimeError):
    """Raised when a provider cannot complete discovery."""


@dataclass(slots=True)
class ProviderConfig:
    """Shared provider settings."""

    limit: int = 10
    github_query: str = "topic:game archived:false fork:false stars:>=5"
    itch_browse_feed_url: str = "https://itch.io/browse/price-free.xml"
    steam_store_language: str = "english"


class ProviderAdapter:
    """Base class for provider adapters."""

    name = "provider"

    def __init__(
        self,
        *,
        fetcher: Optional[Fetcher] = None,
        config: Optional[ProviderConfig] = None,
    ) -> None:
        self.fetcher = fetcher or UrllibFetcher()
        self.config = config or ProviderConfig()

    def discover(self, limit: Optional[int] = None) -> List[CandidateGame]:
        raise NotImplementedError

    @staticmethod
    def env(name: str, default: str = "") -> str:
        return os.getenv(name, default)

    def fetch_json(self, url: str, provenance: List[ProvenanceRecord]) -> Any:
        response = self.fetcher.fetch(url, headers=self.default_headers())
        provenance.append(response.provenance())
        return response.json()

    def fetch_text(self, url: str, provenance: List[ProvenanceRecord]) -> str:
        response = self.fetcher.fetch(url, headers=self.default_headers())
        provenance.append(response.provenance())
        return response.text

    def default_headers(self) -> Dict[str, str]:
        return {"Accept": "application/json"}

    @staticmethod
    def response_to_provenance(response: FetchResponse) -> ProvenanceRecord:
        return response.provenance()
