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

Document version: `1.0.0`
