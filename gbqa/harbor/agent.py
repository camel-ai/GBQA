"""Harbor custom agent wrapper for GBQA."""

from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Any

from gbqa.env import load_root_dotenv
from gbqa.harbor.config import render_agent_config
from gbqa.spec import GBQAMetadata, load_gbqa_metadata

DEFAULT_BASE_URL = "https://zenmux.ai/api/v1"

try:
    from harbor.agents.base import BaseAgent
    from harbor.environments.base import BaseEnvironment
    from harbor.models.agent.context import AgentContext
except ImportError:  # pragma: no cover - exercised only without Harbor installed.
    class BaseAgent:  # type: ignore[no-redef]
        def __init__(self, logs_dir: Path, model_name: str | None = None, **_: Any) -> None:
            self.logs_dir = logs_dir
            self.model_name = model_name

    BaseEnvironment = Any  # type: ignore[assignment,misc]
    AgentContext = Any  # type: ignore[assignment,misc]


class GBQAHarborAgent(BaseAgent):
    """Run the GBQA QA loop inside a Harbor-managed Daytona sandbox."""

    _REMOTE_ROOT = "/sandbox"
    _REMOTE_AGENT_DIR = "/sandbox/agent"
    _REMOTE_GBQA_DIR = "/sandbox/gbqa"
    _REMOTE_RUNTIME_DIR = "/sandbox/runtime"
    _REMOTE_PYTHON = "/opt/venv/bin/python"
    _TASK_METADATA_RELATIVE = Path("gbqa/tasks/dark-castle/gbqa.yaml")

    def __init__(
        self,
        logs_dir: Path,
        model_name: str | None = None,
        interaction_mode: str = "api",
        max_steps: int = 30,
        extra_env: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(logs_dir=logs_dir, model_name=model_name, **kwargs)
        self.metadata = self._load_task_metadata()
        if interaction_mode not in self.metadata.supported_interaction_modes:
            raise ValueError(
                "interaction_mode must be one of: "
                + ", ".join(self.metadata.supported_interaction_modes)
            )
        self.interaction_mode = interaction_mode
        self.max_steps = int(max_steps)
        self._extra_env = dict(extra_env or {})

    @staticmethod
    def name() -> str:
        return "gbqa"

    def version(self) -> str:
        return "0.1.0"

    async def setup(self, environment: BaseEnvironment) -> None:
        repo_root = self._repo_root()
        await environment.exec(
            command=(
                f"mkdir -p {self._REMOTE_ROOT} {self._REMOTE_RUNTIME_DIR} "
                f"{self.metadata.agent_artifact_dir}/artifacts"
            ),
            user="root",
        )
        await environment.upload_dir(repo_root / "agent", self._REMOTE_AGENT_DIR)
        await environment.upload_dir(repo_root / "gbqa", self._REMOTE_GBQA_DIR)
        await self._ensure_software_release(environment)

        config_text = render_agent_config(
            metadata=self.metadata,
            interaction_mode=self.interaction_mode,
            max_steps=self.max_steps,
            report_output_dir=f"{self.metadata.agent_artifact_dir}/raw_reports",
            prompt_dir=f"{self._REMOTE_AGENT_DIR}/prompts",
            screenshot_dir=f"{self.metadata.agent_artifact_dir}/artifacts/screenshots",
        )
        await self._write_remote_file(
            environment,
            f"{self._REMOTE_RUNTIME_DIR}/config.yaml",
            config_text,
        )

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        del instruction
        runtime_env = self._runtime_env()
        self._validate_runtime_env(runtime_env)

        await self._start_dark_castle(environment)
        await self._wait_for_service(environment)

        run_command = (
            f"cd {shlex.quote(self._REMOTE_AGENT_DIR)} && "
            f"{shlex.quote(self._REMOTE_PYTHON)} run_agent.py "
            f"--task {shlex.quote(self.metadata.task_slug)} "
            f"--config {shlex.quote(self._REMOTE_RUNTIME_DIR + '/config.yaml')} "
            f"--max-steps {self.max_steps} "
            f"> {self.metadata.agent_artifact_dir}/gbqa-agent.stdout "
            f"2> {self.metadata.agent_artifact_dir}/gbqa-agent.stderr"
        )
        result = await environment.exec(
            command=run_command,
            env=runtime_env,
            timeout_sec=max(300, self.max_steps * 90),
        )

        await self._export_artifacts(environment)
        if hasattr(context, "metadata"):
            context.metadata = {
                "interaction_mode": self.interaction_mode,
                "artifact_dir": self.metadata.agent_artifact_dir,
                "agent_return_code": getattr(result, "return_code", None),
            }

        if getattr(result, "return_code", 1) != 0:
            raise RuntimeError(
                "GBQA agent failed with return code "
                f"{result.return_code}. See {self.metadata.agent_artifact_dir}/gbqa-agent.stderr."
            )

    @classmethod
    def build_run_command(
        cls,
        *,
        max_steps: int,
        config_path: str = "/sandbox/runtime/config.yaml",
        remote_agent_dir: str = "/sandbox/agent",
        python_path: str = "/opt/venv/bin/python",
        artifact_dir: str = "/logs/agent/gbqa",
    ) -> str:
        """Return the sandbox command used to run the legacy QA loop."""

        return (
            f"cd {shlex.quote(remote_agent_dir)} && "
            f"{shlex.quote(python_path)} run_agent.py "
            "--task dark-castle "
            f"--config {shlex.quote(config_path)} "
            f"--max-steps {int(max_steps)} "
            f"> {artifact_dir}/gbqa-agent.stdout "
            f"2> {artifact_dir}/gbqa-agent.stderr"
        )

    @staticmethod
    def _repo_root() -> Path:
        return Path(__file__).resolve().parents[2]

    @classmethod
    def _load_task_metadata(cls) -> GBQAMetadata:
        return load_gbqa_metadata(cls._repo_root() / cls._TASK_METADATA_RELATIVE)

    async def _ensure_software_release(self, environment: BaseEnvironment) -> None:
        software_dir = shlex.quote(self.metadata.software_install_dir)
        archive_url = shlex.quote(self.metadata.software_archive_url)
        command = (
            f"if [ ! -f {software_dir}/backend/app.py ]; then "
            f"rm -rf {software_dir} && mkdir -p {software_dir} && "
            f"curl -fsSL {archive_url} | tar -xz --strip-components=1 -C {software_dir}; "
            "fi; "
            f"test -f {software_dir}/backend/app.py"
        )
        result = await environment.exec(command=command, timeout_sec=300)
        if getattr(result, "return_code", 1) != 0:
            raise RuntimeError(
                "Failed to prepare software release "
                f"{self.metadata.software_selected_version} from {self.metadata.software_repository}."
            )

    async def _start_dark_castle(self, environment: BaseEnvironment) -> None:
        command = (
            f"mkdir -p {self.metadata.agent_artifact_dir} && "
            f"cd {shlex.quote(self.metadata.software_install_dir)}/backend && "
            f"env PORT={self.metadata.service_port} "
            f"setsid -f {shlex.quote(self._REMOTE_PYTHON)} app.py "
            f"> {self.metadata.agent_artifact_dir}/dark-castle-server.log "
            "2>&1 < /dev/null && "
            f"echo started > {self.metadata.agent_artifact_dir}/dark-castle-server.pid"
        )
        result = await environment.exec(command=command, timeout_sec=30)
        if getattr(result, "return_code", 1) != 0:
            raise RuntimeError("Failed to start Dark Castle service.")

    async def _wait_for_service(self, environment: BaseEnvironment) -> None:
        url = f"{self.metadata.service_origin}{self.metadata.service_health_path}"
        command = (
            "for i in $(seq 1 60); do "
            f"curl -fsS {shlex.quote(url)} >/dev/null && exit 0; "
            "sleep 1; "
            "done; "
            f"cat {self.metadata.agent_artifact_dir}/dark-castle-server.log || true; "
            "exit 1"
        )
        result = await environment.exec(command=command, timeout_sec=90)
        if getattr(result, "return_code", 1) != 0:
            raise RuntimeError(f"Dark Castle service did not become healthy: {url}")

    async def _export_artifacts(self, environment: BaseEnvironment) -> None:
        command = (
            f"cd {self._REMOTE_ROOT} && "
            f"{shlex.quote(self._REMOTE_PYTHON)} -m gbqa.reporting.export "
            f"--reports-root {self.metadata.agent_artifact_dir}/raw_reports "
            f"--task-id {shlex.quote(self.metadata.task_id)} "
            f"--out-dir {self.metadata.agent_artifact_dir}"
        )
        result = await environment.exec(
            command=command,
            env={"PYTHONPATH": f"{self._REMOTE_ROOT}:{self._REMOTE_AGENT_DIR}"},
            timeout_sec=120,
        )
        if getattr(result, "return_code", 1) != 0:
            raise RuntimeError("Failed to export GBQA Harbor artifacts.")

    async def _write_remote_file(
        self,
        environment: BaseEnvironment,
        remote_path: str,
        content: str,
    ) -> None:
        quoted_path = shlex.quote(remote_path)
        command = f"cat > {quoted_path} <<'GBQA_CONFIG_EOF'\n{content}\nGBQA_CONFIG_EOF"
        result = await environment.exec(command=command, timeout_sec=30)
        if getattr(result, "return_code", 1) != 0:
            raise RuntimeError(f"Failed to write remote file: {remote_path}")

    def _runtime_env(self) -> dict[str, str]:
        load_root_dotenv()
        env: dict[str, str] = {
            "PYTHONPATH": f"{self._REMOTE_ROOT}:{self._REMOTE_AGENT_DIR}",
        }
        for key in ("API_KEY", "BASE_URL", "MODEL_NAME"):
            value = self._extra_env.get(key) or os.environ.get(key)
            if value:
                env[key] = value
        env.setdefault("BASE_URL", DEFAULT_BASE_URL)
        if "MODEL_NAME" not in env and self.model_name:
            env["MODEL_NAME"] = self.model_name
        return env

    @staticmethod
    def _validate_runtime_env(env: dict[str, str]) -> None:
        missing = [
            key for key in ("API_KEY", "MODEL_NAME") if not env.get(key)
        ]
        if missing:
            raise RuntimeError(
                "GBQAHarborAgent requires these env vars for M1 runs: "
                + ", ".join(missing)
            )
