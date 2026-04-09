# API Reference

Backend API reference for **Dark Castle: Night of Awakening**.

## Base Information

- **Base URL**: `http://localhost:5000/api`
- **Format**: JSON
- **Encoding**: UTF-8

## 1. Player Session Endpoints

These endpoints are used by the browser frontend and rely on session state.

### 1.1 Create a New Game

```http
POST /api/game/new
```

Response example:

```json
{
  "success": true,
  "game_id": "4d07fd20-6d38-4e06-b889-0e537ce75957",
  "message": "Opening narration...",
  "state": {
    "room": {},
    "inventory": [],
    "flags": {}
  }
}
```

### 1.2 Send a Command

```http
POST /api/game/command
```

Request body:

```json
{
  "command": "go north"
}
```

Response example:

```json
{
  "success": true,
  "message": "[Corridor]\n\nThis is a narrow corridor...",
  "state": {},
  "game_over": false,
  "turn": 5
}
```

### 1.3 Get Current State

```http
GET /api/game/state
```

### 1.4 Reset the Game

```http
POST /api/game/reset
```

## 2. Agent Endpoints

These endpoints are intended for LLM-driven testing. They use `game_id` directly and do not depend on browser session state.

### 2.1 Create a New Game

```http
POST /api/agent/new
```

Response example:

```json
{
  "success": true,
  "game_id": "4d07fd20-6d38-4e06-b889-0e537ce75957",
  "message": "Opening narration...",
  "state": {
    "room": {
      "id": "hall",
      "name": "Hall",
      "description": "...",
      "exits": ["north", "west", "east", "down"],
      "dark": false
    },
    "inventory": [],
    "flags": {
      "key_assembled": false,
      "door_unlocked": false,
      "game_won": false,
      "ladder_placed": false
    },
    "turn_count": 0,
    "can_see": true
  },
  "full_state": {}
}
```

### 2.2 Send a Command

```http
POST /api/agent/command
```

Request body:

```json
{
  "game_id": "4d07fd20-6d38-4e06-b889-0e537ce75957",
  "command": "take matches"
}
```

Response example:

```json
{
  "success": true,
  "message": "You pick up the matches.",
  "state": {},
  "game_over": false,
  "turn": 1,
  "full_state": {}
}
```

### 2.3 Get Agent State

```http
GET /api/agent/state/<game_id>
```

### 2.4 List Source Code Files

```http
GET /api/agent/code/files
```

Response example:

```json
{
  "success": true,
  "files": [
    {"path": "app.py", "size": 11222},
    {"path": "game/engine.py", "size": 7767},
    {"path": "game/actions.py", "size": 29959},
    {"path": "game/world.py", "size": 13574},
    {"path": "game/parser.py", "size": 7204},
    {"path": "game/data/rooms.json", "size": 9406},
    {"path": "game/data/items.json", "size": 14198}
  ]
}
```

### 2.5 Read a Source Code File

```http
POST /api/agent/code/read
```

Request body:

```json
{
  "path": "game/engine.py",
  "start_line": 1,
  "end_line": 20
}
```

`start_line` and `end_line` are optional. When omitted the full file is returned.

Response example:

```json
{
  "success": true,
  "path": "game/engine.py",
  "content": "   1  \"\"\"...\n   2  ...",
  "start_line": 1,
  "end_line": 20,
  "total_lines": 227
}
```

### 2.6 Search Source Code

```http
POST /api/agent/code/search
```

Request body:

```json
{
  "pattern": "def handle_combine",
  "max_results": 30
}
```

`pattern` supports Python regex. `max_results` defaults to 30.

Response example:

```json
{
  "success": true,
  "pattern": "def handle_combine",
  "matches": [
    {
      "path": "game/actions.py",
      "line": 562,
      "text": "    def handle_combine(self, command: ParsedCommand) -> ActionResult:"
    }
  ],
  "total": 1
}
```

### 2.7 Write / Patch a Source Code File

```http
POST /api/agent/code/write
```

Request body (patch mode — search-and-replace):

```json
{
  "path": "game/actions.py",
  "patch": {
    "search": "    def handle_take(self, command: ParsedCommand) -> ActionResult:",
    "replace": "    def handle_take(self, command: ParsedCommand) -> ActionResult:\n        print(f\"DEBUG: target={command.target}\")"
  }
}
```

Request body (full overwrite):

```json
{
  "path": "game/actions.py",
  "content": "...full file content..."
}
```

A backup of the original file is created on the first write. The server hot-reloads
the affected module so changes take effect immediately for all active game sessions.

Response example:

```json
{
  "success": true,
  "message": "Successfully updated game/actions.py",
  "path": "game/actions.py",
  "backup_available": true
}
```

### 2.8 Read / Clear Debug Logs

Captured `print()` output from the game server process.

**Read logs:**

```http
GET /api/agent/code/debug_logs
```

Response example:

```json
{
  "success": true,
  "logs": "[14:23:01.456] DEBUG: target=matches\n"
}
```

**Clear logs:**

```http
DELETE /api/agent/code/debug_logs
```

Response example:

```json
{
  "success": true,
  "message": "Debug logs cleared."
}
```

### 2.9 Restore a Source Code File

Restore a file to its original state before any `code/write` modifications.

```http
POST /api/agent/code/restore
```

Request body:

```json
{
  "path": "game/actions.py"
}
```

Response example:

```json
{
  "success": true,
  "message": "Successfully restored game/actions.py",
  "path": "game/actions.py",
  "backup_available": false
}
```

### 2.10 Analyze Session Log

Run anomaly detection on the current game session log.

```http
POST /api/agent/logs/analyze
```

Request body:

```json
{
  "game_id": "4d07fd20-6d38-4e06-b889-0e537ce75957",
  "include_debug_output": true
}
```

Response example:

```json
{
  "success": true,
  "game_id": "4d07fd20-...",
  "analysis": {
    "summary": "Found 3 anomalies in 45-turn session, 1 server errors",
    "total_turns": 45,
    "anomaly_count": 3,
    "anomalies": [
      {
        "type": "failed_command_streak",
        "severity": "high",
        "turns": [12, 13, 14],
        "description": "3 consecutive failures: 'take sword', 'take sword', 'take sword'",
        "evidence": [{"turn": 12, "command": "take sword", "message": "You can't take that."}]
      }
    ],
    "debug_findings": {
      "error_count": 1,
      "warning_count": 0,
      "errors": [{"timestamp": "14:23:01.456", "line": "KeyError: 'sword'", "context": "..."}],
      "warnings": []
    }
  }
}
```

Anomaly types: `failed_command_streak`, `repeated_command`, `state_inconsistency`, `error_in_response`, `time_gap`, `game_over_mismatch`.

### 2.11 Get Filtered Session Commands

```http
POST /api/agent/logs/filtered
```

Request body:

```json
{
  "game_id": "4d07fd20-6d38-4e06-b889-0e537ce75957",
  "start_turn": 10,
  "end_turn": 20,
  "failures_only": false,
  "limit": 50
}
```

All fields except `game_id` are optional. `failures_only` filters to commands where `response.success` is false.

Response example:

```json
{
  "success": true,
  "game_id": "4d07fd20-...",
  "commands": [
    {
      "turn": 10,
      "timestamp": "2025-12-18T18:36:15",
      "command": "take matches",
      "response": {"success": true, "message": "You pick up the matches.", "game_over": false},
      "state_snapshot": {"room": "Hall", "inventory": ["matches"]}
    }
  ],
  "total_commands": 45,
  "returned_commands": 11,
  "filtered_total": 11
}
```

## 3. Log Endpoints

### 3.1 List Logs

```http
GET /api/logs
```

Response example:

```json
{
  "success": true,
  "logs": [
    {
      "filename": "game_20251218_183519_4d07fd20.json",
      "game_id": "4d07fd20-...",
      "start_time": "2025-12-18T18:35:19",
      "result": "victory",
      "total_turns": 38
    }
  ],
  "total": 1
}
```

### 3.2 Get a Specific Log

```http
GET /api/logs/<filename>
```

### 3.3 Get the Active Log for a Game

```http
GET /api/logs/current/<game_id>
```

## 4. Health Check

```http
GET /api/health
```

Response example:

```json
{
  "status": "healthy",
  "game": "Dark Castle: Night of Awakening",
  "version": "1.0.0"
}
```

## 5. State Shape

### 5.1 `state`

```typescript
interface GameState {
  room: {
    id: string;
    name: string;
    description: string;
    exits: string[];
    dark: boolean;
  };
  items: Array<{
    id: string;
    name: string;
    description: string;
  }>;
  inventory: Array<{
    id: string;
    name: string;
    state: object;
  }>;
  flags: {
    key_assembled: boolean;
    door_unlocked: boolean;
    game_won: boolean;
    ladder_placed: boolean;
  };
  turn_count: number;
  can_see: boolean;
}
```

### 5.2 Command Response

```typescript
interface CommandResponse {
  success: boolean;
  message: string;
  state: GameState;
  game_over: boolean;
  turn: number;
  full_state?: object;
}
```

## 6. Errors

All endpoints return an error payload in this shape:

```json
{
  "success": false,
  "message": "Error description"
}
```

Common status codes:

- `400` invalid request payload
- `404` missing resource

## 7. Examples

### Python

```python
import requests

BASE_URL = "http://localhost:5000/api"

response = requests.post(f"{BASE_URL}/agent/new")
data = response.json()
game_id = data["game_id"]
print(data["message"])

def send_command(command):
    response = requests.post(
        f"{BASE_URL}/agent/command",
        json={"game_id": game_id, "command": command},
    )
    return response.json()

print(send_command("look")["message"])
print(send_command("take matches")["message"])
print(send_command("go north")["message"])

state = requests.get(f"{BASE_URL}/agent/state/{game_id}").json()
print(f"Current room: {state['state']['room']['name']}")
print(f"Inventory: {[item['name'] for item in state['state']['inventory']]}")
```

### JavaScript

```javascript
const BASE_URL = "http://localhost:5000/api";

async function playGame() {
  const newGame = await fetch(`${BASE_URL}/agent/new`, {
    method: "POST",
  }).then((response) => response.json());

  const gameId = newGame.game_id;
  console.log(newGame.message);

  async function command(cmd) {
    return await fetch(`${BASE_URL}/agent/command`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ game_id: gameId, command: cmd }),
    }).then((response) => response.json());
  }

  console.log((await command("look")).message);
  console.log((await command("take matches")).message);
}

playGame();
```

---

Document version: `1.2.0`
