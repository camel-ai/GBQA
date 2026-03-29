# Game Design Document

## 1. Overview

### 1.1 Genre
Text adventure / interactive fiction

### 1.2 Positioning
This project is a benchmark game designed for **GBQA**. The player interacts with the world through natural-language commands, while the game state remains deterministic and fully inspectable for automated testing.

### 1.3 Design Goals

- High observability for testing and debugging
- Puzzle logic grounded in physical common sense
- Moderate challenge with multi-step planning
- Deterministic outcomes for the same input sequence

## 2. Narrative Setup

The story takes place in a remote mountain region in late 19th-century Europe. A mysterious fortress known as **Moriarty Castle** stands on a fog-covered ridge. It once belonged to a reclusive alchemist who vanished during a violent storm, leaving behind sealed rooms, failed experiments, and hidden clues.

The player awakens in the castle hall with no clear memory of how they arrived. The main door is held shut by a magical seal. The only escape is to recover the **Key of Awakening**, a magical key broken into three fragments and hidden across the castle.

## 3. World Structure

The game world contains 8 rooms:

```text
                    [Attic]
                       |
[Bedroom] --- [Corridor] --- [Library]
                |
[Kitchen] --- [Hall] --- [Storage Room]
                |
            [Basement]
```

| Room | Description | Key Objects |
|------|-------------|-------------|
| Hall | Grand central hall with the sealed main door | matches, candlestick, sealed door |
| Corridor | Narrow hallway lined with portraits | portrait, torch sconce |
| Library | Dusty room of ancient books | scroll, bookshelf, reading table, trapdoor |
| Attic | Tight upper room with a locked chest | old chest, telescope, key fragment A |
| Bedroom | Former alchemist's chamber | four-poster bed, nightstand, diary, small key |
| Kitchen | Abandoned kitchen with dry wood | fireplace, bucket, ladder |
| Storage Room | Locked utility room | toolbox, rope, oil lamp, key fragment B |
| Basement | Dark lower chamber | wine barrels, iron door, key fragment C |

## 4. Item System

### Portable Items

- matches
- candlestick
- small key
- scroll
- diary
- ladder
- oil lamp
- rope
- bucket
- key fragment A
- key fragment B
- key fragment C
- Key of Awakening

### Fixed or Environmental Objects

- sealed door
- portrait
- torch sconce
- bookshelf
- reading table
- trapdoor
- old chest
- telescope
- four-poster bed
- nightstand
- mirror
- fireplace
- toolbox
- wine barrels
- iron door

### Containers

- nightstand
- old chest
- toolbox
- bucket
- player inventory (capacity: 6 items)

## 5. Core Interaction Rules

### Lighting

- Dark rooms cannot be explored properly without light
- Lit candlesticks and oil lamps function as light sources
- Matches can ignite the candlestick, oil lamp, and fireplace

### Locks and Doors

- The small key unlocks the storage room
- The attic chest uses a numeric code
- The basement iron door must be oiled before it can open
- The sealed door requires the assembled Key of Awakening

### Containers

- Containers must be open before items can be taken from them
- Locked containers must be unlocked first

### Inventory

- Maximum capacity is 6 items
- Players must manage space during the optimal route

## 6. Puzzle Structure

### Puzzle 1: Unlock the Storage Room

1. Search the bedroom
2. Open the nightstand
3. Take the small key
4. Unlock the storage room
5. Open the toolbox for key fragment B

### Puzzle 2: Reach the Attic

1. Find the ladder in the kitchen
2. Carry it to the library
3. Set it beneath the trapdoor
4. Read the scroll for the numeric clue
5. Enter `3` to open the attic chest

### Puzzle 3: Open the Basement Iron Door

1. Bring a light source into the basement
2. Carry the oil lamp
3. Use its fuel to loosen the rusted lock
4. Open the iron door and recover key fragment C

### Final Puzzle: Escape

1. Collect all three key fragments
2. Combine them into the Key of Awakening
3. Return to the hall
4. Use the key on the sealed door
5. Open the door and escape

## 7. Gameplay Loop

1. Player enters a command
2. Parser converts it into a structured action
3. The engine validates world rules
4. State updates are applied
5. The game returns a textual response and visible state

## 8. Win Condition

The player wins by opening the sealed main door after assembling and using the Key of Awakening.

There is no fail state; the player can continue trying until they solve the castle.

## 9. Testing Value

This design is suitable for:

- navigation testing
- inventory reasoning
- common-sense interaction checks
- multi-step puzzle planning
- invalid-command handling
- state consistency validation

## 10. Extensibility

The game is intentionally data-driven:

- rooms and items live in JSON
- the parser is alias-driven
- actions are routed through a handler map
- logs make scenario replay straightforward

Future extensions could add new rooms, more puzzles, NPCs, branching endings, or timed scenarios.

---

Document version: `1.0.0`
