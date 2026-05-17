from __future__ import annotations

from collections import defaultdict

from .models import RepositoryCandidate, StaticSignals, SubEnvironmentCandidate
from .utils import first_matching_path, has_fix_language, normalize_path, slugify


DEPLOYMENT_MARKERS = (
    "dockerfile",
    "docker-compose.yml",
    "compose.yml",
    "makefile",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "go.mod",
    "cargo.toml",
    "pom.xml",
    "build.gradle",
)
LOCKFILE_MARKERS = (
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "poetry.lock",
    "uv.lock",
    "requirements.lock",
    "cargo.lock",
)
API_MARKERS = (
    "openapi",
    "swagger",
    "routes/",
    "api/",
    "server.py",
    "app.py",
    "fastapi",
    "flask",
    "express",
    "controllers/",
)
CLI_MARKERS = (
    "argparse",
    "click",
    "typer",
    "cobra",
    "commander",
    "__main__.py",
    "cmd/",
)
BROWSER_MARKERS = (
    "src/app.tsx",
    "src/app.jsx",
    "src/main.tsx",
    "src/main.jsx",
    "pages/",
    "components/",
    "vite.config",
    "webpack.config",
)
HEALTH_MARKERS = ("health", "ready", "live")


def detect_sub_environments(repository: RepositoryCandidate) -> list[SubEnvironmentCandidate]:
    sub_paths = _candidate_sub_paths(repository.file_paths)
    return [_build_sub_environment(repository, sub_path) for sub_path in sub_paths]


def _candidate_sub_paths(paths: list[str]) -> list[str]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for path in paths:
        normalized = normalize_path(path)
        first, _, rest = normalized.partition("/")
        if first in {"apps", "packages", "services", "examples"} and rest:
            second = rest.split("/", 1)[0]
            grouped[f"{first}/{second}"].append(normalized)
    result = [""]
    result.extend(sorted(grouped))
    return result


def _build_sub_environment(
    repository: RepositoryCandidate,
    sub_path: str,
) -> SubEnvironmentCandidate:
    scoped_paths = _scoped_paths(repository.file_paths, sub_path)
    signals = _signals(repository, scoped_paths)
    deployment_files = _matching_paths(scoped_paths, DEPLOYMENT_MARKERS)
    interaction_evidence = _matching_paths(scoped_paths, API_MARKERS + CLI_MARKERS + BROWSER_MARKERS)
    runtime_evidence = _matching_paths(scoped_paths, DEPLOYMENT_MARKERS + LOCKFILE_MARKERS)
    kind = _kind(signals)
    suffix = slugify(sub_path) if sub_path else "root"
    return SubEnvironmentCandidate(
        candidate_id=f"{repository.repository_id}-{suffix}",
        repository=repository,
        sub_path=sub_path,
        name=f"{repository.name}:{sub_path}" if sub_path else repository.name,
        kind=kind,
        deployment_files=deployment_files,
        interaction_evidence=interaction_evidence,
        runtime_evidence=runtime_evidence,
        release_pair=repository.release_pair(),
        signals=signals,
    )


def _scoped_paths(paths: list[str], sub_path: str) -> list[str]:
    normalized_sub_path = normalize_path(sub_path)
    if not normalized_sub_path:
        return [normalize_path(path) for path in paths]
    prefix = normalized_sub_path + "/"
    return [
        normalize_path(path)[len(prefix) :]
        for path in paths
        if normalize_path(path).startswith(prefix)
    ]


def _signals(repository: RepositoryCandidate, paths: list[str]) -> StaticSignals:
    lowered_paths = [path.lower() for path in paths]
    deployment = _matching_paths(paths, DEPLOYMENT_MARKERS)
    has_dockerfile = bool(first_matching_path(paths, ("dockerfile",)))
    has_compose = bool(first_matching_path(paths, ("docker-compose.yml", "compose.yml")))
    has_makefile = bool(first_matching_path(paths, ("makefile",)))
    has_lockfile = bool(first_matching_path(paths, LOCKFILE_MARKERS))
    has_api_surface = bool(_matching_paths(paths, API_MARKERS))
    has_cli_surface = bool(_matching_paths(paths, CLI_MARKERS)) or _package_json_bin_hint(lowered_paths)
    has_browser_surface = bool(_matching_paths(paths, BROWSER_MARKERS))
    latest_body = repository.stable_releases()[-1].body if repository.stable_releases() else ""
    return StaticSignals(
        has_two_stable_releases=len(repository.stable_releases()) >= 2,
        linux_candidate=bool(deployment),
        has_api_surface=has_api_surface,
        has_cli_surface=has_cli_surface,
        has_browser_surface=has_browser_surface,
        has_dockerfile=has_dockerfile,
        has_compose=has_compose,
        has_makefile=has_makefile,
        has_lockfile=has_lockfile,
        has_health_endpoint_hint=bool(_matching_paths(paths, HEALTH_MARKERS)),
        bugfix_evidence=has_fix_language(latest_body),
    )


def _matching_paths(paths: list[str], markers: tuple[str, ...]) -> list[str]:
    result: list[str] = []
    lowered_markers = tuple(marker.lower() for marker in markers)
    for path in paths:
        lowered = normalize_path(path).lower()
        if any(marker in lowered for marker in lowered_markers):
            result.append(normalize_path(path))
    return result


def _package_json_bin_hint(paths: list[str]) -> bool:
    return "package.json" in paths and any("bin/" in path for path in paths)


def _kind(signals: StaticSignals):
    if signals.has_api_surface:
        return "api"
    if signals.has_cli_surface:
        return "cli"
    if signals.has_browser_surface:
        return "browser"
    if signals.linux_candidate:
        return "service"
    return "unknown"
