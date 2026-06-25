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
    ISSUE_REQUIRED_FIELDS,
    REPORT_STATUS_COMPLETE,
    REPORT_STATUS_INCOMPLETE,
    REPORT_STATUS_INVALID,
    SCHEMA_VERSION,
    load_bug_candidates,
    load_issue_report_bundle,
    load_issue_reports,
    normalize_bug_candidate,
    normalize_issue_report,
    normalize_step_record,
)

__all__ = [
    "SCHEMA_VERSION",
    "ISSUE_REQUIRED_FIELDS",
    "REPORT_STATUS_COMPLETE",
    "REPORT_STATUS_INCOMPLETE",
    "REPORT_STATUS_INVALID",
    "INTERACTION_MODE_ALIASES",
    "INTERACTION_MODE_TO_BACKEND",
    "SUPPORTED_INTERACTION_MODES",
    "backend_type_for_interaction_mode",
    "interaction_mode_for_backend_type",
    "load_bug_candidates",
    "load_issue_report_bundle",
    "load_issue_reports",
    "normalize_interaction_mode",
    "normalize_bug_candidate",
    "normalize_issue_report",
    "normalize_step_record",
]
