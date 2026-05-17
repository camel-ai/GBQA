from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Mapping, Protocol
import urllib.error
import urllib.request

from .models import ProvenanceRecord
from .utils import now_iso, sha256_text


class FetchError(RuntimeError):
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
    url: str
    text: str
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    fetched_at: str = field(default_factory=now_iso)

    def json(self) -> Any:
        return json.loads(self.text)

    def provenance(self) -> ProvenanceRecord:
        return ProvenanceRecord(
            url=self.url,
            sha256=sha256_text(self.text),
            fetched_at=self.fetched_at,
            content_type=self.headers.get("Content-Type", ""),
        )


class Fetcher(Protocol):
    def fetch(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> FetchResponse:
        ...


class UrllibFetcher:
    def __init__(self, timeout: int = 20, user_agent: str = "GBQA Environment Sourcing/0.1"):
        self._timeout = timeout
        self._user_agent = user_agent

    def fetch(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> FetchResponse:
        request_headers = {"User-Agent": self._user_agent}
        if headers:
            request_headers.update(headers)
        request = urllib.request.Request(url, headers=request_headers)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                text = response.read().decode("utf-8", errors="replace")
                return FetchResponse(
                    url=str(response.geturl()),
                    text=text,
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
            raise FetchError(f"failed to fetch {url}: {exc.reason}", url=url) from exc


class StaticFetcher:
    def __init__(self, responses: Mapping[str, Any]):
        self._responses = dict(responses)

    def fetch(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> FetchResponse:
        del headers
        if url not in self._responses:
            raise FetchError(f"missing fixture for {url}", url=url)
        payload = self._responses[url]
        if isinstance(payload, Exception):
            raise payload
        if isinstance(payload, FetchResponse):
            return payload
        if isinstance(payload, (dict, list)):
            return FetchResponse(
                url=url,
                text=json.dumps(payload),
                headers={"Content-Type": "application/json"},
            )
        return FetchResponse(url=url, text=str(payload))
