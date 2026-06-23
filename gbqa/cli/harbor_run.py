"""Run Harbor with GBQA's root `.env` loaded first."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from gbqa.env import load_root_dotenv


@dataclass
class GBQAHarborOptions:
    task_runner: str = ""
    agent_model: str = ""
    agent_auth: str = ""
    codex_auth_file: str = ""
    claude_oauth_token: str = ""


_GBQA_VALUE_FLAGS = {
    "--gbqa-task-runner": "task_runner",
    "--gbqa-agent-runner": "task_runner",
    "--gbqa-runner": "task_runner",
    "--gbqa-agent-model": "agent_model",
    "--gbqa-agent-auth": "agent_auth",
    "--gbqa-codex-auth-file": "codex_auth_file",
    "--gbqa-claude-oauth-token": "claude_oauth_token",
}


def build_harbor_command(
    argv: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
) -> list[str]:
    """Build the Harbor CLI command preserving caller arguments."""

    env_map = os.environ if env is None else env
    harbor_args, options = _extract_gbqa_options(list(argv))
    harbor_args = _rewrite_backend_environment(harbor_args)
    harbor_args = _apply_gbqa_options(harbor_args, options, env_map)
    return ["harbor", *harbor_args]


def _extract_gbqa_options(argv: list[str]) -> tuple[list[str], GBQAHarborOptions]:
    options = GBQAHarborOptions()
    remaining: list[str] = []
    index = 0
    while index < len(argv):
        item = argv[index]
        flag, sep, inline_value = item.partition("=")
        if flag in _GBQA_VALUE_FLAGS:
            if sep:
                value = inline_value
            else:
                if index + 1 >= len(argv):
                    raise ValueError(f"{item} requires a value")
                index += 1
                value = argv[index]
            setattr(options, _GBQA_VALUE_FLAGS[flag], value)
        else:
            remaining.append(item)
        index += 1
    return remaining, options


def _apply_gbqa_options(
    argv: list[str],
    options: GBQAHarborOptions,
    env: Mapping[str, str],
) -> list[str]:
    rewritten = list(argv)
    task_runner = _normalize_task_runner(
        options.task_runner
        or env.get("GBQA_TASK_RUNNER", "")
        or env.get("GBQA_AGENT_RUNNER", "")
    )
    if task_runner:
        rewritten = _apply_task_runner_options(rewritten, task_runner, options, env)
    return rewritten


def _apply_task_runner_options(
    argv: list[str],
    task_runner: str,
    options: GBQAHarborOptions,
    env: Mapping[str, str],
) -> list[str]:
    rewritten = list(argv)
    has_native_agent = _has_any_option(
        rewritten,
        {"-a", "--agent", "--agent-import-path"},
    )
    if has_native_agent:
        return rewritten

    if task_runner == "gbqa":
        rewritten.extend(
            ["--agent-import-path", "gbqa.harbor.agent:GBQAHarborAgent"]
        )
        return rewritten

    rewritten.extend(["-a", task_runner])
    agent_model = options.agent_model or env.get("GBQA_AGENT_MODEL", "")
    if agent_model and not _has_any_option(rewritten, {"-m", "--model"}):
        rewritten.extend(["-m", agent_model])

    agent_auth = _normalize_auth_mode(
        options.agent_auth or env.get("GBQA_AGENT_AUTH", "auto")
    )
    for key, value in _agent_auth_env(task_runner, agent_auth, options, env):
        _append_env_option(rewritten, ["--ae", "--agent-env"], key, value)
    return rewritten


def _agent_auth_env(
    task_runner: str,
    auth_mode: str,
    options: GBQAHarborOptions,
    env: Mapping[str, str],
) -> list[tuple[str, str]]:
    if task_runner == "codex":
        if _codex_api_key_forced(env):
            return _openai_compatible_env(env)
        if auth_mode == "subscription":
            path = _resolve_codex_auth_path(options, env, include_default=True)
            if path:
                return [("CODEX_AUTH_JSON_PATH", path)]
            return [("CODEX_FORCE_AUTH_JSON", "1")]
        if auth_mode == "api_key":
            return _openai_compatible_env(env)
        path = _resolve_codex_auth_path(options, env, include_default=True)
        if path:
            return [("CODEX_AUTH_JSON_PATH", path)]
        if env.get("CODEX_FORCE_AUTH_JSON", ""):
            return [("CODEX_FORCE_AUTH_JSON", env["CODEX_FORCE_AUTH_JSON"])]
        return _openai_compatible_env(env)

    if task_runner == "claude-code":
        if auth_mode == "subscription":
            values = []
            token = (
                options.claude_oauth_token
                or env.get("CLAUDE_CODE_OAUTH_TOKEN", "")
            )
            if token:
                values.append(("CLAUDE_CODE_OAUTH_TOKEN", token))
            values.append(("CLAUDE_FORCE_OAUTH", "1"))
            return values
        if auth_mode == "api_key":
            return _present_env(
                env,
                "ANTHROPIC_API_KEY",
                "ANTHROPIC_AUTH_TOKEN",
                "ANTHROPIC_BASE_URL",
            )
        return _present_env(env, "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_FORCE_OAUTH")

    return []


def _present_env(env: Mapping[str, str], *keys: str) -> list[tuple[str, str]]:
    return [(key, env[key]) for key in keys if env.get(key, "")]


def _openai_compatible_env(env: Mapping[str, str]) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    api_key = env.get("OPENAI_API_KEY", "") or env.get("API_KEY", "")
    if api_key:
        values.append(("OPENAI_API_KEY", api_key))
    base_url = (
        env.get("OPENAI_BASE_URL", "")
        or env.get("OPENAI_API_BASE", "")
        or env.get("BASE_URL", "")
    )
    if base_url:
        values.append(("OPENAI_BASE_URL", base_url))
        values.append(("OPENAI_API_BASE", base_url))
    return values


def _codex_api_key_forced(env: Mapping[str, str]) -> bool:
    return _truthy(env.get("CODEX_FORCE_API_KEY", ""))


def _resolve_codex_auth_path(
    options: GBQAHarborOptions,
    env: Mapping[str, str],
    *,
    include_default: bool = False,
) -> str:
    configured = options.codex_auth_file or env.get("CODEX_AUTH_JSON_PATH", "")
    if configured:
        return configured
    default = Path.home() / ".codex" / "auth.json"
    if include_default and default.is_file():
        return str(default)
    return ""


def _append_env_option(
    argv: list[str],
    flags: list[str],
    key: str,
    value: str,
) -> None:
    if value == "" or _has_env_option(argv, set(flags), key):
        return
    argv.extend([flags[0], f"{key}={value}"])


def _has_env_option(argv: list[str], flags: set[str], key: str) -> bool:
    for index, item in enumerate(argv):
        flag, sep, inline_value = item.partition("=")
        if flag not in flags:
            continue
        value = (
            inline_value
            if sep
            else argv[index + 1]
            if index + 1 < len(argv)
            else ""
        )
        if value.split("=", maxsplit=1)[0] == key:
            return True
    return False


def _has_any_option(argv: list[str], flags: set[str]) -> bool:
    for item in argv:
        flag = item.split("=", maxsplit=1)[0]
        if flag in flags:
            return True
    return False


def _normalize_task_runner(value: str) -> str:
    text = str(value or "").strip().lower().replace("_", "-")
    aliases = {
        "custom": "gbqa",
        "gbqa-harbor-agent": "gbqa",
        "gbqaharboragent": "gbqa",
        "claude": "claude-code",
        "claude-code": "claude-code",
        "claude_code": "claude-code",
        "codex-cli": "codex",
    }
    text = aliases.get(text, text)
    if text and text not in {"gbqa", "codex", "claude-code"}:
        raise ValueError("GBQA task runner must be one of: gbqa, codex, claude-code")
    return text


def _normalize_auth_mode(value: str) -> str:
    text = str(value or "auto").strip().lower().replace("-", "_")
    if text in {"api", "api_key", "apikey"}:
        return "api_key"
    if text in {"subscription", "auth_json", "oauth"}:
        return "subscription"
    if text != "auto":
        raise ValueError("auth mode must be one of: auto, api_key, subscription")
    return text


def _truthy(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _rewrite_backend_environment(argv: list[str]) -> list[str]:
    interaction_mode = (
        _agent_kwarg(argv, "interaction_profile")
        or _agent_kwarg(argv, "interaction_mode")
    )
    normalized_mode = interaction_mode.replace("-", "_")
    if normalized_mode == "computer_use":
        normalized_mode = "computer"
    if normalized_mode not in {"computer", "default"}:
        return argv
    path_index = _task_path_index(argv)
    if path_index is None:
        return argv
    task_path = Path(argv[path_index]).expanduser()
    if not task_path.exists():
        return argv
    computer_environment = task_path / "environment-computer-use"
    if not computer_environment.exists():
        return argv
    overlay = _prepare_computer_use_task_overlay(task_path, computer_environment)
    rewritten = list(argv)
    rewritten[path_index] = str(overlay)
    return rewritten


def _task_path_index(argv: list[str]) -> int | None:
    for index, item in enumerate(argv):
        if item in {"-p", "--path", "--task-path"} and index + 1 < len(argv):
            return index + 1
        for prefix in ("--path=", "--task-path="):
            if item.startswith(prefix):
                value = item.split("=", maxsplit=1)[1]
                argv[index] = item.split("=", maxsplit=1)[0]
                argv.insert(index + 1, value)
                return index + 1
    return None


def _agent_kwarg(argv: list[str], key: str) -> str:
    for index, item in enumerate(argv):
        if item == "--ak" and index + 1 < len(argv):
            name, _, value = argv[index + 1].partition("=")
            if name == key:
                return value
        if item.startswith("--ak="):
            name, _, value = item.split("=", maxsplit=1)[1].partition("=")
            if name == key:
                return value
    return ""


def _prepare_computer_use_task_overlay(
    task_path: Path,
    computer_environment: Path,
) -> Path:
    # TODO: Discuss with the team whether backend-specific environment selection
    # should become a first-class Harbor/GBQA task mechanism instead of this overlay.
    repo_root = Path(__file__).resolve().parents[2]
    overlay_root = repo_root / "tmp" / "harbor_task_overlays"
    overlay = overlay_root / f"{task_path.name}-computer-use"
    if overlay.exists():
        shutil.rmtree(overlay)
    ignore = shutil.ignore_patterns("environment", "environment-computer-use")
    shutil.copytree(task_path, overlay, ignore=ignore)
    shutil.copytree(computer_environment, overlay / "environment")
    return overlay


def main(argv: Sequence[str] | None = None) -> int:
    """Load root `.env`, then delegate to Harbor."""

    load_root_dotenv()
    command = build_harbor_command(sys.argv[1:] if argv is None else argv)
    return subprocess.call(command, env=os.environ.copy())


if __name__ == "__main__":
    raise SystemExit(main())
