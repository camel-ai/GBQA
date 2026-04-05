"""Automatic patch-note-to-ground-truth generation."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from .models import CandidateGame, GroundTruthBundle, PatchRecord, VersionPair
from .utils import clean_text, has_fix_language, looks_non_bug_line, split_patch_lines


@dataclass(slots=True)
class PatchNoteLlmClient:
    """Optional OpenAI-compatible helper for reproduction-step synthesis."""

    api_key: str
    model: str
    base_url: str = "https://api.openai.com/v1"
    timeout: int = 20

    @classmethod
    def from_env(cls) -> Optional["PatchNoteLlmClient"]:
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
        game_title: str,
        baseline_version: str,
        issue_summary: str,
        observed_fault: str,
    ) -> Optional[List[str]]:
        prompt = (
            "Return compact JSON with a single key `steps`, whose value is an array of 2 or 3 "
            "minimal reproduction steps for a bug observed in a baseline game build.\n"
            f"Game: {game_title}\n"
            f"Baseline version: {baseline_version}\n"
            f"Issue summary: {issue_summary}\n"
            f"Observed fault: {observed_fault}\n"
        )
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": "You write concise QA reproduction steps as JSON only.",
                },
                {"role": "user", "content": prompt},
            ],
        }
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
            parsed = _extract_json(content)
            steps = parsed.get("steps", [])
            if isinstance(steps, list):
                cleaned = [clean_text(str(step)) for step in steps if clean_text(str(step))]
                return cleaned or None
        except (KeyError, ValueError, TypeError):
            return None
        return None


class GroundTruthGenerator:
    """Generate evaluator-compatible bug files from patch notes."""

    def __init__(self, llm_client: Optional[PatchNoteLlmClient] = None) -> None:
        self._llm_client = llm_client or PatchNoteLlmClient.from_env()

    def generate(
        self,
        candidate: CandidateGame,
        version_pair: VersionPair,
    ) -> GroundTruthBundle:
        patch = self._find_patch(candidate, version_pair.patch_id)
        if patch is None:
            raise ValueError(f"patch {version_pair.patch_id} not found for {candidate.slug}")
        bug_lines = self._extract_bug_lines(patch.body)
        bugs = []
        for index, line in enumerate(bug_lines, start=1):
            observed_fault = self._observed_fault(line)
            steps = self._steps(candidate, version_pair, line, observed_fault)
            bugs.append(
                {
                    "id": f"{version_pair.patch_id.upper()}-BUG-{index:03d}",
                    "bug_type": self._bug_type(line),
                    "difficulty": self._difficulty(line),
                    "title": self._title(line),
                    "description": f"Derived automatically from patch notes: {line}",
                    "minimal_reproduction": steps,
                    "observed_fault": observed_fault,
                    "source_patch_url": patch.notes_url,
                    "source_excerpt": line,
                    "extraction_confidence": self._confidence(line),
                }
            )
        return GroundTruthBundle(
            game_name=candidate.game_id,
            game_title=candidate.title,
            bug_version=version_pair.patch_id,
            total_bugs=len(bugs),
            patch_notes_url=patch.notes_url,
            bugs=bugs,
        )

    @staticmethod
    def _find_patch(candidate: CandidateGame, patch_id: str) -> Optional[PatchRecord]:
        for patch in candidate.patches:
            if patch.patch_id == patch_id:
                return patch
        return None

    @staticmethod
    def _extract_bug_lines(body: str) -> List[str]:
        lines = []
        for line in split_patch_lines(body):
            if not has_fix_language(line):
                continue
            if looks_non_bug_line(line):
                continue
            lines.append(line)
        return lines or [clean_text(body)]

    def _steps(
        self,
        candidate: CandidateGame,
        version_pair: VersionPair,
        line: str,
        observed_fault: str,
    ) -> List[str]:
        if self._llm_client is not None:
            generated = self._llm_client.synthesize_steps(
                game_title=candidate.title,
                baseline_version=version_pair.baseline_version,
                issue_summary=line,
                observed_fault=observed_fault,
            )
            if generated:
                return generated
        return [
            f"Launch {candidate.title} baseline version {version_pair.baseline_version}.",
            f"Exercise the gameplay path related to: {self._title(line)}.",
            f"Observe that {observed_fault}",
        ]

    @staticmethod
    def _title(line: str) -> str:
        text = clean_text(line)
        text = re.sub(r"^(fixed|fix|resolved|resolve|hotfix)\s+", "", text, flags=re.IGNORECASE)
        return text[:120]

    @staticmethod
    def _observed_fault(line: str) -> str:
        text = clean_text(line)
        replacements = (
            (r"^(fixed|fixes?|resolved|resolve|hotfix(ed)?)\s+", ""),
            (r"\bwould\b", ""),
            (r"\bcould\b", ""),
        )
        for pattern, replacement in replacements:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        text = clean_text(text.rstrip("."))
        if not text.lower().startswith("the"):
            text = f"The game {text[0].lower() + text[1:] if text else 'shows the patched issue.'}"
        if not text.endswith("."):
            text += "."
        return text

    @staticmethod
    def _bug_type(line: str) -> str:
        lowered = clean_text(line).lower()
        if "crash" in lowered or "freeze" in lowered:
            return "stability"
        if "ui" in lowered or "menu" in lowered:
            return "ui issue"
        if "save" in lowered or "load" in lowered:
            return "data inconsistency"
        if "performance" in lowered or "lag" in lowered:
            return "performance"
        return "logic error"

    @staticmethod
    def _difficulty(line: str) -> str:
        lowered = clean_text(line).lower()
        if any(token in lowered for token in ("save", "multiplayer", "network", "progression")):
            return "medium"
        if any(token in lowered for token in ("startup", "crash", "launch")):
            return "easy"
        return "easy"

    @staticmethod
    def _confidence(line: str) -> float:
        lowered = clean_text(line).lower()
        if "fix" in lowered or "resolved" in lowered:
            return 0.86
        return 0.65


def _extract_json(content: str) -> Dict[str, Any]:
    text = clean_text(content)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object found")
    return json.loads(text[start : end + 1])
