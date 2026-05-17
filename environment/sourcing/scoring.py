from __future__ import annotations

from .models import RankingScore, SubEnvironmentCandidate


def score_candidate(candidate: SubEnvironmentCandidate) -> RankingScore:
    reproducibility = _bounded(
        0.4 * bool(candidate.release_pair)
        + 0.3 * candidate.signals.linux_candidate
        + 0.2 * bool(candidate.repository.license)
        + 0.1 * candidate.signals.has_lockfile
    )
    interaction_surface = _bounded(
        0.6 * candidate.signals.has_api_surface
        + 0.5 * candidate.signals.has_cli_surface
        + 0.2 * candidate.signals.has_browser_surface
    )
    bug_benchmark_potential = _bounded(
        0.7 * candidate.signals.bugfix_evidence
        + 0.3 * bool(candidate.release_pair)
    )
    oss_health = _bounded(
        min(candidate.repository.stars / 500.0, 0.5)
        + min(candidate.repository.forks / 100.0, 0.2)
        + min(candidate.repository.open_issues / 200.0, 0.2)
        + 0.1 * bool(candidate.repository.topics)
    )
    deployment_clarity = _bounded(
        0.45 * candidate.signals.has_dockerfile
        + 0.35 * candidate.signals.has_compose
        + 0.2 * candidate.signals.has_makefile
        + 0.2 * bool(candidate.deployment_files)
    )
    domain_diversity = _bounded(0.4 + min(len(candidate.tags.domain), 3) * 0.2)
    resource_fit = 1.0
    total = (
        0.25 * reproducibility
        + 0.20 * interaction_surface
        + 0.15 * bug_benchmark_potential
        + 0.15 * oss_health
        + 0.10 * deployment_clarity
        + 0.10 * domain_diversity
        + 0.05 * resource_fit
    ) * 100.0
    return RankingScore(
        reproducibility=round(reproducibility, 4),
        interaction_surface=round(interaction_surface, 4),
        bug_benchmark_potential=round(bug_benchmark_potential, 4),
        oss_health=round(oss_health, 4),
        deployment_clarity=round(deployment_clarity, 4),
        domain_diversity=round(domain_diversity, 4),
        resource_fit=round(resource_fit, 4),
        total=round(total, 2),
    )


def _bounded(value: float) -> float:
    return max(0.0, min(float(value), 1.0))
