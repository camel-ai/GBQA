# Hub Software Project Sourcing

`hub/sourcing` is the Hub-side pipeline for discovering source-code-available software projects from GitHub, filtering them into realistic software-engineering environments, extracting release-based bug evidence, and publishing metadata-only artifacts for later sandbox import and QA-agent execution.

## Overview

The pipeline is organized into five stages:

1. `discover`
  Fetch GitHub repository metadata, releases, tags, issues, pull requests, contributor signals, and architecture hints.
2. `score`
  Apply hard filters and compute a weighted selection score.
3. `select`
  Keep only repositories that pass all hard filters, resolve a valid baseline/fix release pair, and meet the minimum score.
4. `publish`
  Write machine-readable catalog artifacts under `hub/environment/`.
5. `run`
  Execute the full pipeline end to end.

The pipeline stores metadata only. It does not clone repositories or import source code into a sandbox. The published manifests preserve the GitHub links, release pointers, and handoff hints needed for those later stages.

## CAMEL Alignment

This package follows the same implementation principles already used by the repo's CAMEL-backed agent modules:

- typed, focused models
- small helpers with narrow responsibilities
- Google-style docstrings
- concise comments only where needed
- API-oriented documentation

When CAMEL already provides a useful GitHub component, the pipeline reuses it instead of rebuilding an equivalent abstraction.

Current CAMEL reuse:

- optional integration with `camel.toolkits.GithubToolkit`
- direct reuse of local CAMEL/Pydantic coding conventions already present in `agent/src`

The CAMEL GitHub toolkit is used opportunistically for repository file-path discovery. If the local environment does not have the toolkit's optional GitHub dependency installed, the pipeline falls back to the GitHub tree API automatically.

## Package Layout

- `cli.py`
Command-line entrypoint with `auth`, `discover`, `score`, `select`, `publish`, and `run`.
- `pipeline.py`
End-to-end orchestration and publication logic.
- `models.py`
Typed dataclasses for software-project candidates, release pairs, engagement metrics, manifests, and dedupe records.
- `providers/github.py`
GitHub-only discovery provider for software projects.
- `camel_github.py`
Optional CAMEL `GithubToolkit` adapter.
- `scoring.py`
Hard-filter checks and weighted scoring.
- `pairing.py`
Baseline/fix release-pair selection.
- `issue_verification.py`
GitHub issue/PR closure checks for fix releases (release notes plus compare-range commits).
- `ground_truth.py`
Release-note-to-bug-ground-truth generation with optional taxonomy tagging.
- `structured_outputs.py`
Pydantic schemas for optional taxonomy annotations.
- `state.py`
Persisted dedupe ledger support.
- `fetcher.py`
HTTP abstraction used by live runs and tests.
- `utils.py`
Shared normalization, architecture inference, and formatting helpers.

## Filtering Rules

Each repository must satisfy these hard requirements before promotion:

- public source is available on GitHub
- release history is available
- at least one release contains bug-fix evidence in release notes
- a recoverable baseline release exists immediately before a qualifying fix release
- **tracked GitHub issues and pull requests referenced for the fix release are closed**
  (see [Issue and PR closure verification](#issue-and-pr-closure-verification))
- the repository exposes a usable interaction surface inferred from metadata:
`computer_use`, `api_cli`, or `mixed`
- the repository has a minimum workability/activity level

If the pipeline runs **without** an HTTP fetcher (for example in a constrained test harness),
issue verification is skipped and this check is not applied.

The weighted score is computed out of 100:

- source access: 25
- release evidence: 30
- engineering activity: 20
- architecture fit: 15
- metadata quality: 10

## Issue and PR closure verification

After a valid baseline/fix release pair is selected, the pipeline validates that fixes are
**tracked on GitHub** and reach a **closed** state, similar in spirit to SWE-bench’s use of
real issue/PR lifecycles.

1. **Release text**  
   Collect candidate issue and pull-request numbers from the **fix release** title and body:
   `#123` references and `github.com/<owner>/<repo>/issues/<n>` or
   `.../pull/<n>` URLs.

2. **Commits between releases**  
   Call the GitHub compare API for `baseline_tag...fix_tag` and parse the same patterns from
   each commit message in that range (release → commits → issues).

3. **Closure check**  
   For every unique number gathered in steps 1–2, fetch `GET /repos/{owner}/{repo}/issues/{n}`.
   The GitHub issues endpoint covers both issues and pull requests. The check **passes** only
   when there is **at least one** referenced number and **every** referenced number has
   `state == "closed"`.

If no issue or PR numbers can be extracted, verification **fails** with
`no_issue_references_for_verification`. If any referenced item is not closed, verification
fails with `open_tracked_issues`. If an issue request errors, verification fails with
`issue_metadata_fetch_failed`.

Hard-filter rejection uses the code `tracked_issues_not_closed` whenever this verification
does not succeed (and a fetcher was available).

The structured result is stored on the candidate as `extra["issue_verification"]` and copied
into published manifests as `issue_verification` when present.

## Published Metadata

Each promoted software-project manifest includes:

- project identity: repo full name, owner, default branch, clone URL, GitHub URL
- project context: About text, topics, languages
- activity and workability: stars, forks, issues, pull requests, contributors, release cadence, recency
- architecture hints: `has_frontend`, `has_backend`, `has_database`, `interaction_mode`,
`has_tracked_issue_closure`
- selected release pair: baseline version, fix version, recovery method, patch timestamp
- release evidence: release notes URL, artifact URLs
- optional: `issue_verification` payload (referenced numbers, per-number state, compare stats)
- downstream hints: clone hint and sandbox hint
- dedupe key for automation-safe reruns

## Bug Ground Truth and Taxonomy

The pipeline uses release notes as evidential ground truth for bugs in the immediately previous version:

- the latest release is treated as the fixing release by default
- the immediately previous release is treated as the buggy baseline
- only bug-fix items from the latest release notes are converted into bug entries
- feature additions and other non-bug release-note items are ignored

Default release-pair strategy:

- use the latest release as the primary signal
- inspect the latest release notes and keep only bug-fix entries
- use the release immediately before the latest release as the baseline environment
- preserve pull-request links from the release notes when they are available

Core bug fields remain backward-compatible:

- `id`
- `bug_type`
- `difficulty`
- `minimal_reproduction`
- `observed_fault`

Additional metadata is attached when available:

- `title`
- `description`
- `source_patch_url`
- `source_excerpt`
- `extraction_confidence`
- `primary_category`
- `secondary_labels`
- `taxonomy_context`
- `taxonomy_confidence`
- `taxonomy_source`

First-pass taxonomy categories:

- `frontend`
- `backend`
- `database`
- `safety`
- `other`

Optional LLM-based taxonomy tagging is additive only. Deterministic extraction remains the primary behavior.

## Automation and Deduplication

The pipeline persists a ledger in `hub/environment/index.json`.

Deduplication key:

- `repo_full_name + selected_release_id`

This means:

- reruns skip exact repository/release pairs that were already saved
- the same repository can still be promoted later if a new valid release pair appears

## CLI Usage

Run from the repository root:

```bash
python -m hub.sourcing.cli auth --providers github
python -m hub.sourcing.cli run --providers github --limit 5 --output-dir hub/environment
python -m hub.sourcing.cli run --providers github --limit 5 --minimum-selected 3
```

Subcommands:

```bash
python -m hub.sourcing.cli auth --providers github
python -m hub.sourcing.cli discover --providers github --limit 5
python -m hub.sourcing.cli score --output-dir hub/environment
python -m hub.sourcing.cli select --output-dir hub/environment --minimum-score 60
python -m hub.sourcing.cli publish --output-dir hub/environment
python -m hub.sourcing.cli run --providers github --limit 5 --minimum-score 60
```

Useful flags:

- `--allow-partial`
Continue when a provider fails.
- `--max-candidates`
Cap the number of promoted projects.
- `--minimum-selected`
During `run`, keep retrieving additional GitHub search pages until at least this
many projects are selected or discovery is exhausted. This flag applies to
`run` only, must be at least `1`, and cannot be greater than `--max-candidates`
when both are provided.
- `--output-dir`
Change the catalog destination.

Selection behavior:

- `--limit` controls the GitHub page size used for each discovery round.
- `--minimum-selected` controls how many promoted environments the `run` command
should try to reach before stopping.
- if GitHub has no more matching repositories, the run stops even if the target
selected count was not reached.

## Authentication

The CLI supports an interactive GitHub credential flow.

When you run a networked command such as `auth`, `discover`, or `run`:

- saved keys from `hub/sourcing/.env` are loaded automatically
- if no token is configured, the CLI can walk you through token setup
- if GitHub returns `403 rate limit exceeded`, the CLI prompts for a token and retries
- if GitHub returns `401 Bad credentials`, the CLI prompts you to replace the token and retries

GitHub API edge cases:

- some very large repositories return `403` on the contributors endpoint with a
message that the contributor list is too large to compute
- this does not stop discovery; the pipeline falls back to incomplete contributor
metadata for that repository and continues scoring it
- these cases are marked in candidate metadata with
`extra["contributors_metadata_complete"] = false`

### Interactive setup

```bash
python -m hub.sourcing.cli auth --providers github
```

### Manual file input

Copy `.env.example` to `hub/sourcing/.env`, then fill in:

```env
GITHUB_TOKEN=ghp_your_token_here
OPENAI_API_KEY=your_openai_key_here
OPENAI_MODEL=gpt-5.4
OPENAI_BASE_URL=https://api.openai.com/v1
```

## How to Get a GitHub Token

Official docs:

- [Managing your personal access tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)

Suggested process:

1. Sign in to GitHub.
2. Open `Settings`.
3. Open `Developer settings`.
4. Open `Personal access tokens`.
5. Prefer a fine-grained token when possible.
6. Create a token that can read public repository metadata.
7. Copy the token once and paste it into the CLI or `hub/sourcing/.env`.

## Output Layout

Published artifacts are written under `hub/environment/` by default:

```text
hub/environment/
|- candidates.jsonl
|- index.json
`- selected/
   `- <environment_id>/
      |- manifest.json
      |- provenance.json
      `- bugs/
         `- <release_id>.json
```

## Tests

Fixture-backed tests live under `hub/tests/sourcing`.

Run them with:

```bash
python -m unittest discover -s hub/tests/sourcing -p "test_*.py" -v
```

The tests cover:

- GitHub metadata extraction
- architecture inference
- release-pair recovery
- GitHub issue/PR closure verification
- filtering and rejection rules
- dedupe behavior
- bug-ground-truth compatibility with taxonomy metadata
- end-to-end catalog publication

