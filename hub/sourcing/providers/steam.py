"""Steam provider adapter."""

from __future__ import annotations

from typing import Any, Dict, List
from urllib.parse import quote
import re

from ..models import CandidateGame, CapabilityMatrix, PatchRecord, VersionRecord
from ..utils import (
    choose_first_url,
    clean_text,
    epoch_to_iso,
    extract_meta_content,
    extract_version,
    find_link_urls,
    has_fix_language,
    slugify,
    strip_html,
)
from .base import ProviderAdapter, ProviderError


class SteamProvider(ProviderAdapter):
    """Discover candidate games from Steam metadata and announcements."""

    name = "steam"
    _APP_LIST_URL = "https://partner.steam-api.com/IStoreService/GetAppList/v1/"
    _NEWS_URL = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"

    def discover(self, limit: int | None = None) -> List[CandidateGame]:
        key = self.env("STEAM_WEB_API_KEY")
        if not key:
            raise ProviderError("STEAM_WEB_API_KEY is required for Steam discovery")
        count = limit or self.config.limit
        provenance = []
        app_list = self.fetch_json(
            f"{self._APP_LIST_URL}?key={quote(key)}&max_results={count}&include_games=true",
            provenance,
        )
        apps = ((app_list.get("response") or {}).get("apps") or [])[:count]
        candidates: List[CandidateGame] = []
        for app in apps:
            candidates.append(self._build_candidate(app, provenance))
        return candidates

    def default_headers(self) -> Dict[str, str]:
        return {"Accept": "application/json,text/html;q=0.9,*/*;q=0.8"}

    def _build_candidate(
        self,
        payload: Dict[str, Any],
        inherited_provenance: List,
    ) -> CandidateGame:
        provenance = list(inherited_provenance)
        app_id = str(payload.get("appid", ""))
        name = clean_text(payload.get("name", ""))
        store_url = (
            f"https://store.steampowered.com/app/{app_id}/?l={self.config.steam_store_language}"
        )
        page_html = self.fetch_text(store_url, provenance)
        page_text = strip_html(page_html)
        news = self.fetch_json(
            f"{self._NEWS_URL}?appid={app_id}&count=10&maxlength=5000&format=json",
            provenance,
        )
        source_repo_url = choose_first_url(
            page_html, ["github.com", "gitlab.com", "codeberg.org"]
        )
        archive_links = self._extract_archive_links(page_html)
        patches = self._build_patches(news)
        versions = self._derive_versions(patches, archive_links, source_repo_url)
        capabilities = CapabilityMatrix(
            is_free="free to play" in page_text.lower() or "free" in page_text.lower(),
            has_public_source=bool(source_repo_url),
            has_historical_builds=bool(source_repo_url) or len(archive_links) >= 2,
            has_version_trail=len(versions) >= 2 or len(patches) >= 2,
            has_patch_notes=bool(patches),
            has_official_patch_notes=bool(patches),
            runnable_locally=bool(source_repo_url) or bool(archive_links),
            blocks_archival_replay=self._has_blockers(page_text),
            evidence={"steam_app_id": app_id, "news_items": str(len(patches))},
        )
        artifact_urls = archive_links[:] or ([source_repo_url] if source_repo_url else [])
        return CandidateGame(
            game_id=slugify(name or app_id),
            title=name,
            provider=self.name,
            provider_id=app_id,
            slug=slugify(name or app_id),
            summary=extract_meta_content(page_html, "og:description") or clean_text(page_text[:240]),
            homepage_url=store_url,
            source_repo_url=source_repo_url,
            license=self._extract_license(page_text),
            runtime_kind="native_desktop",
            tags=self._extract_tags(page_text),
            versions=versions,
            patches=patches,
            capabilities=capabilities,
            artifact_urls=artifact_urls,
            patch_notes_url=patches[0].notes_url if patches else "",
            provenance=provenance,
        )

    @staticmethod
    def _extract_archive_links(page_html: str) -> List[str]:
        links = []
        for href in find_link_urls(page_html):
            lowered = href.lower()
            if "archive.org" in lowered or lowered.endswith((".zip", ".rar", ".7z")):
                links.append(href)
        unique: List[str] = []
        seen = set()
        for link in links:
            if link not in seen:
                seen.add(link)
                unique.append(link)
        return unique

    @staticmethod
    def _build_patches(news_payload: Dict[str, Any]) -> List[PatchRecord]:
        items = ((news_payload.get("appnews") or {}).get("newsitems") or [])
        patches: List[PatchRecord] = []
        for item in items:
            title = clean_text(item.get("title", ""))
            body = strip_html(clean_text(item.get("contents", "")))
            if not has_fix_language(f"{title} {body}"):
                continue
            version = extract_version(f"{title} {body}")
            notes_url = clean_text(item.get("url", ""))
            patches.append(
                PatchRecord(
                    patch_id=slugify(f"steam-{version or title}"),
                    version=version,
                    title=title,
                    published_at=epoch_to_iso(item.get("date")),
                    notes_url=notes_url,
                    body=body,
                    is_official=True,
                )
            )
        return patches

    @staticmethod
    def _derive_versions(
        patches: List[PatchRecord],
        archive_links: List[str],
        source_repo_url: str,
    ) -> List[VersionRecord]:
        versions: List[VersionRecord] = []
        for index, patch in enumerate(reversed(patches)):
            if not patch.version:
                continue
            if archive_links:
                artifact_url = archive_links[min(index, len(archive_links) - 1)]
                artifact_kind = "developer_archive"
            elif source_repo_url:
                artifact_url = source_repo_url
                artifact_kind = "source_repo"
            else:
                continue
            versions.append(
                VersionRecord(
                    version=patch.version,
                    published_at=patch.published_at,
                    artifact_url=artifact_url,
                    artifact_kind=artifact_kind,
                    notes_url=patch.notes_url,
                    source_url=source_repo_url,
                    accessible=True,
                )
            )
        return versions

    @staticmethod
    def _has_blockers(page_text: str) -> bool:
        lowered = page_text.lower()
        return any(
            token in lowered
            for token in (
                "requires 3rd-party account",
                "anti-cheat",
                "always online",
                "cloud gaming",
                "subscription required",
                "launcher required",
            )
        )

    @staticmethod
    def _extract_license(page_text: str) -> str:
        match = re.search(r"license[:\s]+([a-z0-9\-.+ ]{2,32})", page_text, re.IGNORECASE)
        return clean_text(match.group(1)) if match else ""

    @staticmethod
    def _extract_tags(page_text: str) -> List[str]:
        tags = []
        lowered = page_text.lower()
        for tag in ("multiplayer", "singleplayer", "strategy", "puzzle", "roguelike", "simulation"):
            if tag in lowered:
                tags.append(tag)
        return tags
