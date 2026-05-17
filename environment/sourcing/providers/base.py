from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Protocol

from ..fetcher import Fetcher, UrllibFetcher
from ..models import ProvenanceRecord, RepositoryCandidate


class ProviderError(RuntimeError):
    pass


class RepositoryProvider(Protocol):
    name: str

    def discover(
        self,
        *,
        query: str,
        limit: int,
        page: int = 1,
    ) -> list[RepositoryCandidate]:
        ...


@dataclass(frozen=True)
class ProviderConfig:
    github_query: str = "archived:false fork:false stars:>=10 mirror:false"
    github_search_sort: str = "updated"
    github_page_size: int = 30


class BaseRepositoryProvider:
    name = "provider"

    def __init__(
        self,
        *,
        fetcher: Fetcher | None = None,
        config: ProviderConfig | None = None,
    ) -> None:
        self.fetcher = fetcher or UrllibFetcher()
        self.config = config or ProviderConfig()

    @staticmethod
    def env(name: str, default: str = "") -> str:
        return os.getenv(name, default)

    def default_headers(self) -> dict[str, str]:
        return {"Accept": "application/json"}

    def fetch_json(self, url: str, provenance: list[ProvenanceRecord]):
        response = self.fetcher.fetch(url, headers=self.default_headers())
        provenance.append(response.provenance())
        return response.json()
