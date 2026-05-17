# GBQA Environment Preparation

`environment/` is the offline preparation system for finding, validating, reviewing, and exporting real GitHub software environments into GBQA benchmark tasks.

Only generated and approved task packages under `gbqa/tasks/` participate in benchmark execution.

## Pipeline

```text
GitHub search
  -> repository candidates
  -> sub-environment detection
  -> static filtering
  -> static ranking
  -> Daytona deployment verification
  -> human review
  -> approved task seeds
  -> gbqa/tasks/<task-id>
```

## Commands

Run deterministic discovery, filtering, scoring, and ranking:

```bash
export GITHUB_TOKEN=...
python -m environment.sourcing.cli run \
  --provider github \
  --query "archived:false fork:false stars:>=10 mirror:false" \
  --limit 500 \
  --top-k 100 \
  --output-dir environment/catalog/runs/dev
```

The CLI also loads the repository root `.env`, so `GITHUB_TOKEN` can be stored there for local runs.

## Persistent Resume Ledger

Sourcing uses a persistent local ledger by default. The default state directory is:

```text
environment/catalog/state/
  repositories.jsonl
  release_pairs.jsonl
  sub_environments.jsonl
  verifications.jsonl
```

`run` defaults to `--resume`. This means the pipeline reads `repositories.jsonl`, skips GitHub repositories that have already been processed, and continues paging through GitHub search results until it finds new repositories or reaches `--limit`.

Equivalent explicit command:

```bash
python -m environment.sourcing.cli run \
  --provider github \
  --query "archived:false fork:false stars:>=10 mirror:false" \
  --limit 500 \
  --top-k 100 \
  --output-dir environment/catalog/runs/dev \
  --state-dir environment/catalog/state \
  --resume
```

Use `--no-resume` when you intentionally want to reprocess previously seen repositories:

```bash
python -m environment.sourcing.cli run \
  --provider github \
  --query "archived:false fork:false stars:>=10 mirror:false" \
  --limit 500 \
  --top-k 100 \
  --output-dir environment/catalog/runs/dev-refresh \
  --no-resume
```

Use a separate ledger for experiments that should not affect the main sourcing history:

```bash
python -m environment.sourcing.cli run \
  --provider github \
  --query "archived:false fork:false stars:>=10 mirror:false" \
  --limit 100 \
  --top-k 50 \
  --output-dir environment/catalog/runs/experiment-001 \
  --state-dir environment/catalog/state-experiment
```

Current resume granularity:

- Repository key: `github:<owner>/<repo>`.
- Release-pair key: `github:<owner>/<repo>::<baseline>::<fixed>`.
- Sub-environment key: `github:<owner>/<repo>::<baseline>::<fixed>::<sub_path>`.
- Verification key: `<sub_environment_key>::<provider>::<probe_version>`.

Important behavior:

- Discovery resume is currently repository-level. If a repo is already in `repositories.jsonl`, the default run skips it.
- To refresh a repo for new releases, run with `--no-resume`, use a separate `--state-dir`, or remove the specific state rows.
- `verify` also defaults to `--resume`. If a candidate/provider/probe-version result exists in `verifications.jsonl`, the verifier reuses it instead of running Daytona or fake verification again.
- `environment/catalog/state/` is local generated state and is ignored by git.

Run verification over ranked candidates:

```bash
python -m environment.sourcing.cli verify \
  --input environment/catalog/runs/dev/ranked.jsonl \
  --provider daytona \
  --top-k 20
```

Force a fresh verification pass:

```bash
python -m environment.sourcing.cli verify \
  --input environment/catalog/runs/dev/ranked.jsonl \
  --provider daytona \
  --top-k 20 \
  --no-resume
```

Use the fake verifier for local test runs:

```bash
python -m environment.sourcing.cli verify \
  --input environment/catalog/runs/dev/ranked.jsonl \
  --provider fake \
  --top-k 20
```

Generate task packages from approved review output:

```bash
python -m environment.export.cli generate \
  --input environment/catalog/runs/dev/approved_task_seeds.jsonl \
  --output gbqa/tasks
```

## Human Review

The review app lives in `environment/review/`.

```bash
pnpm --dir environment/review install
pnpm --dir environment/review dev
```

The app imports ranked/verified JSONL files into SQLite, lets reviewers accept or reject candidates, and exports `approved_task_seeds.jsonl`.

## Current Scope

- GitHub-only discovery.
- Linux-first deployment signals.
- API and CLI candidates are prioritized.
- Browser-only and computer-use environments are tagged for future work.
- Generic Daytona verification is represented by a stable interface; candidate-specific build and probe execution will be expanded after the first deterministic sourcing loop is stable.
