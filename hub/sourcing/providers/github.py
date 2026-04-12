"""GitHub provider for source-code-available software projects."""

from __future__ import annotations

from urllib.parse import quote

from ..camel_github import CamelGithubToolkitAdapter
from ..fetcher import FetchError
from ..models import (
    CapabilityMatrix,
    EngagementMetrics,
    ReleaseRecord,
    SoftwareProjectCandidate,
)
from ..utils import (
    build_dedupe_key,
    clean_text,
    days_since,
    extract_version,
    has_fix_language,
    infer_architecture,
    release_cadence_days,
    slugify,
)
from .base import ProviderAdapter


class GithubSoftwareProjectProvider(ProviderAdapter):
    """Discover GitHub software projects with release-based bug evidence."""

    name = "github"
    _API_ROOT = "https://api.github.com"

    def __init__(self, **kwargs) -> None:
        """Initialize the GitHub provider and optional CAMEL adapter."""
        super().__init__(**kwargs)
        self._camel_toolkit = CamelGithubToolkitAdapter.create(
            self.env("GITHUB_TOKEN") or self.env("GITHUB_ACCESS_TOKEN")
        )

    def default_headers(self) -> dict[str, str]:
        """Return GitHub-specific HTTP headers."""
        headers = super().default_headers()
        token = self.env("GITHUB_TOKEN") or self.env("GITHUB_ACCESS_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        headers["Accept"] = "application/vnd.github+json"
        return headers

    def discover(
        self,
        limit: int | None = None,
        *,
        page: int = 1,
    ) -> list[SoftwareProjectCandidate]:
        """Discover source-code-available software projects from GitHub."""
        count = limit or self.config.limit
        query = quote(self.config.github_query, safe="")
        search_url = (
            f"{self._API_ROOT}/search/repositories?q={query}"
            f"&sort={self.config.github_search_sort}"
            f"&order=desc&per_page={count}&page={page}"
        )
        provenance = []
        data = self.fetch_json(search_url, provenance)
        items = data.get("items", []) if isinstance(data, dict) else []
        candidates: list[SoftwareProjectCandidate] = []
        for item in items[:count]:
            candidates.append(self._build_candidate(item, provenance))
        return candidates

    def _build_candidate(
        self,
        payload: dict[str, object],
        inherited_provenance: list,
    ) -> SoftwareProjectCandidate:
        """Build one normalized software-project candidate."""
        provenance = list(inherited_provenance)
        repo_full_name = clean_text(str(payload.get("full_name", "")))
        repo_data = self.fetch_json(f"{self._API_ROOT}/repos/{repo_full_name}", provenance)
        repo = repo_data if isinstance(repo_data, dict) else {}
        releases_data = self.fetch_json(
            f"{self._API_ROOT}/repos/{repo_full_name}/releases?per_page=30",
            provenance,
        )
        tags_data = self.fetch_json(
            f"{self._API_ROOT}/repos/{repo_full_name}/tags?per_page=30",
            provenance,
        )
        languages_data = self.fetch_json(
            f"{self._API_ROOT}/repos/{repo_full_name}/languages",
            provenance,
        )
        contributors_data, contributors_metadata_complete = self._fetch_contributors(
            repo_full_name=repo_full_name,
            provenance=provenance,
        )
        issues_data, issues_metadata_complete = self._fetch_search_issue_totals(
            repo_full_name=repo_full_name,
            search_kind="issue",
            provenance=provenance,
        )
        pulls_data, pulls_metadata_complete = self._fetch_search_issue_totals(
            repo_full_name=repo_full_name,
            search_kind="pr",
            provenance=provenance,
        )

        releases = self._build_releases(releases_data)
        tags = tags_data if isinstance(tags_data, list) else []
        languages = (
            {str(key): int(value) for key, value in languages_data.items()}
            if isinstance(languages_data, dict)
            else {}
        )
        file_paths = self._fetch_file_paths(
            repo_full_name=repo_full_name,
            default_branch=clean_text(str(repo.get("default_branch", "main"))),
            provenance=provenance,
        )
        architecture = infer_architecture(
            file_paths=file_paths,
            languages=languages,
            topics=[str(item) for item in repo.get("topics", [])],
        )
        engagement = self._build_engagement(
            repo=repo,
            releases=releases,
            tags=tags,
            contributors=contributors_data if isinstance(contributors_data, list) else [],
            issues=issues_data if isinstance(issues_data, dict) else {},
            pulls=pulls_data if isinstance(pulls_data, dict) else {},
        )
        capabilities = CapabilityMatrix(
            has_public_source=bool(repo_full_name),
            has_release_history=len(releases) >= 2 or len(tags) >= 2,
            has_fix_releases=any(item.has_bug_fix_evidence for item in releases),
            has_recoverable_baseline=False,
            has_frontend=bool(architecture["has_frontend"]),
            has_backend=bool(architecture["has_backend"]),
            has_database=bool(architecture["has_database"]),
            interaction_mode=str(architecture["interaction_mode"]),
            evidence={
                "architecture_source": (
                    "camel_github_toolkit"
                    if self._camel_toolkit.is_available
                    else "github_tree_api"
                ),
                **{
                    str(key): str(value)
                    for key, value in dict(architecture["evidence"]).items()
                },
            },
        )
        github_url = clean_text(str(repo.get("html_url", "")))
        project_name = clean_text(str(repo.get("name", repo_full_name)))
        return SoftwareProjectCandidate(
            environment_id=slugify(repo_full_name),
            project_name=project_name,
            provider=self.name,
            repo_full_name=repo_full_name,
            github_url=github_url,
            owner=clean_text(str((repo.get("owner") or {}).get("login", ""))),
            default_branch=clean_text(str(repo.get("default_branch", "main"))),
            about=clean_text(str(repo.get("description", ""))),
            topics=[
                clean_text(str(item))
                for item in repo.get("topics", [])
                if clean_text(str(item))
            ],
            license=clean_text(
                str((repo.get("license") or {}).get("spdx_id", ""))
                if isinstance(repo.get("license"), dict)
                else ""
            ),
            clone_url=clean_text(str(repo.get("clone_url", ""))),
            languages=languages,
            capabilities=capabilities,
            engagement=engagement,
            releases=releases,
            artifact_urls=[
                url
                for release in releases
                for url in release.artifact_urls
            ],
            release_notes_url=releases[-1].notes_url if releases else "",
            provenance=provenance,
            dedupe_key=build_dedupe_key(repo_full_name, ""),
            extra={
                "tag_count": len(tags),
                "homepage": clean_text(str(repo.get("homepage", ""))),
                "camel_github_toolkit_available": self._camel_toolkit.is_available,
                "camel_github_toolkit_reason": self._camel_toolkit.availability_reason,
                "contributors_metadata_complete": contributors_metadata_complete,
                "issues_metadata_complete": issues_metadata_complete,
                "pulls_metadata_complete": pulls_metadata_complete,
            },
        )

    def _build_releases(self, payload: object) -> list[ReleaseRecord]:
        """Convert GitHub releases into normalized release records."""
        if not isinstance(payload, list):
            return []
        releases: list[ReleaseRecord] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            asset_urls = []
            assets = item.get("assets", [])
            if isinstance(assets, list):
                for asset in assets:
                    if isinstance(asset, dict):
                        url = clean_text(str(asset.get("browser_download_url", "")))
                        if url:
                            asset_urls.append(url)
            if not asset_urls:
                for key in ("zipball_url", "tarball_url"):
                    url = clean_text(str(item.get(key, "")))
                    if url:
                        asset_urls.append(url)
            body = str(item.get("body", "") or "").replace("\r\n", "\n").replace("\r", "\n")
            releases.append(
                ReleaseRecord(
                    release_id=clean_text(str(item.get("tag_name", "") or item.get("name", ""))),
                    tag_name=clean_text(str(item.get("tag_name", ""))),
                    title=clean_text(str(item.get("name", "") or item.get("tag_name", ""))),
                    published_at=clean_text(str(item.get("published_at", ""))),
                    notes_url=clean_text(str(item.get("html_url", ""))),
                    body=body,
                    artifact_urls=asset_urls,
                    has_bug_fix_evidence=has_fix_language(body),
                )
            )
        return sorted(releases, key=lambda item: item.published_at)

    def _build_engagement(
        self,
        *,
        repo: dict[str, object],
        releases: list[ReleaseRecord],
        tags: list[object],
        contributors: list[object],
        issues: dict[str, object],
        pulls: dict[str, object],
    ) -> EngagementMetrics:
        """Build engagement and workability metrics."""
        stars = int(repo.get("stargazers_count", 0))
        forks = int(repo.get("forks_count", 0))
        contributor_count = len(contributors)
        issue_count = int(issues.get("total_count", 0))
        pull_request_count = int(pulls.get("total_count", 0))
        days_since_last_push = days_since(clean_text(str(repo.get("pushed_at", ""))))
        cadence = release_cadence_days([item.published_at for item in releases])
        workability_score = self._workability_score(
            stars=stars,
            contributor_count=contributor_count,
            issue_count=issue_count,
            pull_request_count=pull_request_count,
            days_since_last_push=days_since_last_push,
            release_count=len(releases),
        )
        return EngagementMetrics(
            stars=stars,
            forks=forks,
            issue_count=issue_count,
            pull_request_count=pull_request_count,
            contributor_count=contributor_count,
            release_count=len(releases),
            tag_count=len(tags),
            open_issue_count=int(repo.get("open_issues_count", 0)),
            days_since_last_push=days_since_last_push,
            release_cadence_days=cadence,
            workability_score=workability_score,
        )

    @staticmethod
    def _workability_score(
        *,
        stars: int,
        contributor_count: int,
        issue_count: int,
        pull_request_count: int,
        days_since_last_push: int | None,
        release_count: int,
    ) -> float:
        """Estimate whether one repository looks active and workable."""
        star_score = min(stars / 200.0, 1.0) * 30.0
        contributor_score = min(contributor_count / 15.0, 1.0) * 20.0
        issue_score = min(issue_count / 100.0, 1.0) * 15.0
        pr_score = min(pull_request_count / 50.0, 1.0) * 15.0
        release_score = min(release_count / 10.0, 1.0) * 10.0
        recency_score = 0.0
        if days_since_last_push is not None:
            if days_since_last_push <= 90:
                recency_score = 10.0
            elif days_since_last_push <= 365:
                recency_score = 6.0
            elif days_since_last_push <= 730:
                recency_score = 2.0
        return round(
            star_score
            + contributor_score
            + issue_score
            + pr_score
            + release_score
            + recency_score,
            2,
        )

    def _fetch_file_paths(
        self,
        *,
        repo_full_name: str,
        default_branch: str,
        provenance: list,
    ) -> list[str]:
        """Return repository file paths using CAMEL when available, else REST."""
        if self._camel_toolkit.is_available:
            file_paths = self._camel_toolkit.get_all_file_paths(repo_full_name)
            if file_paths:
                return file_paths
        tree_url = (
            f"{self._API_ROOT}/repos/{repo_full_name}/git/trees/"
            f"{quote(default_branch, safe='')}?recursive=1"
        )
        tree_payload = self.fetch_json(tree_url, provenance)
        if not isinstance(tree_payload, dict):
            return []
        items = tree_payload.get("tree", [])
        if not isinstance(items, list):
            return []
        return [
            clean_text(str(item.get("path", "")))
            for item in items
            if isinstance(item, dict)
            and item.get("type") == "blob"
            and clean_text(str(item.get("path", "")))
        ]

    def _fetch_contributors(
        self,
        *,
        repo_full_name: str,
        provenance: list,
    ) -> tuple[list[object], bool]:
        """Fetch contributors, tolerating GitHub's large-history contributor overflow."""
        url = (
            f"{self._API_ROOT}/repos/{repo_full_name}/contributors?per_page=30&anon=1"
        )
        try:
            payload = self.fetch_json(url, provenance)
        except FetchError as exc:
            if self._is_nonfatal_contributors_error(exc):
                return [], False
            raise
        if isinstance(payload, list):
            return payload, True
        return [], True

    def _fetch_search_issue_totals(
        self,
        *,
        repo_full_name: str,
        search_kind: str,
        provenance: list,
    ) -> tuple[dict[str, object], bool]:
        """Fetch issue or pull-request totals, tolerating transient network failures."""
        url = (
            f"{self._API_ROOT}/search/issues?"
            f"q={quote(f'repo:{repo_full_name} is:{search_kind}', safe='')}"
        )
        try:
            payload = self.fetch_json(url, provenance)
        except FetchError as exc:
            if self._is_nonfatal_search_metadata_error(exc):
                return {"total_count": 0}, False
            raise
        if isinstance(payload, dict):
            return payload, True
        return {"total_count": 0}, True

    @staticmethod
    def _is_nonfatal_contributors_error(exc: FetchError) -> bool:
        """Treat GitHub contributor-list overflow as non-fatal metadata loss."""
        if exc.status_code != 403:
            return False
        body = clean_text(exc.body).lower()
        return (
            "contributor list is too large" in body
            or "too large to list contributors" in body
        )

    @staticmethod
    def _is_nonfatal_search_metadata_error(exc: FetchError) -> bool:
        """Treat transient transport failures on supplemental search metadata as non-fatal."""
        return exc.status_code is None
