from __future__ import annotations

from .models import EnvironmentTagSet, SubEnvironmentCandidate


DOMAIN_TOPIC_MAP = {
    "ai": "ai-ml",
    "machine-learning": "ai-ml",
    "ml": "ai-ml",
    "devops": "infra-cloud",
    "kubernetes": "infra-cloud",
    "cloud": "infra-cloud",
    "database": "data-database",
    "sql": "data-database",
    "security": "security",
    "cli": "cli-automation",
    "game": "game-interactive",
    "react": "web-productivity",
    "workflow": "web-productivity",
}


def tag_candidate(candidate: SubEnvironmentCandidate) -> EnvironmentTagSet:
    repo = candidate.repository
    domain = _unique(
        DOMAIN_TOPIC_MAP.get(topic.lower(), "")
        for topic in repo.topics
    )
    if not domain:
        language_names = {name.lower() for name in repo.languages}
        if {"python", "typescript", "javascript"} & language_names:
            domain.append("developer-tooling")

    interaction: list[str] = []
    if candidate.signals.has_api_surface:
        interaction.append("api")
    if candidate.signals.has_cli_surface:
        interaction.append("cli")
    if candidate.signals.has_browser_surface:
        interaction.append("browser")

    runtime: list[str] = []
    if candidate.signals.has_dockerfile:
        runtime.append("docker")
    if candidate.signals.has_compose:
        runtime.append("docker-compose")
    for language in repo.languages:
        lowered = language.lower()
        if lowered in {"python", "typescript", "javascript", "go", "rust", "java"}:
            runtime.append("node" if lowered in {"typescript", "javascript"} else lowered)
    runtime = _unique(runtime)

    benchmark = ["release-pair"] if candidate.release_pair else []
    if candidate.signals.bugfix_evidence:
        benchmark.append("bugfix-rich")

    return EnvironmentTagSet(
        domain=_unique(domain),
        interaction=_unique(interaction),
        runtime=runtime,
        benchmark=_unique(benchmark),
    )


def _unique(values) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
