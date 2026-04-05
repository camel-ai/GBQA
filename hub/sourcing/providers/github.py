"""GitHub provider adapter."""

from __future__ import annotations

from typing import Any, Dict, List
from urllib.parse import quote

from ..models import CandidateGame, CapabilityMatrix, PatchRecord, VersionRecord
from ..utils import clean_text, extract_version, has_fix_language, slugify, version_sort_key
from .base import ProviderAdapter


class GitHubProvider(ProviderAdapter):
    """Discover open-source games from GitHub repositories."""

    name = "github"
    _API_ROOT = "https://api.github.com"

    def default_headers(self) -> Dict[str, str]:
        headers = super().default_headers()
        token = self.env("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        headers["Accept"] = "application/vnd.github+json"
        return headers

    def discover(self, limit: int | None = None) -> List[CandidateGame]:
        count = limit or self.config.limit
        query = quote(self.config.github_query, safe="")
        search_url = (
            f"{self._API_ROOT}/search/repositories?q={query}"
            f"&sort=updated&order=desc&per_page={count}"
        )
        provenance: List = []
        data = self.fetch_json(search_url, provenance)
        items = data.get("items", [])
        candidates: List[CandidateGame] = []
        for item in items[:count]:
            candidates.append(self._build_candidate(item, provenance))
        return candidates

    def _build_candidate(
        self,
        payload: Dict[str, Any],
        inherited_provenance: List,
    ) -> CandidateGame:
        provenance = list(inherited_provenance)
        full_name = clean_text(payload.get("full_name", ""))
        releases = self.fetch_json(
            f"{self._API_ROOT}/repos/{full_name}/releases?per_page=20",
            provenance,
        )
        tags = self.fetch_json(
            f"{self._API_ROOT}/repos/{full_name}/tags?per_page=20",
            provenance,
        )

        release_items = releases if isinstance(releases, list) else []
        tag_items = tags if isinstance(tags, list) else []
        versions = self._build_versions(payload, release_items, tag_items)
        patches = self._build_patches(release_items)
        artifact_urls = [item.artifact_url for item in versions if item.artifact_url]
        runtime_kind = self._detect_runtime(payload, artifact_urls)
        capabilities = CapabilityMatrix(
            is_free=True,
            has_public_source=True,
            has_historical_builds=len(versions) >= 2,
            has_version_trail=len(versions) >= 2,
            has_patch_notes=bool(patches),
            has_official_patch_notes=bool(patches),
            runnable_locally=True,
            blocks_archival_replay=False,
            evidence={
                "stars": str(payload.get("stargazers_count", 0)),
                "repo": str(payload.get("html_url", "")),
            },
        )
        return CandidateGame(
            game_id=slugify(clean_text(payload.get("name", full_name))),
            title=clean_text(payload.get("name", full_name)),
            provider=self.name,
            provider_id=str(payload.get("id", full_name)),
            slug=slugify(clean_text(payload.get("name", full_name))),
            summary=clean_text(payload.get("description", "")),
            homepage_url=clean_text(payload.get("homepage", "") or payload.get("html_url", "")),
            source_repo_url=clean_text(payload.get("html_url", "")),
            license=clean_text(
                (payload.get("license") or {}).get("spdx_id", "")
                if isinstance(payload.get("license"), dict)
                else ""
            ),
            runtime_kind=runtime_kind,
            tags=[
                clean_text(topic)
                for topic in payload.get("topics", [])
                if clean_text(str(topic))
            ],
            versions=versions,
            patches=patches,
            capabilities=capabilities,
            artifact_urls=artifact_urls,
            patch_notes_url=patches[0].notes_url if patches else "",
            provenance=provenance,
            extra={
                "full_name": full_name,
                "stars": payload.get("stargazers_count", 0),
                "watchers": payload.get("watchers_count", 0),
            },
        )

    def _build_versions(
        self,
        repo: Dict[str, Any],
        releases: List[Dict[str, Any]],
        tags: List[Dict[str, Any]],
    ) -> List[VersionRecord]:
        versions: List[VersionRecord] = []
        seen = set()
        for release in releases:
            version = extract_version(
                clean_text(release.get("tag_name", "") or release.get("name", ""))
            )
            if not version or version in seen:
                continue
            asset_url = ""
            assets = release.get("assets", [])
            if isinstance(assets, list) and assets:
                asset_url = clean_text(
                    assets[0].get("browser_download_url", "")
                    if isinstance(assets[0], dict)
                    else ""
                )
            artifact_url = asset_url or clean_text(
                release.get("zipball_url", "") or release.get("tarball_url", "")
            )
            versions.append(
                VersionRecord(
                    version=version,
                    published_at=clean_text(release.get("published_at", "")),
                    artifact_url=artifact_url,
                    artifact_kind="release_asset" if asset_url else "source_archive",
                    notes_url=clean_text(release.get("html_url", "")),
                    source_url=clean_text(repo.get("html_url", "")),
                    accessible=bool(artifact_url),
                )
            )
            seen.add(version)
        for tag in tags:
            version = extract_version(clean_text(tag.get("name", "")))
            if not version or version in seen:
                continue
            archive_url = clean_text(
                (tag.get("zipball_url") or "")
                or f"{clean_text(repo.get('html_url', ''))}/archive/refs/tags/{tag.get('name', '')}.zip"
            )
            versions.append(
                VersionRecord(
                    version=version,
                    published_at="",
                    artifact_url=archive_url,
                    artifact_kind="tag_archive",
                    notes_url="",
                    source_url=clean_text(repo.get("html_url", "")),
                    accessible=bool(archive_url),
                )
            )
            seen.add(version)
        return sorted(versions, key=lambda item: version_sort_key(item.version))

    def _build_patches(self, releases: List[Dict[str, Any]]) -> List[PatchRecord]:
        patches: List[PatchRecord] = []
        for release in releases:
            body = clean_text(release.get("body", ""))
            if not body or not has_fix_language(body):
                continue
            version = extract_version(
                clean_text(release.get("tag_name", "") or release.get("name", ""))
            )
            patches.append(
                PatchRecord(
                    patch_id=slugify(
                        f"github-{release.get('tag_name', '') or release.get('name', '')}"
                    ),
                    version=version,
                    title=clean_text(release.get("name", "") or release.get("tag_name", "")),
                    published_at=clean_text(release.get("published_at", "")),
                    notes_url=clean_text(release.get("html_url", "")),
                    body=body,
                    is_official=True,
                )
            )
        return sorted(patches, key=lambda item: item.published_at, reverse=True)

    @staticmethod
    def _detect_runtime(payload: Dict[str, Any], artifact_urls: List[str]) -> str:
        topics = " ".join(str(item).lower() for item in payload.get("topics", []))
        if any(tag in topics for tag in ("html5", "browser", "phaser", "webgl", "threejs")):
            return "web"
        if any(url.lower().endswith(ext) for url in artifact_urls for ext in (".exe", ".msi", ".dmg")):
            return "native_desktop"
        if any(tag in topics for tag in ("unity", "godot", "unreal", "desktop")):
            return "native_desktop"
        return "source_project"
