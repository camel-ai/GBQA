"""GBQA bug-report verifier for Harbor tasks."""

from __future__ import annotations

import argparse
import json
import os
import traceback
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

# Optional LLM semantic matching via agent/src/evaluator
_import_error_msg: str = ""
try:
    from agent.src.evaluator import Evaluator
    from agent.src.llm_client import LlmClient
    from agent.src.types import BugFinding

    _AGENT_EVALUATOR_AVAILABLE = True
except ImportError as _exc:
    _AGENT_EVALUATOR_AVAILABLE = False
    _import_error_msg = f"{type(_exc).__name__}: {_exc}"


@dataclass
class MatchDetail:
    predicted_title: str
    predicted_description: str
    match_id: str
    score: float
    rationale: str
    matched: bool


def _bugs_dict_to_finding(bugs: list[dict[str, Any]]) -> list[Any]:
    """Convert raw bugs.json dicts to BugFinding dataclasses."""
    findings: list[Any] = []
    for bug in bugs:
        if not isinstance(bug, dict):
            continue
        evidence = bug.get("evidence", {})
        if not isinstance(evidence, dict):
            evidence = {}
        findings.append(
            BugFinding(
                title=str(bug.get("title", "")),
                description=str(bug.get("description", "")),
                confidence=float(bug.get("confidence", 0.0)),
                evidence=evidence,
                tags=[str(t) for t in bug.get("tags", []) if t],
            )
        )
    return findings


def _create_llm_client() -> tuple[Any | None, str]:
    """Create an LlmClient from environment variables if available.
    Returns (client, diagnostic_message).
    """
    if not _AGENT_EVALUATOR_AVAILABLE:
        return None, f"agent imports unavailable ({_import_error_msg})"
    api_key = os.environ.get("API_KEY", "")
    base_url = os.environ.get("BASE_URL", "")
    model = os.environ.get("MODEL_NAME", "")
    missing = [k for k in ("API_KEY", "MODEL_NAME") if not os.environ.get(k, "")]
    if missing:
        return None, f"missing env vars: {', '.join(missing)}"
    config: dict[str, Any] = {
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
        "temperature": 0.3,
        "max_tokens": 4096,
        "timeout": 60,
    }
    try:
        client = LlmClient(config)
        return client, "ok"
    except Exception as exc:
        return None, f"LlmClient init failed: {type(exc).__name__}: {exc}"


def evaluate_bug_report(
    *,
    bugs_path: str | Path,
    ground_truth_path: str | Path,
    match_threshold: float = 0.65,
) -> dict[str, Any]:
    """Evaluate a GBQA bug report and return Harbor-compatible reward metrics."""

    try:
        predicted = _load_predicted_bugs(Path(bugs_path))
        ground_truth = _load_ground_truth(Path(ground_truth_path))
    except Exception as exc:  # noqa: BLE001
        return _error_result(f"{type(exc).__name__}: {exc}")

    if not ground_truth:
        return _error_result("No ground-truth bugs were loaded.")

    # Try LLM semantic matching first if agent evaluator is available.
    llm_client, llm_diag = _create_llm_client()
    diagnostics: dict[str, Any] = {
        "agent_imports_available": _AGENT_EVALUATOR_AVAILABLE,
        "agent_import_error": _import_error_msg,
        "llm_client_diag": llm_diag,
        "env_api_key_present": bool(os.environ.get("API_KEY", "")),
        "env_model_name_present": bool(os.environ.get("MODEL_NAME", "")),
        "env_base_url": os.environ.get("BASE_URL", ""),
        "predicted_bug_count": len(predicted),
    }
    if _AGENT_EVALUATOR_AVAILABLE and llm_client is not None and predicted:
        try:
            result = _evaluate_with_llm(
                predicted, ground_truth_path, match_threshold, llm_client
            )
            result["_diagnostics"] = diagnostics
            result["_matcher_used"] = "llm"
            return result
        except Exception as exc:
            diagnostics["llm_eval_error"] = f"{type(exc).__name__}: {exc}"
            diagnostics["llm_eval_traceback"] = traceback.format_exc()
            # Any failure in the LLM path falls through to the legacy
            # SequenceMatcher implementation so the verifier never crashes.
            pass

    # Legacy SequenceMatcher fallback (also used when LLM is unavailable).
    used_truth_indices: set[int] = set()
    details: list[MatchDetail] = []
    matched = 0
    for bug in predicted:
        match_index, score = _best_match_index(
            bug,
            ground_truth,
            used_truth_indices,
            match_threshold,
        )
        is_match = match_index is not None
        if is_match:
            matched += 1
            used_truth_indices.add(match_index)
        truth = ground_truth[match_index] if match_index is not None else {}
        details.append(
            MatchDetail(
                predicted_title=str(bug.get("title", "")),
                predicted_description=str(bug.get("description", "")),
                match_id=str(truth.get("id", "")),
                score=score,
                rationale="sequence_matcher",
                matched=is_match,
            )
        )

    precision = matched / len(predicted) if predicted else 0.0
    recall = matched / len(ground_truth) if ground_truth else 0.0
    reward = recall
    result = {
        "reward": reward,
        "precision": precision,
        "recall": recall,
        "matched": matched,
        "total_predicted": len(predicted),
        "total_ground_truth": len(ground_truth),
        "details": [asdict(detail) for detail in details],
    }
    result["_diagnostics"] = diagnostics
    result["_matcher_used"] = "sequence_matcher"
    return result


def _evaluate_with_llm(
    predicted: list[dict[str, Any]],
    ground_truth_path: str | Path,
    match_threshold: float,
    llm_client: Any,
) -> dict[str, Any]:
    """Evaluate using the agent's LLM-based semantic matcher."""
    findings = _bugs_dict_to_finding(predicted)
    evaluator = Evaluator(
        ground_truth_path=str(ground_truth_path),
        match_threshold=match_threshold,
        llm_client=llm_client,
    )
    result = evaluator.evaluate(findings)
    return {
        "reward": result.recall,
        "precision": result.precision,
        "recall": result.recall,
        "matched": result.matched,
        "total_predicted": result.total_predicted,
        "total_ground_truth": result.total_ground_truth,
        "details": [asdict(d) for d in result.details],
    }


def write_harbor_reward(result: dict[str, Any], out_dir: str | Path) -> None:
    """Write Harbor reward files under the verifier log directory."""

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    reward = float(result.get("reward", 0.0) or 0.0)
    (out_path / "reward.txt").write_text(f"{reward}\n", encoding="utf-8")
    (out_path / "reward.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_predicted_bugs(path: Path) -> list[dict[str, Any]]:
    if path.is_dir():
        path = path / "bugs.json"
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, dict):
        bugs = payload.get("bugs", [])
    elif isinstance(payload, list):
        bugs = payload
    else:
        bugs = []
    return [bug for bug in bugs if isinstance(bug, dict)]


def _load_ground_truth(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    bugs = payload.get("bugs", []) if isinstance(payload, dict) else []
    return [_normalize_truth(item) for item in bugs if isinstance(item, dict)]


def _best_match_index(
    bug: dict[str, Any],
    truth: list[dict[str, Any]],
    used_indices: set[int],
    match_threshold: float,
) -> tuple[int | None, float]:
    best_score = 0.0
    best_index: int | None = None
    bug_text = _bug_text(bug)
    for index, item in enumerate(truth):
        if index in used_indices:
            continue
        score = _match_score(bug, item, bug_text)
        if score > best_score:
            best_score = score
            best_index = index
    if best_score >= match_threshold:
        return best_index, best_score
    return None, best_score


def _bug_text(bug: dict[str, Any]) -> str:
    evidence = bug.get("evidence", {})
    parts = [
        bug.get("title", ""),
        bug.get("description", ""),
        " ".join(str(tag) for tag in bug.get("tags", []) if tag),
    ]
    if isinstance(evidence, dict):
        parts.extend(str(value) for value in evidence.values())
    return " ".join(str(part).strip() for part in parts if str(part).strip())


def _match_score(
    bug: dict[str, Any],
    truth: dict[str, Any],
    bug_text: str,
) -> float:
    """Score both whole-report similarity and structured evidence overlap."""

    scores = [SequenceMatcher(None, bug_text, _truth_text(truth)).ratio()]
    for left in _bug_match_parts(bug):
        for right in _truth_match_parts(truth):
            if left and right:
                scores.append(SequenceMatcher(None, left, right).ratio())
    return max(scores) if scores else 0.0


def _bug_match_parts(bug: dict[str, Any]) -> list[str]:
    evidence = bug.get("evidence", {})
    parts = [str(bug.get("title", "")), str(bug.get("description", ""))]
    if isinstance(evidence, dict):
        observed_fault = evidence.get("observed_fault")
        if observed_fault:
            parts.append(str(observed_fault))
        reproduction = evidence.get("minimal_reproduction")
        if isinstance(reproduction, list):
            parts.append(" ".join(str(step) for step in reproduction))
        elif reproduction:
            parts.append(str(reproduction))
    return [part.strip() for part in parts if part and part.strip()]


def _truth_match_parts(truth: dict[str, Any]) -> list[str]:
    return [
        str(part).strip()
        for part in [
            truth.get("title", ""),
            truth.get("description", ""),
            truth.get("observed_fault", ""),
            " ".join(truth.get("minimal_reproduction", [])),
        ]
        if str(part).strip()
    ]


def _normalize_truth(payload: dict[str, Any]) -> dict[str, Any]:
    minimal_reproduction = payload.get("minimal_reproduction") or payload.get("test_steps", [])
    if isinstance(minimal_reproduction, str):
        minimal_reproduction = [minimal_reproduction]
    if not isinstance(minimal_reproduction, list):
        minimal_reproduction = []
    observed_fault = str(
        payload.get("observed_fault")
        or payload.get("actual_behavior")
        or payload.get("description")
        or ""
    ).strip()
    return {
        "id": str(payload.get("id", "")).strip(),
        "bug_type": str(payload.get("bug_type", "")).strip(),
        "difficulty": str(payload.get("difficulty", "")).strip(),
        "minimal_reproduction": [str(step).strip() for step in minimal_reproduction],
        "observed_fault": observed_fault,
        "title": str(payload.get("title") or observed_fault).strip(),
        "description": str(payload.get("description") or observed_fault).strip(),
    }


def _truth_text(truth: dict[str, Any]) -> str:
    parts = [
        truth.get("title", ""),
        truth.get("description", ""),
        truth.get("bug_type", ""),
        truth.get("difficulty", ""),
        " ".join(truth.get("minimal_reproduction", [])),
        truth.get("observed_fault", ""),
    ]
    return " ".join(str(part).strip() for part in parts if str(part).strip())


def _error_result(error: str) -> dict[str, Any]:
    return {
        "reward": 0.0,
        "precision": 0.0,
        "recall": 0.0,
        "matched": 0,
        "total_predicted": 0,
        "total_ground_truth": 0,
        "details": [],
        "error": error,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate a GBQA bug report")
    parser.add_argument("--bugs", required=True)
    parser.add_argument("--ground-truth", required=True)
    parser.add_argument("--out-dir", default="/logs/verifier")
    parser.add_argument("--match-threshold", type=float, default=0.65)
    args = parser.parse_args()
    result = evaluate_bug_report(
        bugs_path=args.bugs,
        ground_truth_path=args.ground_truth,
        match_threshold=args.match_threshold,
    )
    write_harbor_reward(result, args.out_dir)


if __name__ == "__main__":
    main()
