"""itch.io provider adapter."""

from __future__ import annotations

from typing import List
from urllib.parse import urljoin
import re
import xml.etree.ElementTree as ET

from ..models import CandidateGame, CapabilityMatrix, PatchRecord, VersionRecord
from ..utils import (
    choose_first_url,
    clean_text,
    extract_meta_content,
    extract_version,
    find_link_urls,
    has_fix_language,
    looks_non_bug_line,
    slugify,
    strip_html,
)
from .base import ProviderAdapter


class ItchProvider(ProviderAdapter):
    """Discover candidates from itch.io browse feeds and devlogs."""

    name = "itch"

    def discover(self, limit: int | None = None) -> List[CandidateGame]:
        count = limit or self.config.limit
        provenance = []
        feed_xml = self.fetch_text(self.config.itch_browse_feed_url, provenance)
        root = ET.fromstring(feed_xml)
        items = root.findall(".//item")
        candidates: List[CandidateGame] = []
        for item in items[:count]:
            link = clean_text(item.findtext("link", ""))
            if not link:
                continue
            candidates.append(
                self._build_candidate(
                    title=clean_text(item.findtext("title", "")),
                    page_url=link,
                    inherited_provenance=provenance,
                )
            )
        return candidates

    def default_headers(self) -> dict[str, str]:
        return {"Accept": "text/html,application/xml;q=0.9,*/*;q=0.8"}

    def _build_candidate(
        self,
        *,
        title: str,
        page_url: str,
        inherited_provenance: List,
    ) -> CandidateGame:
        provenance = list(inherited_provenance)
        page_html = self.fetch_text(page_url, provenance)
        page_text = strip_html(page_html)
        homepage_url = page_url
        source_repo_url = choose_first_url(
            page_html, ["github.com", "gitlab.com", "codeberg.org"]
        )
        archive_links = self._extract_archive_links(page_html, page_url)
        patches = self._extract_devlogs(page_html, page_url, provenance)
        versions = self._derive_versions(patches, archive_links, source_repo_url)
        runtime_kind = "web" if "html5" in page_text.lower() else "native_desktop"
        capabilities = CapabilityMatrix(
            is_free=self._is_free(page_text),
            has_public_source=bool(source_repo_url),
            has_historical_builds=bool(source_repo_url) or len(archive_links) >= 2,
            has_version_trail=len(versions) >= 2 or len(patches) >= 2,
            has_patch_notes=bool(patches),
            has_official_patch_notes=bool(patches),
            runnable_locally=bool(source_repo_url) or bool(archive_links),
            blocks_archival_replay=self._has_blockers(page_text),
            evidence={
                "page": page_url,
                "devlogs": str(len(patches)),
                "downloads": str(len(archive_links)),
            },
        )
        return CandidateGame(
            game_id=slugify(title),
            title=title or extract_meta_content(page_html, "og:title"),
            provider=self.name,
            provider_id=page_url,
            slug=slugify(title or page_url),
            summary=extract_meta_content(page_html, "og:description") or clean_text(page_text[:240]),
            homepage_url=homepage_url,
            source_repo_url=source_repo_url,
            license=self._extract_license(page_text),
            runtime_kind=runtime_kind,
            tags=self._extract_tags(page_text),
            versions=versions,
            patches=patches,
            capabilities=capabilities,
            artifact_urls=archive_links[:],
            patch_notes_url=patches[0].notes_url if patches else "",
            provenance=provenance,
        )

    @staticmethod
    def _extract_archive_links(page_html: str, page_url: str) -> List[str]:
        links = []
        for href in find_link_urls(page_html):
            absolute = urljoin(page_url, href)
            lowered = absolute.lower()
            if any(token in lowered for token in ("download", "upload", "archive.org")):
                links.append(absolute)
            elif lowered.endswith((".zip", ".rar", ".7z", ".tar.gz")):
                links.append(absolute)
        unique: List[str] = []
        seen = set()
        for link in links:
            if link not in seen:
                seen.add(link)
                unique.append(link)
        return unique

    def _extract_devlogs(
        self,
        page_html: str,
        page_url: str,
        provenance: List,
    ) -> List[PatchRecord]:
        patch_links: List[str] = []
        for href in find_link_urls(page_html):
            absolute = urljoin(page_url, href)
            lowered = absolute.lower()
            if "/devlog/" in lowered or any(
                token in lowered for token in ("update", "patch", "hotfix", "changelog")
            ):
                patch_links.append(absolute)
        patches: List[PatchRecord] = []
        seen = set()
        for link in patch_links[:10]:
            if link in seen:
                continue
            seen.add(link)
            html_text = self.fetch_text(link, provenance)
            title = extract_meta_content(html_text, "og:title") or self._extract_title(html_text)
            body = strip_html(html_text)
            if not has_fix_language(body):
                continue
            if looks_non_bug_line(clean_text(title)) and not has_fix_language(title):
                continue
            version = extract_version(title or body)
            patches.append(
                PatchRecord(
                    patch_id=slugify(f"itch-{version or title}"),
                    version=version,
                    title=clean_text(title),
                    published_at="",
                    notes_url=link,
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
            artifact_url = archive_links[min(index, len(archive_links) - 1)] if archive_links else source_repo_url
            if not artifact_url:
                continue
            versions.append(
                VersionRecord(
                    version=patch.version,
                    published_at=patch.published_at,
                    artifact_url=artifact_url,
                    artifact_kind="upload_archive" if archive_links else "source_repo",
                    notes_url=patch.notes_url,
                    source_url=source_repo_url,
                    accessible=True,
                )
            )
        if len(versions) == 1 and source_repo_url:
            versions.insert(
                0,
                VersionRecord(
                    version=f"{versions[0].version}-baseline",
                    published_at="",
                    artifact_url=source_repo_url,
                    artifact_kind="source_repo",
                    source_url=source_repo_url,
                    accessible=True,
                ),
            )
        return versions

    @staticmethod
    def _extract_title(html_text: str) -> str:
        match = re.search(r"<title>(.*?)</title>", html_text, re.IGNORECASE | re.DOTALL)
        return clean_text(match.group(1)) if match else ""

    @staticmethod
    def _is_free(page_text: str) -> bool:
        lowered = page_text.lower()
        return "free" in lowered or "name your own price" in lowered or "download now" in lowered

    @staticmethod
    def _has_blockers(page_text: str) -> bool:
        lowered = page_text.lower()
        return any(
            token in lowered
            for token in ("requires steam", "requires account", "cloud only", "launcher required")
        )

    @staticmethod
    def _extract_license(page_text: str) -> str:
        match = re.search(r"license[:\s]+([a-z0-9\-.+ ]{2,32})", page_text, re.IGNORECASE)
        return clean_text(match.group(1)) if match else ""

    @staticmethod
    def _extract_tags(page_text: str) -> List[str]:
        tags = []
        lowered = page_text.lower()
        for tag in ("html5", "unity", "godot", "platformer", "puzzle", "strategy", "roguelike"):
            if tag in lowered:
                tags.append(tag)
        return tags
