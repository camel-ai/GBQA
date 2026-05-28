from __future__ import annotations

import os
import shlex

from ..models import EnvironmentVerificationResult, ProbeResult, SubEnvironmentCandidate, VerificationArtifacts


class DaytonaEnvironmentVerifier:
    """Run a conservative remote smoke probe in a Daytona sandbox."""

    name = "daytona"

    def __init__(self, *, timeout: int = 900) -> None:
        self.timeout = timeout

    def verify(self, candidate: SubEnvironmentCandidate) -> EnvironmentVerificationResult:
        release_pair = candidate.release_pair
        baseline = release_pair.baseline_release if release_pair else ""
        deployment_method = _deployment_method(candidate)
        if not release_pair:
            return self._failed(
                candidate,
                baseline=baseline,
                deployment_method=deployment_method,
                reason="candidate has no selected release pair",
            )
        if not os.getenv("DAYTONA_API_KEY"):
            return self._failed(
                candidate,
                baseline=baseline,
                deployment_method=deployment_method,
                reason="DAYTONA_API_KEY is required for Daytona verification.",
            )

        try:
            from daytona import Daytona, DaytonaConfig
        except Exception as exc:  # pragma: no cover - dependency environment guard
            return self._failed(
                candidate,
                baseline=baseline,
                deployment_method=deployment_method,
                reason=f"failed to import Daytona SDK: {exc}",
            )

        daytona = Daytona(DaytonaConfig(api_key=os.getenv("DAYTONA_API_KEY")))
        sandbox = None
        try:
            sandbox = daytona.create(timeout=self.timeout)
            script = self._probe_script(candidate)
            response = sandbox.process.exec(script, timeout=self.timeout)
            status = "passed" if int(response.exit_code) == 0 else "failed"
            failure_reason = None if status == "passed" else f"probe exited with {response.exit_code}"
            return EnvironmentVerificationResult(
                candidate_id=candidate.candidate_id,
                status=status,
                sandbox_provider=self.name,
                baseline_release=baseline,
                deployment_method=deployment_method,
                interaction_mode=candidate.kind,
                probe=ProbeResult(
                    command=script,
                    endpoint="http://127.0.0.1/health" if candidate.kind == "api" else None,
                    exit_code=int(response.exit_code),
                    http_status=None,
                ),
                artifacts=VerificationArtifacts(logs=[str(response.result)[-8000:]]),
                failure_reason=failure_reason,
            )
        except Exception as exc:
            return self._failed(
                candidate,
                baseline=baseline,
                deployment_method=deployment_method,
                reason=str(exc),
            )
        finally:
            if sandbox is not None:
                try:
                    daytona.delete(sandbox, timeout=120)
                except Exception:
                    pass

    def _failed(
        self,
        candidate: SubEnvironmentCandidate,
        *,
        baseline: str,
        deployment_method: str,
        reason: str,
    ) -> EnvironmentVerificationResult:
        return EnvironmentVerificationResult(
            candidate_id=candidate.candidate_id,
            status="failed",
            sandbox_provider=self.name,
            baseline_release=baseline,
            deployment_method=deployment_method,
            interaction_mode=candidate.kind,
            probe=ProbeResult(),
            artifacts=VerificationArtifacts(),
            failure_reason=reason,
        )

    def _probe_script(self, candidate: SubEnvironmentCandidate) -> str:
        release_pair = candidate.release_pair
        archive_url = release_pair.baseline_archive_url if release_pair else ""
        sub_path = candidate.sub_path.strip("/")
        cd_target = f"/sandbox/environment-candidate/{sub_path}" if sub_path else "/sandbox/environment-candidate"
        method = _deployment_method(candidate)
        return f"""bash -lc {shlex.quote(f'''
set -euo pipefail
mkdir -p /sandbox/environment-candidate
curl -L {shlex.quote(archive_url)} -o /tmp/candidate.tar.gz
tar -xzf /tmp/candidate.tar.gz -C /sandbox/environment-candidate --strip-components=1
cd {shlex.quote(cd_target)}
echo candidate_id={shlex.quote(candidate.candidate_id)}
echo deployment_method={method}
case {shlex.quote(method)} in
  dockerfile)
    command -v docker >/dev/null
    docker build -t gbqa-candidate .
    ;;
  compose)
    command -v docker >/dev/null
    docker compose config >/tmp/gbqa-compose-config.txt
    ;;
  makefile)
    command -v make >/dev/null
    make -n
    ;;
  package_script)
    if [ -f package.json ]; then
      command -v node >/dev/null
      node -e "JSON.parse(require('fs').readFileSync('package.json', 'utf8')); console.log('package_json_ok')"
    elif [ -f pyproject.toml ] || [ -f requirements.txt ]; then
      command -v python >/dev/null
      python --version
    else
      echo "no package script probe available"
      exit 2
    fi
    ;;
  *)
    echo "unsupported deployment method"
    exit 2
    ;;
esac
''')}"""


def _deployment_method(candidate: SubEnvironmentCandidate) -> str:
    if candidate.signals.has_dockerfile:
        return "dockerfile"
    if candidate.signals.has_compose:
        return "compose"
    if candidate.signals.has_makefile:
        return "makefile"
    if candidate.deployment_files:
        return "package_script"
    return "inferred"
