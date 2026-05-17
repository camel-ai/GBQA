from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Literal


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return _serialize(asdict(value))
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    return value


class Serializable:
    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class ProvenanceRecord(Serializable):
    url: str
    sha256: str
    fetched_at: str
    content_type: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProvenanceRecord":
        return cls(
            url=str(payload.get("url", "")),
            sha256=str(payload.get("sha256", "")),
            fetched_at=str(payload.get("fetched_at", "")),
            content_type=str(payload.get("content_type", "")),
        )


@dataclass(slots=True)
class ReleaseRecord(Serializable):
    tag_name: str
    title: str
    published_at: str
    html_url: str
    archive_url: str
    body: str = ""
    draft: bool = False
    prerelease: bool = False

    @property
    def is_stable(self) -> bool:
        text = f"{self.tag_name} {self.title}".lower()
        unstable_markers = ("alpha", "beta", "rc", "preview", "nightly", "dev")
        return not self.draft and not self.prerelease and not any(
            marker in text for marker in unstable_markers
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ReleaseRecord":
        return cls(
            tag_name=str(payload.get("tag_name", "")),
            title=str(payload.get("title", "")),
            published_at=str(payload.get("published_at", "")),
            html_url=str(payload.get("html_url", "")),
            archive_url=str(payload.get("archive_url", "")),
            body=str(payload.get("body", "")),
            draft=bool(payload.get("draft", False)),
            prerelease=bool(payload.get("prerelease", False)),
        )


@dataclass(slots=True)
class ReleasePairCandidate(Serializable):
    baseline_release: str
    fixed_release: str
    baseline_archive_url: str
    fixed_release_url: str
    selection_policy: str = "latest_minus_one"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ReleasePairCandidate":
        return cls(
            baseline_release=str(payload.get("baseline_release", "")),
            fixed_release=str(payload.get("fixed_release", "")),
            baseline_archive_url=str(payload.get("baseline_archive_url", "")),
            fixed_release_url=str(payload.get("fixed_release_url", "")),
            selection_policy=str(payload.get("selection_policy", "latest_minus_one")),
        )


@dataclass(slots=True)
class RepositoryCandidate(Serializable):
    repository_id: str
    provider: str
    owner: str
    name: str
    full_name: str
    html_url: str
    clone_url: str
    default_branch: str
    description: str
    topics: list[str] = field(default_factory=list)
    license: str = ""
    stars: int = 0
    forks: int = 0
    open_issues: int = 0
    languages: dict[str, int] = field(default_factory=dict)
    releases: list[ReleaseRecord] = field(default_factory=list)
    file_paths: list[str] = field(default_factory=list)
    archived: bool = False
    fork: bool = False
    template: bool = False
    homepage: str = ""
    provenance: list[ProvenanceRecord] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def stable_releases(self) -> list[ReleaseRecord]:
        return sorted(
            [release for release in self.releases if release.is_stable],
            key=lambda item: item.published_at,
        )

    def release_pair(self) -> ReleasePairCandidate | None:
        stable_releases = self.stable_releases()
        if len(stable_releases) < 2:
            return None
        baseline = stable_releases[-2]
        fixed = stable_releases[-1]
        if not baseline.archive_url:
            return None
        return ReleasePairCandidate(
            baseline_release=baseline.tag_name,
            fixed_release=fixed.tag_name,
            baseline_archive_url=baseline.archive_url,
            fixed_release_url=fixed.html_url,
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RepositoryCandidate":
        return cls(
            repository_id=str(payload.get("repository_id", "")),
            provider=str(payload.get("provider", "")),
            owner=str(payload.get("owner", "")),
            name=str(payload.get("name", "")),
            full_name=str(payload.get("full_name", "")),
            html_url=str(payload.get("html_url", "")),
            clone_url=str(payload.get("clone_url", "")),
            default_branch=str(payload.get("default_branch", "")),
            description=str(payload.get("description", "")),
            topics=list(payload.get("topics", [])),
            license=str(payload.get("license", "")),
            stars=int(payload.get("stars", 0)),
            forks=int(payload.get("forks", 0)),
            open_issues=int(payload.get("open_issues", 0)),
            languages={str(key): int(value) for key, value in dict(payload.get("languages", {})).items()},
            releases=[
                ReleaseRecord.from_dict(item)
                for item in payload.get("releases", [])
                if isinstance(item, dict)
            ],
            file_paths=list(payload.get("file_paths", [])),
            archived=bool(payload.get("archived", False)),
            fork=bool(payload.get("fork", False)),
            template=bool(payload.get("template", False)),
            homepage=str(payload.get("homepage", "")),
            provenance=[
                ProvenanceRecord.from_dict(item)
                for item in payload.get("provenance", [])
                if isinstance(item, dict)
            ],
            extra=dict(payload.get("extra", {})),
        )


EnvironmentKind = Literal["api", "cli", "browser", "service", "unknown"]


@dataclass(slots=True)
class StaticSignals(Serializable):
    has_two_stable_releases: bool = False
    linux_candidate: bool = False
    has_api_surface: bool = False
    has_cli_surface: bool = False
    has_browser_surface: bool = False
    has_dockerfile: bool = False
    has_compose: bool = False
    has_makefile: bool = False
    has_lockfile: bool = False
    has_health_endpoint_hint: bool = False
    bugfix_evidence: bool = False

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "StaticSignals":
        return cls(**{field_name: bool(payload.get(field_name, False)) for field_name in cls.__dataclass_fields__})


@dataclass(slots=True)
class EnvironmentTagSet(Serializable):
    domain: list[str] = field(default_factory=list)
    interaction: list[str] = field(default_factory=list)
    runtime: list[str] = field(default_factory=list)
    benchmark: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EnvironmentTagSet":
        return cls(
            domain=list(payload.get("domain", [])),
            interaction=list(payload.get("interaction", [])),
            runtime=list(payload.get("runtime", [])),
            benchmark=list(payload.get("benchmark", [])),
        )


@dataclass(slots=True)
class RankingScore(Serializable):
    reproducibility: float = 0.0
    interaction_surface: float = 0.0
    bug_benchmark_potential: float = 0.0
    oss_health: float = 0.0
    deployment_clarity: float = 0.0
    domain_diversity: float = 0.0
    resource_fit: float = 0.0
    total: float = 0.0

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RankingScore":
        return cls(
            reproducibility=float(payload.get("reproducibility", 0.0)),
            interaction_surface=float(payload.get("interaction_surface", 0.0)),
            bug_benchmark_potential=float(payload.get("bug_benchmark_potential", 0.0)),
            oss_health=float(payload.get("oss_health", 0.0)),
            deployment_clarity=float(payload.get("deployment_clarity", 0.0)),
            domain_diversity=float(payload.get("domain_diversity", 0.0)),
            resource_fit=float(payload.get("resource_fit", 0.0)),
            total=float(payload.get("total", 0.0)),
        )


@dataclass(slots=True)
class SubEnvironmentCandidate(Serializable):
    candidate_id: str
    repository: RepositoryCandidate
    sub_path: str
    name: str
    kind: EnvironmentKind
    deployment_files: list[str] = field(default_factory=list)
    interaction_evidence: list[str] = field(default_factory=list)
    runtime_evidence: list[str] = field(default_factory=list)
    release_pair: ReleasePairCandidate | None = None
    signals: StaticSignals = field(default_factory=StaticSignals)
    tags: EnvironmentTagSet = field(default_factory=EnvironmentTagSet)
    score: RankingScore | None = None
    rejection_reasons: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SubEnvironmentCandidate":
        release_pair = payload.get("release_pair")
        score = payload.get("score")
        return cls(
            candidate_id=str(payload.get("candidate_id", "")),
            repository=RepositoryCandidate.from_dict(dict(payload.get("repository", {}))),
            sub_path=str(payload.get("sub_path", "")),
            name=str(payload.get("name", "")),
            kind=str(payload.get("kind", "unknown")),  # type: ignore[arg-type]
            deployment_files=list(payload.get("deployment_files", [])),
            interaction_evidence=list(payload.get("interaction_evidence", [])),
            runtime_evidence=list(payload.get("runtime_evidence", [])),
            release_pair=(
                ReleasePairCandidate.from_dict(release_pair)
                if isinstance(release_pair, dict)
                else None
            ),
            signals=StaticSignals.from_dict(dict(payload.get("signals", {}))),
            tags=EnvironmentTagSet.from_dict(dict(payload.get("tags", {}))),
            score=RankingScore.from_dict(score) if isinstance(score, dict) else None,
            rejection_reasons=list(payload.get("rejection_reasons", [])),
        )


@dataclass(slots=True)
class ProbeResult(Serializable):
    command: str = ""
    endpoint: str | None = None
    exit_code: int | None = None
    http_status: int | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProbeResult":
        return cls(
            command=str(payload.get("command", "")),
            endpoint=payload.get("endpoint"),
            exit_code=payload.get("exit_code"),
            http_status=payload.get("http_status"),
        )


@dataclass(slots=True)
class VerificationArtifacts(Serializable):
    logs: list[str] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "VerificationArtifacts":
        return cls(
            logs=list(payload.get("logs", [])),
            screenshots=list(payload.get("screenshots", [])),
        )


@dataclass(slots=True)
class EnvironmentVerificationResult(Serializable):
    candidate_id: str
    status: Literal["passed", "failed", "inconclusive"]
    sandbox_provider: str
    baseline_release: str
    deployment_method: str
    interaction_mode: str
    probe: ProbeResult = field(default_factory=ProbeResult)
    artifacts: VerificationArtifacts = field(default_factory=VerificationArtifacts)
    failure_reason: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EnvironmentVerificationResult":
        return cls(
            candidate_id=str(payload.get("candidate_id", "")),
            status=str(payload.get("status", "inconclusive")),  # type: ignore[arg-type]
            sandbox_provider=str(payload.get("sandbox_provider", "")),
            baseline_release=str(payload.get("baseline_release", "")),
            deployment_method=str(payload.get("deployment_method", "")),
            interaction_mode=str(payload.get("interaction_mode", "")),
            probe=ProbeResult.from_dict(dict(payload.get("probe", {}))),
            artifacts=VerificationArtifacts.from_dict(dict(payload.get("artifacts", {}))),
            failure_reason=payload.get("failure_reason"),
        )


@dataclass(slots=True)
class PipelineResult(Serializable):
    repositories: list[RepositoryCandidate]
    sub_environments: list[SubEnvironmentCandidate]
    filtered: list[SubEnvironmentCandidate]
    ranked: list[SubEnvironmentCandidate]
    rejected: list[SubEnvironmentCandidate]
    skipped_repositories: int = 0
