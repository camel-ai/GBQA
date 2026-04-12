"""Automatic release-note-to-ground-truth generation for software projects."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from .models import GroundTruthBundle, ReleasePair, SoftwareProjectCandidate
from .structured_outputs import TaxonomyPredictionBatch
from .utils import (
    classify_release_note_line,
    clean_text,
    find_urls,
    has_fix_language,
    looks_non_bug_line,
    split_patch_lines,
)


@dataclass(slots=True)
class PatchNoteLlmClient:
    """Optional OpenAI-compatible helper for reproduction and taxonomy metadata."""

    api_key: str
    model: str
    base_url: str = "https://api.openai.com/v1"
    timeout: int = 20

    @classmethod
    def from_env(cls) -> Optional["PatchNoteLlmClient"]:
        """Build one optional client from environment variables."""
        import os

        api_key = os.getenv("OPENAI_API_KEY", "")
        model = os.getenv("OPENAI_MODEL", "")
        if not api_key or not model:
            return None
        return cls(
            api_key=api_key,
            model=model,
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )

    def synthesize_steps(
        self,
        *,
        project_name: str,
        baseline_version: str,
        issue_summary: str,
        observed_fault: str,
    ) -> Optional[List[str]]:
        """Generate minimal reproduction steps with an optional LLM call."""
        prompt = (
            "Return compact JSON with a single key `steps`, whose value is an array "
            "of 2 or 3 minimal reproduction steps for a software bug.\n"
            f"Project: {project_name}\n"
            f"Baseline version: {baseline_version}\n"
            f"Issue summary: {issue_summary}\n"
            f"Observed fault: {observed_fault}\n"
        )
        payload = self._chat_payload(
            system_message="You write concise software QA reproduction steps as JSON only.",
            user_message=prompt,
        )
        parsed = self._post_json(payload)
        if not isinstance(parsed, dict):
            return None
        steps = parsed.get("steps", [])
        if not isinstance(steps, list):
            return None
        cleaned = [clean_text(str(step)) for step in steps if clean_text(str(step))]
        return cleaned or None

    def annotate_taxonomy(
        self,
        *,
        release_summary: str,
        bug_lines: List[str],
    ) -> Dict[int, Dict[str, Any]]:
        """Generate optional taxonomy annotations for bug lines."""
        if not bug_lines:
            return {}
        prompt_lines = "\n".join(f"{index}. {line}" for index, line in enumerate(bug_lines))
        prompt = (
            "Return JSON with key `findings`, containing one item per bug line. "
            "Each item must include finding_index, primary_category, secondary_labels, "
            "context_summary, and confidence. Allowed primary categories are "
            "frontend, backend, database, safety, other.\n"
            f"Release summary: {release_summary}\n"
            f"Bug lines:\n{prompt_lines}\n"
        )
        payload = self._chat_payload(
            system_message="You classify software bug-fix statements into broad QA categories.",
            user_message=prompt,
        )
        parsed = self._post_json(payload)
        if not isinstance(parsed, dict):
            return {}
        try:
            batch = TaxonomyPredictionBatch.model_validate(parsed)
        except Exception:  # noqa: BLE001
            return {}
        return {
            item.finding_index: {
                "primary_category": item.primary_category,
                "secondary_labels": item.secondary_labels,
                "taxonomy_context": item.context_summary,
                "taxonomy_confidence": item.confidence,
                "taxonomy_source": "llm",
            }
            for item in batch.findings
        }

    def _chat_payload(self, *, system_message: str, user_message: str) -> Dict[str, Any]:
        return {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message},
            ],
        }

    def _post_json(self, payload: Dict[str, Any]) -> Dict[str, Any] | None:
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            return None
        try:
            data = json.loads(raw)
            content = data["choices"][0]["message"]["content"]
            return _extract_json(content)
        except (KeyError, ValueError, TypeError):
            return None


class GroundTruthGenerator:
    """Generate bug-ground-truth bundles from release notes."""

    def __init__(self, llm_client: Optional[PatchNoteLlmClient] = None) -> None:
        self._llm_client = llm_client or PatchNoteLlmClient.from_env()

    def generate(
        self,
        candidate: SoftwareProjectCandidate,
        release_pair: ReleasePair,
    ) -> GroundTruthBundle:
        """Generate one ground-truth bundle for a selected release pair."""
        release = self._find_release(candidate, release_pair.release_id)
        if release is None:
            raise ValueError(f"release {release_pair.release_id} not found")
        bug_lines = self._extract_bug_lines(release.body)
        llm_taxonomy = (
            self._llm_client.annotate_taxonomy(
                release_summary=release.body,
                bug_lines=bug_lines,
            )
            if self._llm_client is not None
            else {}
        )
        bugs = []
        for index, line in enumerate(bug_lines, start=1):
            observed_fault = self._observed_fault(line)
            steps = self._steps(candidate, release_pair, line, observed_fault)
            taxonomy = llm_taxonomy.get(index - 1, self._deterministic_taxonomy(line))
            bugs.append(
                {
                    "id": f"{release_pair.release_id.upper()}-BUG-{index:03d}",
                    "bug_type": self._bug_type(line),
                    "difficulty": self._difficulty(line),
                    "title": self._title(line),
                    "description": f"Derived automatically from release notes: {line}",
                    "minimal_reproduction": steps,
                    "observed_fault": observed_fault,
                    "source_patch_url": self._source_patch_url(candidate, release, line),
                    "source_excerpt": line,
                    "extraction_confidence": self._confidence(line),
                    **taxonomy,
                }
            )
        return GroundTruthBundle(
            project_name=candidate.project_name,
            repo_full_name=candidate.repo_full_name,
            bug_version=release_pair.release_id,
            total_bugs=len(bugs),
            release_notes_url=release.notes_url,
            bugs=bugs,
        )

    @staticmethod
    def _find_release(
        candidate: SoftwareProjectCandidate,
        release_id: str,
    ):
        for release in candidate.releases:
            if release.release_id == release_id:
                return release
        return None

    @staticmethod
    def _extract_bug_lines(body: str) -> List[str]:
        lines = []
        active_section = "content"
        for raw_line in body.replace("\r", "\n").split("\n"):
            section_kind = classify_release_note_line(raw_line)
            if section_kind == "empty":
                continue
            if section_kind in {"bug_section", "feature_section"}:
                active_section = section_kind
                continue
            for line in split_patch_lines(raw_line):
                if not line:
                    continue
                if active_section == "feature_section":
                    continue
                if looks_non_bug_line(line):
                    continue
                if active_section == "bug_section" or has_fix_language(line):
                    lines.append(line)
        unique_lines = []
        seen_lines = set()
        for line in lines:
            normalized = clean_text(line)
            if normalized in seen_lines:
                continue
            seen_lines.add(normalized)
            unique_lines.append(normalized)
        return unique_lines or [clean_text(body)]

    def _steps(
        self,
        candidate: SoftwareProjectCandidate,
        release_pair: ReleasePair,
        line: str,
        observed_fault: str,
    ) -> List[str]:
        if self._llm_client is not None:
            generated = self._llm_client.synthesize_steps(
                project_name=candidate.project_name,
                baseline_version=release_pair.baseline_version,
                issue_summary=line,
                observed_fault=observed_fault,
            )
            if generated:
                return generated
        return [
            f"Check out {candidate.repo_full_name} at baseline version {release_pair.baseline_version}.",
            f"Exercise the code path related to: {self._title(line)}.",
            f"Observe that {observed_fault}",
        ]

    @staticmethod
    def _title(line: str) -> str:
        text = clean_text(line)
        text = re.sub(
            r"^(fixed|fix|fixes|resolved|resolve|hotfix|security fix)\s+",
            "",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"\s*\((?:#\d+|https?://[^)]+)\)\s*$", "", text, flags=re.IGNORECASE)
        return text[:120]

    @staticmethod
    def _observed_fault(line: str) -> str:
        text = clean_text(line)
        text = re.sub(
            r"^(fixed|fixes?|resolved|resolve|hotfix(ed)?|security fix)\s+",
            "",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"\s*\((?:#\d+|https?://[^)]+)\)\s*$", "", text, flags=re.IGNORECASE)
        text = clean_text(text.rstrip("."))
        if not text.lower().startswith("the"):
            text = f"The project {text[0].lower() + text[1:] if text else 'shows the patched issue.'}"
        if not text.endswith("."):
            text += "."
        return text

    @staticmethod
    def _source_patch_url(candidate: SoftwareProjectCandidate, release, line: str) -> str:
        urls = find_urls(line)
        if urls:
            return urls[0]
        pull_request_match = re.search(r"#(\d+)", line)
        if pull_request_match and candidate.github_url:
            return f"{candidate.github_url}/pull/{pull_request_match.group(1)}"
        return release.notes_url

    @staticmethod
    def _bug_type(line: str) -> str:
        lowered = clean_text(line).lower()
        if any(token in lowered for token in ("vulnerability", "security", "xss", "csrf")):
            return "safety"
        if "database" in lowered or "sql" in lowered or "migration" in lowered:
            return "data inconsistency"
        if "ui" in lowered or "render" in lowered or "button" in lowered:
            return "ui issue"
        if "crash" in lowered or "panic" in lowered or "exception" in lowered:
            return "stability"
        return "logic error"

    @staticmethod
    def _difficulty(line: str) -> str:
        lowered = clean_text(line).lower()
        if any(token in lowered for token in ("security", "database", "migration", "concurrency")):
            return "medium"
        if any(token in lowered for token in ("crash", "panic", "startup")):
            return "easy"
        return "easy"

    @staticmethod
    def _confidence(line: str) -> float:
        lowered = clean_text(line).lower()
        if "fixed" in lowered or "resolved" in lowered:
            return 0.88
        return 0.7

    @staticmethod
    def _deterministic_taxonomy(line: str) -> Dict[str, Any]:
        lowered = clean_text(line).lower()
        if any(token in lowered for token in ("xss", "csrf", "security", "vulnerability")):
            return {
                "primary_category": "safety",
                "secondary_labels": ["security"],
                "taxonomy_context": "Security or safety defect inferred from release notes.",
                "taxonomy_confidence": 0.9,
                "taxonomy_source": "deterministic",
            }
        if any(token in lowered for token in ("sql", "database", "migration", "query", "prisma")):
            return {
                "primary_category": "database",
                "secondary_labels": ["storage"],
                "taxonomy_context": "Database or persistence issue inferred from release notes.",
                "taxonomy_confidence": 0.82,
                "taxonomy_source": "deterministic",
            }
        if any(token in lowered for token in ("ui", "button", "page", "screen", "render", "layout", "css")):
            return {
                "primary_category": "frontend",
                "secondary_labels": ["ui"],
                "taxonomy_context": "Frontend presentation or interaction issue inferred from release notes.",
                "taxonomy_confidence": 0.8,
                "taxonomy_source": "deterministic",
            }
        if any(token in lowered for token in ("api", "server", "endpoint", "worker", "auth", "request", "response")):
            return {
                "primary_category": "backend",
                "secondary_labels": ["service"],
                "taxonomy_context": "Backend service issue inferred from release notes.",
                "taxonomy_confidence": 0.8,
                "taxonomy_source": "deterministic",
            }
        return {
            "primary_category": "other",
            "secondary_labels": [],
            "taxonomy_context": "No stronger deterministic category was found.",
            "taxonomy_confidence": 0.55,
            "taxonomy_source": "deterministic",
        }


def _extract_json(content: str) -> Dict[str, Any]:
    """Extract one JSON object from a model response."""
    text = clean_text(content)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object found")
    return json.loads(text[start : end + 1])
