"""Typed models for the Hub software-project sourcing pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


def _serialize(value: Any) -> Any:
    """Recursively convert nested dataclasses into JSON-serializable objects."""
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


class SerializableModel:
    """Base helper for JSON serialization."""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable dictionary."""
        return _serialize(asdict(self))


@dataclass(slots=True)
class ProvenanceRecord(SerializableModel):
    """Store fetched-source metadata for reproducibility."""

    url: str
    sha256: str
    fetched_at: str
    content_type: str = ""


@dataclass(slots=True)
class CapabilityMatrix(SerializableModel):
    """Describe hard-filter signals and inferred architecture."""

    has_public_source: bool = False
    has_release_history: bool = False
    has_fix_releases: bool = False
    has_recoverable_baseline: bool = False
    has_tracked_issue_closure: bool = False
    has_frontend: bool = False
    has_backend: bool = False
    has_database: bool = False
    interaction_mode: str = "unknown"
    evidence: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "CapabilityMatrix":
        """Create a capability matrix from serialized data."""
        return cls(
            has_public_source=bool(payload.get("has_public_source", False)),
            has_release_history=bool(payload.get("has_release_history", False)),
            has_fix_releases=bool(payload.get("has_fix_releases", False)),
            has_recoverable_baseline=bool(
                payload.get("has_recoverable_baseline", False)
            ),
            has_tracked_issue_closure=bool(
                payload.get("has_tracked_issue_closure", False)
            ),
            has_frontend=bool(payload.get("has_frontend", False)),
            has_backend=bool(payload.get("has_backend", False)),
            has_database=bool(payload.get("has_database", False)),
            interaction_mode=str(payload.get("interaction_mode", "unknown")),
            evidence=dict(payload.get("evidence", {})),
        )


@dataclass(slots=True)
class EngagementMetrics(SerializableModel):
    """Store GitHub engagement and contributor activity signals."""

    stars: int = 0
    forks: int = 0
    issue_count: int = 0
    pull_request_count: int = 0
    contributor_count: int = 0
    release_count: int = 0
    tag_count: int = 0
    open_issue_count: int = 0
    days_since_last_push: Optional[int] = None
    release_cadence_days: Optional[float] = None
    workability_score: float = 0.0

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "EngagementMetrics":
        """Create engagement metrics from serialized data."""
        return cls(
            stars=int(payload.get("stars", 0)),
            forks=int(payload.get("forks", 0)),
            issue_count=int(payload.get("issue_count", 0)),
            pull_request_count=int(payload.get("pull_request_count", 0)),
            contributor_count=int(payload.get("contributor_count", 0)),
            release_count=int(payload.get("release_count", 0)),
            tag_count=int(payload.get("tag_count", 0)),
            open_issue_count=int(payload.get("open_issue_count", 0)),
            days_since_last_push=payload.get("days_since_last_push"),
            release_cadence_days=payload.get("release_cadence_days"),
            workability_score=float(payload.get("workability_score", 0.0)),
        )


@dataclass(slots=True)
class ReleaseRecord(SerializableModel):
    """Store GitHub release metadata and bug-fix evidence."""

    release_id: str
    tag_name: str
    title: str
    published_at: str
    notes_url: str
    body: str
    artifact_urls: List[str] = field(default_factory=list)
    has_bug_fix_evidence: bool = False

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ReleaseRecord":
        """Create a release record from serialized data."""
        return cls(
            release_id=str(payload.get("release_id", "")),
            tag_name=str(payload.get("tag_name", "")),
            title=str(payload.get("title", "")),
            published_at=str(payload.get("published_at", "")),
            notes_url=str(payload.get("notes_url", "")),
            body=str(payload.get("body", "")),
            artifact_urls=list(payload.get("artifact_urls", [])),
            has_bug_fix_evidence=bool(payload.get("has_bug_fix_evidence", False)),
        )


@dataclass(slots=True)
class ReleasePair(SerializableModel):
    """Store a recoverable baseline/fix release pair."""

    baseline_version: str
    baseline_artifact: str
    fix_version: str
    release_id: str
    patch_published_at: str
    recovery_method: str

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ReleasePair":
        """Create a release pair from serialized data."""
        return cls(
            baseline_version=str(payload.get("baseline_version", "")),
            baseline_artifact=str(payload.get("baseline_artifact", "")),
            fix_version=str(payload.get("fix_version", "")),
            release_id=str(payload.get("release_id", "")),
            patch_published_at=str(payload.get("patch_published_at", "")),
            recovery_method=str(payload.get("recovery_method", "")),
        )


@dataclass(slots=True)
class ScoreBreakdown(SerializableModel):
    """Store weighted selection scores and hard-filter outcome."""

    source_access: float = 0.0
    release_evidence: float = 0.0
    engineering_activity: float = 0.0
    architecture_fit: float = 0.0
    metadata_quality: float = 0.0
    total: float = 0.0
    accepted: bool = False
    hard_filter_failures: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ScoreBreakdown":
        """Create a score breakdown from serialized data."""
        return cls(
            source_access=float(payload.get("source_access", 0.0)),
            release_evidence=float(payload.get("release_evidence", 0.0)),
            engineering_activity=float(payload.get("engineering_activity", 0.0)),
            architecture_fit=float(payload.get("architecture_fit", 0.0)),
            metadata_quality=float(payload.get("metadata_quality", 0.0)),
            total=float(payload.get("total", 0.0)),
            accepted=bool(payload.get("accepted", False)),
            hard_filter_failures=list(payload.get("hard_filter_failures", [])),
        )


@dataclass(slots=True)
class SoftwareProjectCandidate(SerializableModel):
    """Represent a candidate GitHub software project."""

    environment_id: str
    project_name: str
    provider: str
    repo_full_name: str
    github_url: str
    owner: str
    default_branch: str
    about: str
    topics: List[str] = field(default_factory=list)
    license: str = ""
    clone_url: str = ""
    languages: Dict[str, int] = field(default_factory=dict)
    capabilities: CapabilityMatrix = field(default_factory=CapabilityMatrix)
    engagement: EngagementMetrics = field(default_factory=EngagementMetrics)
    releases: List[ReleaseRecord] = field(default_factory=list)
    selected_release_pair: Optional[ReleasePair] = None
    artifact_urls: List[str] = field(default_factory=list)
    release_notes_url: str = ""
    score: float = 0.0
    score_breakdown: Optional[ScoreBreakdown] = None
    rejection_reasons: List[str] = field(default_factory=list)
    provenance: List[ProvenanceRecord] = field(default_factory=list)
    dedupe_key: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "SoftwareProjectCandidate":
        """Create a candidate from serialized data."""
        score_breakdown = payload.get("score_breakdown")
        selected_release_pair = payload.get("selected_release_pair")
        return cls(
            environment_id=str(payload.get("environment_id", "")),
            project_name=str(payload.get("project_name", "")),
            provider=str(payload.get("provider", "")),
            repo_full_name=str(payload.get("repo_full_name", "")),
            github_url=str(payload.get("github_url", "")),
            owner=str(payload.get("owner", "")),
            default_branch=str(payload.get("default_branch", "")),
            about=str(payload.get("about", "")),
            topics=list(payload.get("topics", [])),
            license=str(payload.get("license", "")),
            clone_url=str(payload.get("clone_url", "")),
            languages=dict(payload.get("languages", {})),
            capabilities=CapabilityMatrix.from_dict(
                dict(payload.get("capabilities", {}))
            ),
            engagement=EngagementMetrics.from_dict(dict(payload.get("engagement", {}))),
            releases=[
                ReleaseRecord.from_dict(item)
                for item in payload.get("releases", [])
                if isinstance(item, dict)
            ],
            selected_release_pair=(
                ReleasePair.from_dict(selected_release_pair)
                if isinstance(selected_release_pair, dict)
                else None
            ),
            artifact_urls=list(payload.get("artifact_urls", [])),
            release_notes_url=str(payload.get("release_notes_url", "")),
            score=float(payload.get("score", 0.0)),
            score_breakdown=(
                ScoreBreakdown.from_dict(score_breakdown)
                if isinstance(score_breakdown, dict)
                else None
            ),
            rejection_reasons=list(payload.get("rejection_reasons", [])),
            provenance=[
                ProvenanceRecord(**item)
                for item in payload.get("provenance", [])
                if isinstance(item, dict)
            ],
            dedupe_key=str(payload.get("dedupe_key", "")),
            extra=dict(payload.get("extra", {})),
        )


@dataclass(slots=True)
class SoftwareProjectManifest(SerializableModel):
    """Represent a published software-project manifest."""

    environment_id: str
    project_name: str
    provider: str
    repo_full_name: str
    github_url: str
    clone_url: str
    owner: str
    default_branch: str
    about: str
    topics: List[str]
    license: str
    languages: Dict[str, int]
    capabilities: CapabilityMatrix
    engagement: EngagementMetrics
    selected_release_pair: ReleasePair
    score: float
    score_breakdown: ScoreBreakdown
    release_notes_url: str
    artifact_urls: List[str]
    ground_truth_path: str
    clone_hint: str
    sandbox_hint: str
    dedupe_key: str
    issue_verification: Optional[Dict[str, Any]] = None


@dataclass(slots=True)
class GroundTruthBundle(SerializableModel):
    """Represent a generated bug-ground-truth bundle."""

    project_name: str
    repo_full_name: str
    bug_version: str
    total_bugs: int
    release_notes_url: str
    bugs: List[Dict[str, Any]]


@dataclass(slots=True)
class DedupeRecord(SerializableModel):
    """Represent one saved release-pair record."""

    dedupe_key: str
    repo_full_name: str
    project_name: str
    release_id: str
    baseline_version: str
    fix_version: str
    manifest_path: str
    saved_at: str


@dataclass(slots=True)
class CatalogLedger(SerializableModel):
    """Represent the persisted dedupe ledger."""

    records: List[DedupeRecord] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "CatalogLedger":
        """Create a ledger from serialized data."""
        return cls(
            records=[
                DedupeRecord(**item)
                for item in payload.get("records", [])
                if isinstance(item, dict)
            ]
        )
