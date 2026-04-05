"""Typed models for the Hub sourcing pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


def _serialize(value: Any) -> Any:
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


class SerializableModel:
    """Common JSON serialization helpers for dataclasses."""

    def to_dict(self) -> Dict[str, Any]:
        return _serialize(asdict(self))


@dataclass(slots=True)
class ProvenanceRecord(SerializableModel):
    """Fetched source metadata for reproducibility."""

    url: str
    sha256: str
    fetched_at: str
    content_type: str = ""


@dataclass(slots=True)
class CapabilityMatrix(SerializableModel):
    """Hard-filter and feasibility signals for a candidate."""

    is_free: bool = False
    has_public_source: bool = False
    has_historical_builds: bool = False
    has_version_trail: bool = False
    has_patch_notes: bool = False
    has_official_patch_notes: bool = False
    runnable_locally: bool = False
    blocks_archival_replay: bool = False
    evidence: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "CapabilityMatrix":
        return cls(
            is_free=bool(payload.get("is_free", False)),
            has_public_source=bool(payload.get("has_public_source", False)),
            has_historical_builds=bool(payload.get("has_historical_builds", False)),
            has_version_trail=bool(payload.get("has_version_trail", False)),
            has_patch_notes=bool(payload.get("has_patch_notes", False)),
            has_official_patch_notes=bool(
                payload.get("has_official_patch_notes", False)
            ),
            runnable_locally=bool(payload.get("runnable_locally", False)),
            blocks_archival_replay=bool(payload.get("blocks_archival_replay", False)),
            evidence=dict(payload.get("evidence", {})),
        )


@dataclass(slots=True)
class VersionRecord(SerializableModel):
    """Recoverable version artifact information."""

    version: str
    published_at: str
    artifact_url: str
    artifact_kind: str = "archive"
    notes_url: str = ""
    source_url: str = ""
    accessible: bool = True
    checksum: str = ""

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "VersionRecord":
        return cls(
            version=str(payload.get("version", "")),
            published_at=str(payload.get("published_at", "")),
            artifact_url=str(payload.get("artifact_url", "")),
            artifact_kind=str(payload.get("artifact_kind", "archive")),
            notes_url=str(payload.get("notes_url", "")),
            source_url=str(payload.get("source_url", "")),
            accessible=bool(payload.get("accessible", True)),
            checksum=str(payload.get("checksum", "")),
        )


@dataclass(slots=True)
class PatchRecord(SerializableModel):
    """Official patch note or changelog entry."""

    patch_id: str
    version: str
    title: str
    published_at: str
    notes_url: str
    body: str
    is_official: bool = True

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "PatchRecord":
        return cls(
            patch_id=str(payload.get("patch_id", "")),
            version=str(payload.get("version", "")),
            title=str(payload.get("title", "")),
            published_at=str(payload.get("published_at", "")),
            notes_url=str(payload.get("notes_url", "")),
            body=str(payload.get("body", "")),
            is_official=bool(payload.get("is_official", True)),
        )


@dataclass(slots=True)
class VersionPair(SerializableModel):
    """Selected baseline/fix version pair for benchmark construction."""

    baseline_version: str
    baseline_artifact: str
    fix_version: str
    patch_id: str
    patch_published_at: str
    recovery_method: str

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "VersionPair":
        return cls(
            baseline_version=str(payload.get("baseline_version", "")),
            baseline_artifact=str(payload.get("baseline_artifact", "")),
            fix_version=str(payload.get("fix_version", "")),
            patch_id=str(payload.get("patch_id", "")),
            patch_published_at=str(payload.get("patch_published_at", "")),
            recovery_method=str(payload.get("recovery_method", "")),
        )


@dataclass(slots=True)
class ScoreBreakdown(SerializableModel):
    """Selection score and hard-filter outcome."""

    access_licensing: float = 0.0
    version_patch_quality: float = 0.0
    historical_build_recoverability: float = 0.0
    complexity_fit: float = 0.0
    maintenance_cadence: float = 0.0
    documentation_quality: float = 0.0
    total: float = 0.0
    accepted: bool = False
    hard_filter_failures: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ScoreBreakdown":
        return cls(
            access_licensing=float(payload.get("access_licensing", 0.0)),
            version_patch_quality=float(payload.get("version_patch_quality", 0.0)),
            historical_build_recoverability=float(
                payload.get("historical_build_recoverability", 0.0)
            ),
            complexity_fit=float(payload.get("complexity_fit", 0.0)),
            maintenance_cadence=float(payload.get("maintenance_cadence", 0.0)),
            documentation_quality=float(payload.get("documentation_quality", 0.0)),
            total=float(payload.get("total", 0.0)),
            accepted=bool(payload.get("accepted", False)),
            hard_filter_failures=list(payload.get("hard_filter_failures", [])),
        )


@dataclass(slots=True)
class CandidateGame(SerializableModel):
    """Normalized candidate game metadata across providers."""

    game_id: str
    title: str
    provider: str
    provider_id: str
    slug: str
    summary: str
    homepage_url: str
    source_repo_url: str
    license: str
    runtime_kind: str
    tags: List[str] = field(default_factory=list)
    versions: List[VersionRecord] = field(default_factory=list)
    patches: List[PatchRecord] = field(default_factory=list)
    capabilities: CapabilityMatrix = field(default_factory=CapabilityMatrix)
    score: float = 0.0
    score_breakdown: Optional[ScoreBreakdown] = None
    complexity: str = "medium"
    selected_version_pair: Optional[VersionPair] = None
    artifact_urls: List[str] = field(default_factory=list)
    patch_notes_url: str = ""
    provenance: List[ProvenanceRecord] = field(default_factory=list)
    rejection_reasons: List[str] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "CandidateGame":
        score_breakdown = payload.get("score_breakdown")
        version_pair = payload.get("selected_version_pair")
        return cls(
            game_id=str(payload.get("game_id", "")),
            title=str(payload.get("title", "")),
            provider=str(payload.get("provider", "")),
            provider_id=str(payload.get("provider_id", "")),
            slug=str(payload.get("slug", "")),
            summary=str(payload.get("summary", "")),
            homepage_url=str(payload.get("homepage_url", "")),
            source_repo_url=str(payload.get("source_repo_url", "")),
            license=str(payload.get("license", "")),
            runtime_kind=str(payload.get("runtime_kind", "")),
            tags=list(payload.get("tags", [])),
            versions=[
                VersionRecord.from_dict(item)
                for item in payload.get("versions", [])
                if isinstance(item, dict)
            ],
            patches=[
                PatchRecord.from_dict(item)
                for item in payload.get("patches", [])
                if isinstance(item, dict)
            ],
            capabilities=CapabilityMatrix.from_dict(
                payload.get("capabilities", {}) if isinstance(payload, dict) else {}
            ),
            score=float(payload.get("score", 0.0)),
            score_breakdown=(
                ScoreBreakdown.from_dict(score_breakdown)
                if isinstance(score_breakdown, dict)
                else None
            ),
            complexity=str(payload.get("complexity", "medium")),
            selected_version_pair=(
                VersionPair.from_dict(version_pair)
                if isinstance(version_pair, dict)
                else None
            ),
            artifact_urls=list(payload.get("artifact_urls", [])),
            patch_notes_url=str(payload.get("patch_notes_url", "")),
            provenance=[
                ProvenanceRecord(**item)
                for item in payload.get("provenance", [])
                if isinstance(item, dict)
            ],
            rejection_reasons=list(payload.get("rejection_reasons", [])),
            extra=dict(payload.get("extra", {})),
        )


@dataclass(slots=True)
class CandidateManifest(SerializableModel):
    """Published manifest consumed by later Hub import steps."""

    game_id: str
    title: str
    provider: str
    runtime_kind: str
    homepage_url: str
    source_repo_url: str
    license: str
    free_access: bool
    historical_build_access: bool
    selected_version_pair: VersionPair
    score: float
    score_breakdown: ScoreBreakdown
    patch_notes_url: str
    artifact_urls: List[str]
    ground_truth_path: str


@dataclass(slots=True)
class GroundTruthBundle(SerializableModel):
    """Published bug bundle derived from patch notes."""

    game_name: str
    game_title: str
    bug_version: str
    total_bugs: int
    patch_notes_url: str
    bugs: List[Dict[str, Any]]
