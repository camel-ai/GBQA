# Hub Sourcing

`hub/sourcing` is the Hub-side pipeline for discovering candidate games from open channels, scoring them against GBQA selection rules, resolving a recoverable pre-patch version pair, and publishing Hub-compatible metadata plus bug ground truth.

## What It Does

The pipeline is organized into five stages:

1. `discover`
   Fetch candidate metadata from GitHub, itch.io, and Steam.
2. `score`
   Apply hard filters and compute a fixed weighted score.
3. `select`
   Keep only candidates that pass all hard filters, resolve a valid version pair, classify as `medium` complexity, and meet the minimum score.
4. `publish`
   Write machine-readable catalog artifacts under `hub/catalog/`.
5. `run`
   Execute the full pipeline end to end.

## Package Layout

- `cli.py`
  Command-line entrypoint with `discover`, `score`, `select`, `publish`, and `run`.
- `pipeline.py`
  End-to-end orchestration and publication logic.
- `models.py`
  Typed dataclasses for candidates, versions, patches, manifests, scores, and ground-truth bundles.
- `providers/`
  Source-specific adapters for GitHub, itch.io, and Steam.
- `scoring.py`
  Hard-filter checks, complexity classification, and weighted scoring.
- `pairing.py`
  Provider-aware baseline/fix version pairing.
- `ground_truth.py`
  Automatic patch-note segmentation and Hub-compatible bug JSON generation.
- `fetcher.py`
  Network abstraction used by live providers and frozen-fixture tests.
- `utils.py`
  Shared text, version, hashing, and normalization helpers.

## Selection Rules

Every candidate is checked against these hard requirements before promotion:

- free access
- public source or public historical-build access
- explicit version trail
- official patch notes
- runnable on a local machine
- no launcher/DRM/account requirement that blocks archival replay

Scores are computed out of 100 with fixed weights:

- access and licensing: 25
- version and patch-note quality: 25
- historical build recoverability: 20
- complexity fit: 15
- maintenance cadence: 10
- documentation quality: 5

Only `medium` complexity candidates are accepted by default. `low` is used for trivial or jam-scale projects with weak system depth or release history. `high` is used for operationally heavy or replay-hostile projects such as multiplayer, anti-cheat, or launcher-bound games.

## Provider Notes

### GitHub

- Uses repository search, releases, and tags.
- Prefers adjacent release pairs, then tag-based fallbacks.
- Works best for open-source games with release assets or recoverable source archives.

### itch.io

- Uses the public free-games RSS feed for discovery.
- Scrapes the game page for metadata, source links, archives, and devlogs.
- Promotes only when there is a public source repo or recoverable historical build access.

### Steam

- Uses `IStoreService.GetAppList` for discovery and `ISteamNews.GetNewsForApp` for patch history.
- Requires `STEAM_WEB_API_KEY`.
- Steam candidates are only promotable when the store page also exposes a public source repo or recoverable archived builds.

## CLI Usage

Run from the repository root:

```bash
python -m hub.sourcing.cli auth --providers github steam
python -m hub.sourcing.cli run --providers github itch steam --limit 5 --output-dir hub/catalog
```

Subcommands:

```bash
python -m hub.sourcing.cli auth --providers github steam
python -m hub.sourcing.cli discover --providers github itch steam --limit 5
python -m hub.sourcing.cli score --output-dir hub/catalog
python -m hub.sourcing.cli select --output-dir hub/catalog --minimum-score 60
python -m hub.sourcing.cli publish --output-dir hub/catalog
python -m hub.sourcing.cli run --providers github itch steam --limit 5 --minimum-score 60
```

Useful flags:

- `--allow-partial`
  Continue when one provider fails.
- `--max-candidates`
  Cap the number of promoted candidates.
- `--output-dir`
  Change the catalog destination.

## Authentication and Manual Key Input

The CLI now supports an interactive credential flow. When you run a networked command such as `auth`, `discover`, or `run`:

- saved keys from `hub/sourcing/.env` are loaded automatically
- if a required key is missing, the CLI explains what it is for and shows setup steps
- if GitHub returns a `403 rate limit exceeded`, the CLI prompts for a token and retries
- if GitHub returns `401 Bad credentials`, the CLI prompts you to replace the saved token and retries
- entered keys can be saved locally to `hub/sourcing/.env` for future runs

You can set credentials in either of these ways.

### Option 1: interactive setup

```bash
python -m hub.sourcing.cli auth --providers github steam
```

### Option 2: manual file input

Copy `.env.example` to `hub/sourcing/.env`, then fill in the values:

```env
GITHUB_TOKEN=ghp_your_token_here
STEAM_WEB_API_KEY=your_steam_key_here
OPENAI_API_KEY=your_openai_key_here
OPENAI_MODEL=gpt-5.4
OPENAI_BASE_URL=https://api.openai.com/v1
```

`hub/sourcing/.env` is ignored by Git, so it is safe to keep local-only credentials there.

## How to Get the Keys

### GitHub token

This is strongly recommended for `github` discovery because unauthenticated requests hit rate limits quickly.

Official docs:

- [Managing your personal access tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)

Suggested process:

1. Sign in to GitHub.
2. Open `Settings`.
3. Open `Developer settings`.
4. Open `Personal access tokens`.
5. Prefer a fine-grained token when possible.
6. Create a token that can read the public repositories you want to inspect.
7. Copy the token once and paste it into the CLI or `hub/sourcing/.env`.

### Steam Web API key

This is required for `steam` discovery because the current Steam adapter uses the partner Steam Web API.

Official docs:

- [Steam Web API authentication overview](https://partner.steamgames.com/doc/webapi_overview/auth)
- [IStoreService](https://partner.steamgames.com/doc/webapi/IStoreService)

Suggested process:

1. Sign in to Steamworks with an account that can manage Web API access.
2. Open `Users & Permissions`.
3. Open `Manage Groups`.
4. Create or edit a group with Web API permissions.
5. Choose `Create WebAPI Key`.
6. Copy the generated key and paste it into the CLI or `hub/sourcing/.env`.

If you do not have Steamworks access, run without Steam:

```bash
python -m hub.sourcing.cli run --providers github itch --limit 5 --output-dir hub/catalog
```

## Output Layout

Published artifacts are written under `hub/catalog/` by default:

```text
hub/catalog/
├── candidates.jsonl
└── selected/
    └── <slug>/
        ├── manifest.json
        ├── provenance.json
        └── bugs/
            └── <patch_id>.json
```

### `candidates.jsonl`

One JSON object per discovered candidate after normalization and scoring.

### `manifest.json`

Each promoted candidate includes:

- `game_id`
- `title`
- `provider`
- `runtime_kind`
- `homepage_url`
- `source_repo_url`
- `license`
- `free_access`
- `historical_build_access`
- `selected_version_pair`
- `score`
- `score_breakdown`
- `patch_notes_url`
- `artifact_urls`
- `ground_truth_path`

### `bugs/<patch_id>.json`

The generated bug file is evaluator-compatible with the existing Hub/agent contract. Core fields are preserved:

- `id`
- `bug_type`
- `difficulty`
- `minimal_reproduction`
- `observed_fault`

Additional fields are included for traceability:

- `title`
- `description`
- `source_patch_url`
- `source_excerpt`
- `extraction_confidence`

## Ground Truth Generation

`ground_truth.py` converts patch notes into bug entries by:

1. splitting the patch notes into candidate fix statements
2. removing obvious non-bug items such as content additions
3. normalizing each fix into a bug record
4. assigning stable IDs per patch
5. generating minimal reproduction steps

If `OPENAI_API_KEY` and `OPENAI_MODEL` are set, the pipeline can ask an OpenAI-compatible endpoint for compact reproduction steps. If not, it falls back to deterministic template-based steps.

## Environment Variables

- `STEAM_WEB_API_KEY`
  Required for Steam discovery. Can be set in `hub/sourcing/.env`.
- `GITHUB_TOKEN`
  Optional but strongly recommended. Can be set in `hub/sourcing/.env`.
- `OPENAI_API_KEY`
  Optional, enables LLM-based reproduction-step synthesis.
- `OPENAI_MODEL`
  Optional, required together with `OPENAI_API_KEY`.
- `OPENAI_BASE_URL`
  Optional, defaults to `https://api.openai.com/v1`.

## Tests

Frozen-fixture tests live under `hub/tests/sourcing`.

Run them with:

```bash
python -m unittest discover -s hub/tests/sourcing -p "test_*.py" -v
```

The tests cover:

- provider normalization for GitHub, itch.io, and Steam
- hard-filter and scoring behavior
- version-pair resolution and publication
- ground-truth generation
- end-to-end catalog output using fixture-backed fetchers
