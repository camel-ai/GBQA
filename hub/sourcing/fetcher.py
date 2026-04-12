"""HTTP fetch abstractions used by the sourcing providers."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import urllib.error
import urllib.request
from typing import Any, Dict, Mapping, Optional, Protocol

from .models import ProvenanceRecord
from .utils import now_iso, sha256_text


class FetchError(RuntimeError):
    """Raised when an HTTP resource cannot be fetched."""

    def __init__(
        self,
        message: str,
        *,
        url: str = "",
        status_code: int | None = None,
        body: str = "",
    ) -> None:
        super().__init__(message)
        self.url = url
        self.status_code = status_code
        self.body = body


@dataclass(slots=True)
class FetchResponse:
    """Normalized HTTP response payload."""

    url: str
    text: str
    status: int = 200
    headers: Dict[str, str] = field(default_factory=dict)
    fetched_at: str = field(default_factory=now_iso)

    @property
    def sha256(self) -> str:
        return sha256_text(self.text)

    def json(self) -> Any:
        return json.loads(self.text)

    def provenance(self) -> ProvenanceRecord:
        return ProvenanceRecord(
            url=self.url,
            sha256=self.sha256,
            fetched_at=self.fetched_at,
            content_type=self.headers.get("Content-Type", ""),
        )


class Fetcher(Protocol):
    """Protocol used by providers and tests."""

    def fetch(
        self,
        url: str,
        *,
        headers: Optional[Mapping[str, str]] = None,
    ) -> FetchResponse:
        ...


class UrllibFetcher:
    """Default network fetcher based on the Python standard library."""

    def __init__(self, timeout: int = 20, user_agent: str = "GBQA Hub Sourcing/1.0"):
        self._timeout = timeout
        self._user_agent = user_agent

    def fetch(
        self,
        url: str,
        *,
        headers: Optional[Mapping[str, str]] = None,
    ) -> FetchResponse:
        request_headers = {"User-Agent": self._user_agent}
        if headers:
            request_headers.update(headers)
        request = urllib.request.Request(url, headers=request_headers)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                data = response.read().decode("utf-8", errors="replace")
                return FetchResponse(
                    url=str(response.geturl()),
                    text=data,
                    status=int(getattr(response, "status", 200)),
                    headers={key: value for key, value in response.headers.items()},
                )
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise FetchError(
                f"{url} returned HTTP {exc.code}: {body[:200]}",
                url=url,
                status_code=exc.code,
                body=body,
            ) from exc
        except urllib.error.URLError as exc:
            raise FetchError(
                f"failed to fetch {url}: {exc.reason}",
                url=url,
            ) from exc


class StaticFetcher:
    """Fixture-backed fetcher used by tests."""

    def __init__(self, responses: Mapping[str, Any]):
        self._responses = dict(responses)

    def fetch(
        self,
        url: str,
        *,
        headers: Optional[Mapping[str, str]] = None,
    ) -> FetchResponse:
        del headers
        if url not in self._responses:
            raise FetchError(f"missing fixture for {url}")
        payload = self._responses[url]
        if isinstance(payload, FetchResponse):
            return payload
        if isinstance(payload, (dict, list)):
            text = json.dumps(payload)
            return FetchResponse(
                url=url,
                text=text,
                headers={"Content-Type": "application/json"},
            )
        return FetchResponse(url=url, text=str(payload))
