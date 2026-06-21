"""Stable GBQA QA output protocol."""

from gbqa.protocol.interaction import (
    INTERACTION_MODE_ALIASES,
    INTERACTION_MODE_TO_BACKEND,
    SUPPORTED_INTERACTION_MODES,
    backend_type_for_interaction_mode,
    interaction_mode_for_backend_type,
    normalize_interaction_mode,
)
from gbqa.protocol.schemas import (
    SCHEMA_VERSION,
    load_bug_candidates,
    normalize_bug_candidate,
    normalize_step_record,
)

__all__ = [
    "SCHEMA_VERSION",
    "INTERACTION_MODE_ALIASES",
    "INTERACTION_MODE_TO_BACKEND",
    "SUPPORTED_INTERACTION_MODES",
    "backend_type_for_interaction_mode",
    "interaction_mode_for_backend_type",
    "load_bug_candidates",
    "normalize_interaction_mode",
    "normalize_bug_candidate",
    "normalize_step_record",
]
