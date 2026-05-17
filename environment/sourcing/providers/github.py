from __future__ import annotations

from urllib.parse import quote

from ..fetcher import FetchError
from ..models import ReleaseRecord, RepositoryCandidate
from ..utils import clean_text, slugify
from .base import BaseRepositoryProvider, ProviderConfig


class GitHubRepositoryProvider(BaseRepositoryProvider):
    name = "github"
    _API_ROOT = "https://api.github.com"

    def default_headers(self) -> dict[str, str]:
        headers = super().default_headers()
        token = self.env("GITHUB_TOKEN") or self.env("GITHUB_ACCESS_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        headers["Accept"] = "application/vnd.github+json"
        return headers

    def discover(
        self,
        *,
        query: str | None = None,
        limit: int,
        page: int = 1,
    ) -> list[RepositoryCandidate]:
        resolved_query = query or self.config.github_query
        per_page = max(1, min(limit, self.config.github_page_size))
        search_url = (
            f"{self._API_ROOT}/search/repositories?q={quote(resolved_query, safe='')}"
            f"&sort={self.config.github_search_sort}&order=desc"
            f"&per_page={per_page}&page={page}"
        )
        provenance = []
        payload = self.fetch_json(search_url, provenance)
        items = payload.get("items", []) if isinstance(payload, dict) else []
        repositories: list[RepositoryCandidate] = []
        for item in items[:limit]:
            if not isinstance(item, dict):
                continue
            try:
                repositories.append(
                    self._build_repository(item, inherited_provenance=provenance)
                )
            except FetchError:
                continue
        return repositories

    def _build_repository(
        self,
        payload: dict[str, object],
        *,
        inherited_provenance: list,
    ) -> RepositoryCandidate:
        provenance = list(inherited_provenance)
        full_name = clean_text(str(payload.get("full_name", "")))
        repo = self.fetch_json(f"{self._API_ROOT}/repos/{full_name}", provenance)
        repo_payload = repo if isinstance(repo, dict) else {}
        releases_payload = self.fetch_json(
            f"{self._API_ROOT}/repos/{full_name}/releases?per_page=30",
            provenance,
        )
        languages_payload = self.fetch_json(
            f"{self._API_ROOT}/repos/{full_name}/languages",
            provenance,
        )
        file_paths = self._fetch_file_paths(
            full_name=full_name,
            default_branch=clean_text(str(repo_payload.get("default_branch", "main"))),
            provenance=provenance,
        )
        owner = repo_payload.get("owner", {})
        license_payload = repo_payload.get("license") or {}
        return RepositoryCandidate(
            repository_id=slugify(full_name),
            provider=self.name,
            owner=clean_text(str(owner.get("login", ""))) if isinstance(owner, dict) else "",
            name=clean_text(str(repo_payload.get("name", full_name.rsplit("/", 1)[-1]))),
            full_name=full_name,
            html_url=clean_text(str(repo_payload.get("html_url", ""))),
            clone_url=clean_text(str(repo_payload.get("clone_url", ""))),
            default_branch=clean_text(str(repo_payload.get("default_branch", "main"))),
            description=clean_text(str(repo_payload.get("description", ""))),
            topics=[
                clean_text(str(item))
                for item in repo_payload.get("topics", [])
                if clean_text(str(item))
            ],
            license=(
                clean_text(str(license_payload.get("spdx_id", "")))
                if isinstance(license_payload, dict)
                else ""
            ),
            stars=int(repo_payload.get("stargazers_count", 0)),
            forks=int(repo_payload.get("forks_count", 0)),
            open_issues=int(repo_payload.get("open_issues_count", 0)),
            languages=(
                {str(key): int(value) for key, value in languages_payload.items()}
                if isinstance(languages_payload, dict)
                else {}
            ),
            releases=self._build_releases(releases_payload),
            file_paths=file_paths,
            archived=bool(repo_payload.get("archived", False)),
            fork=bool(repo_payload.get("fork", False)),
            template=bool(repo_payload.get("is_template", False)),
            homepage=clean_text(str(repo_payload.get("homepage", ""))),
            provenance=provenance,
        )

    def _fetch_file_paths(
        self,
        *,
        full_name: str,
        default_branch: str,
        provenance: list,
    ) -> list[str]:
        tree_url = (
            f"{self._API_ROOT}/repos/{full_name}/git/trees/"
            f"{quote(default_branch, safe='')}?recursive=1"
        )
        try:
            payload = self.fetch_json(tree_url, provenance)
        except FetchError:
            return []
        items = payload.get("tree", []) if isinstance(payload, dict) else []
        return [
            clean_text(str(item.get("path", "")))
            for item in items
            if isinstance(item, dict)
            and item.get("type") == "blob"
            and clean_text(str(item.get("path", "")))
        ]

    @staticmethod
    def _build_releases(payload: object) -> list[ReleaseRecord]:
        if not isinstance(payload, list):
            return []
        releases: list[ReleaseRecord] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            tag_name = clean_text(str(item.get("tag_name", "")))
            releases.append(
                ReleaseRecord(
                    tag_name=tag_name,
                    title=clean_text(str(item.get("name", "") or tag_name)),
                    published_at=clean_text(str(item.get("published_at", ""))),
                    html_url=clean_text(str(item.get("html_url", ""))),
                    archive_url=clean_text(
                        str(
                            item.get("tarball_url", "")
                            or item.get("zipball_url", "")
                            or (
                                f"https://github.com/{item.get('full_name', '')}/"
                                f"archive/refs/tags/{tag_name}.tar.gz"
                            )
                        )
                    ),
                    body=str(item.get("body", "") or "").replace("\r\n", "\n").replace("\r", "\n"),
                    draft=bool(item.get("draft", False)),
                    prerelease=bool(item.get("prerelease", False)),
                )
            )
        return sorted(releases, key=lambda item: item.published_at)


PROVIDER_TYPES = {
    "github": GitHubRepositoryProvider,
}
