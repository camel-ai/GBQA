# Dark Castle: Night of Awakening

A text adventure game.

## Overview

Dark Castle: Night of Awakening is a classic interactive fiction game inspired by games like **ALFWorld** and **Zork**. The player wakes inside a ruined castle, explores 8 rooms, collects 3 key fragments, assembles the **Key of Awakening**, and escapes through the sealed main door.

### Core Features

- 8 connected rooms with deterministic navigation
- 20+ interactive objects with pickup, use, open, read, combine, and light behaviors
- Puzzle logic based on physical common sense: light sources, locks, containers, and inventory limits
- A clean backend/frontend split for automated agent testing
- Session logging for replay and debugging

## Quick Start

### 1. Install dependencies

```bash
cd backend && pip install -r requirements.txt
```

### 2. Start the server

```bash
python app.py
```

### 3. Play the game

Open **http://localhost:5000** in your browser.

## World Map

```text
                    [Attic]
                       |
[Bedroom] --- [Corridor] --- [Library]
                |
[Kitchen] --- [Hall] --- [Storage Room]
                |
            [Basement]
```

## Basic Commands

| Type | Example |
|------|---------|
| Move | `go north`, `n` |
| Look | `look`, `examine candlestick` |
| Take | `take matches` |
| Drop | `drop matches` |
| Use | `use small key on storage room` |
| Inventory | `inventory` |
| Help | `help` |

## Developer Mode

Type `devmode` or `autoplay` in the running game to launch the guided full-play demo:

- Runs the complete 38-step win path
- Shows live progress
- Can be interrupted with `stop`

## Agent API

The backend includes dedicated endpoints for agent-driven play:

```bash
# Create a game
curl -X POST http://localhost:5000/api/agent/new

# Send a command
curl -X POST http://localhost:5000/api/agent/command \
  -H "Content-Type: application/json" \
  -d '{"game_id":"<game_id>","command":"look"}'
```

See [API Reference](docs/api_reference.md) for the full contract.

## Project Structure

```text
dark-castle/
├── backend/                 # Python backend
│   ├── app.py               # Flask application
│   └── game/                # Game engine
├── .cache/                  # Generated cache artifacts
│   ├── data/                # Generated data files
│   └── log/                 # Session logs
├── frontend/                # Web frontend
│   ├── index.html
│   ├── css/style.css
│   └── js/
└── docs/                    # Project documentation
```

## Documentation

| Document | Description |
|----------|-------------|
| [Game Design](docs/game_design_document.md) | World design, puzzles, and systems |
| [API Reference](docs/api_reference.md) | Backend API details |
| [Walkthrough](docs/walkthrough.md) | Complete winning route |

## Logging

Each game session writes a JSON log into `.cache/log/`:

- Format: `game_YYYYMMDD_HHMMSS_<game_id>.json`
- Contains commands, responses, and lightweight state snapshots
- Browse via `GET /api/logs`

## QA Scenarios

This project is useful for evaluating:

1. Spatial reasoning across connected rooms
2. Item interaction logic and inventory management
3. Physical common-sense reasoning around light, locks, and containers
4. Multi-step planning and puzzle solving
5. Natural-language command understanding
