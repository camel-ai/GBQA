"""Harbor custom agent wrapper for GBQA."""

from __future__ import annotations

import os
import shutil
import shlex
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from gbqa.env import load_root_dotenv
from gbqa.harbor.config import render_agent_config
from gbqa.protocol.interaction import normalize_interaction_mode
from gbqa.spec import GBQAMetadata, load_gbqa_metadata

DEFAULT_BASE_URL = "https://zenmux.ai/api/v1"
COMPUTER_USE_ENVIRONMENT_HINT = (
    "computer/default interaction profiles require the GBQA GUI/Cua environment. "
    "If this run was started with direct `harbor run`, Harbor may have selected "
    "the default non-GUI environment. Use `python -m gbqa.cli.harbor_run run ... "
    "--ak interaction_mode=computer` or `--ak interaction_mode=default` so GBQA can select the "
    "`environment-computer-use` overlay."
)

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
    _REMOTE_CONFIG_PATH = "/sandbox/runtime/config.toml"
    _REMOTE_PYTHON = "/opt/venv/bin/python"
    _DEFAULT_TASK_METADATA_RELATIVE = Path("gbqa/tasks/dark-castle/gbqa.yaml")
    _AGENT_UPLOAD_ITEMS = (
        "run_agent.py",
        "config.toml.example",
        "src",
        "prompts",
        "skills",
    )
    _UPLOAD_IGNORE = shutil.ignore_patterns(
        ".env",
        ".venv",
        "__pycache__",
        "*.pyc",
        ".pytest_cache",
        ".mypy_cache",
        ".playwright-mcp",
        "reports",
        "memory",
        "tmp",
        "artifacts",
        "node_modules",
        "*.log",
    )

    def __init__(
        self,
        logs_dir: Path,
        model_name: str | None = None,
        interaction_mode: str = "terminal",
        interaction_profile: str | None = None,
        harness_mode: str = "minimal",
        max_steps: int = 30,
        extra_env: dict[str, str] | None = None,
        task_metadata_path: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(logs_dir=logs_dir, model_name=model_name, **kwargs)
        self._task_metadata_path = task_metadata_path
        self.metadata = self._load_task_metadata(task_metadata_path)
        requested_interaction = interaction_profile or interaction_mode
        normalized_interaction_mode = normalize_interaction_mode(requested_interaction)
        supported_modes = [
            normalize_interaction_mode(mode)
            for mode in self.metadata.supported_interaction_modes
        ]
        if (
            normalized_interaction_mode != "default"
            and normalized_interaction_mode not in supported_modes
        ):
            raise ValueError(
                "interaction_mode must be one of: default, "
                + ", ".join(supported_modes)
        )
        self.interaction_mode = normalized_interaction_mode
        self.harness_mode = self._normalize_harness_mode(harness_mode)
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
        with tempfile.TemporaryDirectory(prefix="gbqa-harbor-upload-") as temp_dir:
            staging_root = Path(temp_dir)
            agent_upload_dir = self._stage_agent_upload_dir(
                source_dir=repo_root / "agent",
                staging_root=staging_root,
            )
            gbqa_upload_dir = self._stage_package_upload_dir(
                source_dir=repo_root / "gbqa",
                staging_root=staging_root,
            )
            await environment.upload_dir(agent_upload_dir, self._REMOTE_AGENT_DIR)
            await environment.upload_dir(gbqa_upload_dir, self._REMOTE_GBQA_DIR)
        await self._ensure_software_release(environment)

        config_text = render_agent_config(
            metadata=self.metadata,
            interaction_mode=self.interaction_mode,
            harness_mode=self.harness_mode,
            max_steps=self.max_steps,
            report_output_dir=f"{self.metadata.agent_artifact_dir}/raw_reports",
            prompt_dir=f"{self._REMOTE_AGENT_DIR}/prompts",
            screenshot_dir=f"{self.metadata.agent_artifact_dir}/artifacts/screenshots",
        )
        await self._write_remote_file(
            environment,
            self._REMOTE_CONFIG_PATH,
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

        await self._start_software_service(environment)
        await self._wait_for_service(environment)
        if "computer" in self._enabled_interaction_modes():
            await self._start_computer_use_services(environment)
            await self._wait_for_computer_server(environment)
            await self._open_computer_use_frontend(environment)

        run_command = (
            f"cd {shlex.quote(self._REMOTE_AGENT_DIR)} && "
            f"{shlex.quote(self._REMOTE_PYTHON)} run_agent.py "
            f"--task {shlex.quote(self.metadata.task_slug)} "
            f"--config {shlex.quote(self._REMOTE_CONFIG_PATH)} "
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
                "interaction_profile": self.interaction_mode,
                "interaction_mode": (
                    self.metadata.default_interaction_mode
                    if self.interaction_mode == "default"
                    else self.interaction_mode
                ),
                "harness_mode": self.harness_mode,
                "enabled_interaction_modes": self._enabled_interaction_modes(),
                "artifact_dir": self.metadata.agent_artifact_dir,
                "agent_return_code": getattr(result, "return_code", None),
            }

        if getattr(result, "return_code", 1) != 0:
            raise RuntimeError(
                "GBQA agent failed with return code "
                f"{result.return_code}. See {self.metadata.agent_artifact_dir}/gbqa-agent.stderr."
            )

    @classmethod
    def _stage_agent_upload_dir(
        cls,
        *,
        source_dir: Path,
        staging_root: Path,
    ) -> Path:
        target_dir = staging_root / "agent"
        target_dir.mkdir(parents=True, exist_ok=True)
        for relative in cls._AGENT_UPLOAD_ITEMS:
            source = source_dir / relative
            target = target_dir / relative
            if source.is_dir():
                shutil.copytree(source, target, ignore=cls._UPLOAD_IGNORE)
            elif source.is_file():
                shutil.copy2(source, target)
            else:
                raise FileNotFoundError(f"Missing agent upload item: {source}")
        return target_dir

    @classmethod
    def _stage_package_upload_dir(
        cls,
        *,
        source_dir: Path,
        staging_root: Path,
    ) -> Path:
        target_dir = staging_root / "gbqa"
        shutil.copytree(source_dir, target_dir, ignore=cls._UPLOAD_IGNORE)
        return target_dir

    @classmethod
    def build_run_command(
        cls,
        *,
        max_steps: int,
        task_slug: str = "dark-castle",
        config_path: str = "/sandbox/runtime/config.toml",
        remote_agent_dir: str = "/sandbox/agent",
        python_path: str = "/opt/venv/bin/python",
        artifact_dir: str = "/logs/agent/gbqa",
    ) -> str:
        """Return the sandbox command used to run the legacy QA loop."""

        return (
            f"cd {shlex.quote(remote_agent_dir)} && "
            f"{shlex.quote(python_path)} run_agent.py "
            f"--task {shlex.quote(task_slug)} "
            f"--config {shlex.quote(config_path)} "
            f"--max-steps {int(max_steps)} "
            f"> {artifact_dir}/gbqa-agent.stdout "
            f"2> {artifact_dir}/gbqa-agent.stderr"
        )

    @staticmethod
    def _repo_root() -> Path:
        return Path(__file__).resolve().parents[2]

    @classmethod
    def _load_task_metadata(cls, metadata_path: str | None = None) -> GBQAMetadata:
        configured = metadata_path or os.environ.get("GBQA_TASK_METADATA_PATH")
        if configured:
            path = Path(configured)
            if not path.is_absolute():
                path = cls._repo_root() / path
            return load_gbqa_metadata(path)
        return load_gbqa_metadata(
            cls._repo_root() / cls._DEFAULT_TASK_METADATA_RELATIVE
        )

    @staticmethod
    def _normalize_harness_mode(value: str) -> str:
        mode = str(value or "minimal").strip().lower().replace("-", "_")
        if mode == "bare":
            mode = "minimal"
        if mode not in {"minimal", "full"}:
            raise ValueError("harness_mode must be one of: minimal, full")
        return mode

    def _enabled_interaction_modes(self) -> list[str]:
        if self.interaction_mode == "default":
            return [
                normalize_interaction_mode(mode)
                for mode in self.metadata.supported_interaction_modes
            ]
        return [self.interaction_mode]

    async def _ensure_software_release(self, environment: BaseEnvironment) -> None:
        software_dir = shlex.quote(self.metadata.software_install_dir)
        ready_path = shlex.quote(
            f"{self.metadata.software_install_dir.rstrip('/')}/"
            f"{self.metadata.software_ready_path.lstrip('/')}"
        )
        archive_url = shlex.quote(self.metadata.software_archive_url)
        command = (
            f"if [ ! -e {ready_path} ]; then "
            f"rm -rf {software_dir} && mkdir -p {software_dir} && "
            f"curl -fsSL {archive_url} | tar -xz --strip-components=1 -C {software_dir}; "
            "fi; "
            f"test -e {ready_path}"
        )
        result = await environment.exec(command=command, timeout_sec=300)
        if getattr(result, "return_code", 1) != 0:
            raise RuntimeError(
                "Failed to prepare software release "
                f"{self.metadata.software_selected_version} from "
                f"{self.metadata.software_repository}."
            )

    async def _start_software_service(self, environment: BaseEnvironment) -> None:
        start_command = self._format_runtime_template(
            self.metadata.runtime_start_command,
            quote_values=True,
        ).strip()
        if not start_command:
            raise RuntimeError(
                "Task metadata must define runtime.startup.command for Harbor execution."
            )
        workdir = shlex.quote(
            self._format_runtime_template(
                self.metadata.runtime_start_workdir,
                quote_values=False,
            )
        )
        stdout_path = self._format_runtime_template(
            self.metadata.runtime_stdout_path,
            quote_values=False,
        )
        pid_file = self._format_runtime_template(
            self.metadata.runtime_pid_file,
            quote_values=False,
        )
        stdout_dir = shlex.quote(str(Path(stdout_path).parent))
        command = (
            f"mkdir -p {self.metadata.agent_artifact_dir} /logs/runtime {stdout_dir} && "
            f"cd {workdir} && "
            f"{start_command} "
            f"> {shlex.quote(stdout_path)} "
            "2>&1 < /dev/null && "
            f"echo started > {shlex.quote(pid_file)}"
        )
        result = await environment.exec(command=command, timeout_sec=30)
        if getattr(result, "return_code", 1) != 0:
            raise RuntimeError(f"Failed to start task service for {self.metadata.task_id}.")

    async def _wait_for_service(self, environment: BaseEnvironment) -> None:
        url = f"{self.metadata.service_origin}{self.metadata.service_health_path}"
        stdout_path = self._format_runtime_template(
            self.metadata.runtime_stdout_path,
            quote_values=False,
        )
        command = (
            "for i in $(seq 1 60); do "
            f"curl -fsS {shlex.quote(url)} >/dev/null && exit 0; "
            "sleep 1; "
            "done; "
            f"cat {shlex.quote(stdout_path)} "
            "|| true; "
            "exit 1"
        )
        result = await environment.exec(command=command, timeout_sec=90)
        if getattr(result, "return_code", 1) != 0:
            raise RuntimeError(f"Task service did not become healthy: {url}")

    async def _start_computer_use_services(self, environment: BaseEnvironment) -> None:
        adapter = self.metadata.interaction_adapter("computer")
        display = adapter.get("display", {})
        if not isinstance(display, dict):
            display = {}
        width = int(display.get("width", 1280))
        height = int(display.get("height", 720))
        api_port = self._port_from_url(self.metadata.computer_use_server_url, 8030)
        url = self.metadata.computer_use_server_url
        startup_log = f"{self.metadata.agent_artifact_dir}/cua-startup.log"
        command = (
            f"mkdir -p {self.metadata.agent_artifact_dir} && "
            f"{{ "
            "echo '== preflight =='; "
            "date; "
            "echo 'sandbox:'; ls -la /sandbox || true; "
            "echo 'logs:'; ls -la /logs || true; "
            "echo 'ports:'; (ss -lntp || netstat -lntp || true); "
            f"}} > {startup_log} 2>&1; "
            f"(curl -fsS {shlex.quote(url)} >/dev/null || "
            f"curl -fsS {shlex.quote(url + '/docs')} >/dev/null) && exit 0; "
            "export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin; "
            "export DISPLAY=:1; "
            f"export API_PORT={api_port}; "
            f"export VNC_RESOLUTION={width}x{height}; "
            "test -x /usr/local/bin/start-vnc.sh || "
            f"{{ echo 'missing required computer-use runtime: "
            f"/usr/local/bin/start-vnc.sh' | tee -a {startup_log} >&2; "
            f"exit 1; }}; "
            f"setsid -f /usr/local/bin/start-vnc.sh "
            f"> {self.metadata.agent_artifact_dir}/cua-vnc.log 2>&1 < /dev/null || true; "
            "test -x /usr/local/bin/start-novnc.sh || "
            f"{{ echo 'missing required computer-use runtime: "
            f"/usr/local/bin/start-novnc.sh' | tee -a {startup_log} >&2; "
            f"exit 1; }}; "
            f"setsid -f /usr/local/bin/start-novnc.sh "
            f"> {self.metadata.agent_artifact_dir}/cua-novnc.log 2>&1 < /dev/null || true; "
            "test -x /usr/local/bin/start-computer-server.sh || "
            f"{{ echo 'missing required computer-use runtime: "
            f"/usr/local/bin/start-computer-server.sh' | tee -a {startup_log} >&2; "
            f"exit 1; }}; "
            f"setsid -f /usr/local/bin/start-computer-server.sh "
            f"> {self.metadata.agent_artifact_dir}/cua-computer-server.log 2>&1 < /dev/null || true"
        )
        result = await environment.exec(command=command, timeout_sec=30)
        if getattr(result, "return_code", 1) != 0:
            raise RuntimeError(
                "Failed to start Cua computer-use services.\n"
                + COMPUTER_USE_ENVIRONMENT_HINT
                + "\n"
                + self._format_exec_output(result)
            )

    async def _wait_for_computer_server(self, environment: BaseEnvironment) -> None:
        url = self.metadata.computer_use_server_url
        command = (
            "for i in $(seq 1 60); do "
            f"curl -fsS {shlex.quote(url)} >/dev/null && exit 0; "
            f"curl -fsS {shlex.quote(url + '/docs')} >/dev/null && exit 0; "
            "sleep 1; "
            "done; "
            "echo '== processes =='; ps -ef || true; "
            "echo '== ports =='; (ss -lntp || netstat -lntp || true); "
            f"for log in "
            f"{self.metadata.agent_artifact_dir}/cua-startup.log "
            f"{self.metadata.agent_artifact_dir}/cua-vnc.log "
            f"{self.metadata.agent_artifact_dir}/cua-novnc.log "
            f"{self.metadata.agent_artifact_dir}/cua-computer-server.log; do "
            "echo \"== $log ==\"; sed -n '1,220p' \"$log\" 2>/dev/null || true; "
            "done; "
            "exit 1"
        )
        result = await environment.exec(command=command, timeout_sec=90)
        if getattr(result, "return_code", 1) != 0:
            raise RuntimeError(
                f"Cua computer-server did not become healthy at {url}.\n"
                + COMPUTER_USE_ENVIRONMENT_HINT
                + "\n"
                + self._format_exec_output(result)
            )

    async def _open_computer_use_frontend(self, environment: BaseEnvironment) -> None:
        url = self.metadata.service_frontend_url
        command = (
            f"mkdir -p {self.metadata.agent_artifact_dir} && "
            "export DISPLAY=:1; "
            "export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin; "
            "browser=$(command -v firefox || command -v chromium || "
            "command -v chromium-browser || command -v google-chrome || true); "
            "if [ -z \"$browser\" ]; then echo 'No GUI browser found' >&2; exit 1; fi; "
            f"setsid -f \"$browser\" --new-window {shlex.quote(url)} "
            f"> {self.metadata.agent_artifact_dir}/cua-browser.log 2>&1 < /dev/null"
        )
        result = await environment.exec(command=command, timeout_sec=30)
        if getattr(result, "return_code", 1) != 0:
            raise RuntimeError(
                f"Failed to open computer-use frontend at {url}.\n"
                + COMPUTER_USE_ENVIRONMENT_HINT
                + "\n"
                + self._format_exec_output(result)
            )
        await environment.exec(command="sleep 2", timeout_sec=5)

    @staticmethod
    def _format_exec_output(result: Any) -> str:
        stdout = str(getattr(result, "stdout", "") or "").strip()
        stderr = str(getattr(result, "stderr", "") or "").strip()
        parts = []
        if stdout:
            parts.append("stdout:\n" + stdout)
        if stderr:
            parts.append("stderr:\n" + stderr)
        return "\n".join(parts) or "No command output captured."

    @staticmethod
    def _port_from_url(url: str, default: int) -> int:
        parsed = urlparse(url)
        if parsed.port is not None:
            return int(parsed.port)
        return default

    async def _export_artifacts(self, environment: BaseEnvironment) -> None:
        export_commands = []
        for item in self.metadata.runtime_artifact_exports:
            source = shlex.quote(
                self._format_runtime_template(
                    item["source"],
                    quote_values=False,
                )
            )
            destination = shlex.quote(
                self._format_runtime_template(
                    item["destination"],
                    quote_values=False,
                )
            )
            export_commands.append(
                f"mkdir -p {destination} && cp -a {source} {destination} 2>/dev/null || true"
            )
        runtime_exports = "; ".join(export_commands)
        if runtime_exports:
            runtime_exports += "; "
        command = (
            f"cd {self._REMOTE_ROOT} && "
            f"{runtime_exports}"
            f"mkdir -p {self.metadata.agent_artifact_dir}/artifacts/runtime_logs && "
            "cp -a /logs/runtime/. "
            f"{self.metadata.agent_artifact_dir}/artifacts/runtime_logs/ "
            "2>/dev/null || true; "
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

    def _format_runtime_template(
        self,
        template: str,
        *,
        quote_values: bool,
    ) -> str:
        values: dict[str, Any] = {
            "task_id": self.metadata.task_id,
            "task_slug": self.metadata.task_slug,
            "software_install_dir": self.metadata.software_install_dir,
            "service_host": self.metadata.service_host,
            "service_port": self.metadata.service_port,
            "service_origin": self.metadata.service_origin,
            "agent_artifact_dir": self.metadata.agent_artifact_dir,
            "verifier_artifact_dir": self.metadata.verifier_artifact_dir,
            "python": self._REMOTE_PYTHON,
        }
        if quote_values:
            values = {
                key: shlex.quote(str(value))
                for key, value in values.items()
            }
        return str(template).format(**values)

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
        # CLI model selection (e.g. harbor run -m <model>) takes precedence.
        if self.model_name:
            env["MODEL_NAME"] = self.model_name
        for key in ("API_KEY", "BASE_URL", "MODEL_NAME"):
            if key not in env:
                value = self._extra_env.get(key) or os.environ.get(key)
                if value:
                    env[key] = value
        env.setdefault("BASE_URL", DEFAULT_BASE_URL)
        return env

    @staticmethod
    def _validate_runtime_env(env: dict[str, str]) -> None:
        missing = [
            key for key in ("API_KEY", "MODEL_NAME") if not env.get(key)
        ]
        if missing:
            raise RuntimeError(
                "GBQAHarborAgent requires these env vars for Harbor runs: "
                + ", ".join(missing)
            )
