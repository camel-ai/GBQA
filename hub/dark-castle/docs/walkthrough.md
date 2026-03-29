# Walkthrough

Complete winning route for **Dark Castle: Night of Awakening**.

## Goal

Collect the three key fragments, assemble the **Key of Awakening**, break the seal on the main door, and escape the castle.

## World Map

```text
                    [Attic]
                       ^
                    (needs ladder)
                       |
[Bedroom] <--> [Corridor] <--> [Library]
                 ^
                 |
[Kitchen] <--> [Hall] <--> [Storage Room]
                 v            (needs small key)
                 |
             [Basement]
               (dark)
```

## Fragment Locations

| Fragment | Location | Requirement |
|----------|----------|-------------|
| A | Attic -> old chest | Ladder + code `3` |
| B | Storage Room -> toolbox | Small key |
| C | Basement -> behind the iron door | Light source + oiling the lock |

## Important Items

| Item | Location | Purpose |
|------|----------|---------|
| matches | Hall | Lights the candlestick or oil lamp |
| small key | Bedroom -> nightstand | Unlocks the storage room |
| diary | Bedroom | Gives puzzle clues |
| ladder | Kitchen | Reaches the attic |
| scroll | Library | Reveals the code |
| oil lamp | Storage Room | Light source and oil supply |

## Optimized 38-Step Route

> Inventory capacity is 6 items, so the route drops the small key when it is no longer needed.

### Phase 1: Get the Small Key

```text
1.  look
2.  take matches
3.  go north
4.  go west
5.  open nightstand
6.  take small key
7.  read diary
```

### Phase 2: Get Key Fragment B

```text
8.  go east
9.  go south
10. use small key on storage room
11. go east
12. take oil lamp
13. open toolbox
14. take key fragment b
```

### Phase 3: Get Key Fragment A

```text
15. go west
16. go west
17. take ladder
18. go east
19. go north
20. go east
21. read scroll
22. use ladder
23. go up
24. enter 3
25. take key fragment a
```

### Phase 4: Get Key Fragment C

```text
26. go down
27. go west
28. go south
29. drop small key
30. light oil lamp
31. go down
32. oil iron door
33. open iron door
34. take key fragment c
```

### Final Phase: Escape

```text
35. combine
36. go up
37. use key of awakening
38. open sealed door
```

## Puzzle Answers

### Storage Room

- Problem: the door is locked
- Solution: find the small key in the bedroom nightstand

### Attic Access

- Problem: the trapdoor is out of reach
- Solution: carry the ladder from the kitchen to the library

### Chest Code

- Problem: the chest needs a number
- Solution: read the scroll; the correct code is `3`

### Basement Iron Door

- Problem: the door is rusted and the basement is dark
- Solution:
  1. light the oil lamp
  2. bring it into the basement
  3. oil the iron door
  4. open the door

## Developer Mode

Type `devmode` or `autoplay` in the game to launch the scripted full-play demo.

## FAQ

### What if my inventory is full?

Use `drop <item>` to free space. The small key can be dropped after the storage room is opened.

### Why is the basement unreadable?

You need a lit light source before you can explore it properly. `light oil lamp` is the intended route.

### Why can I not combine the key yet?

Make sure you are carrying all three fragments: A, B, and C.

### Why does the sealed door not open?

You must first `use key of awakening`, then `open sealed door`.

## Command Quick Reference

| Command | Example |
|---------|---------|
| Move | `go north`, `n` |
| Look | `look`, `examine candlestick` |
| Take | `take matches` |
| Drop | `drop matches` |
| Open | `open nightstand` |
| Use | `use small key on storage room` |
| Read | `read diary` |
| Light | `light oil lamp` |
| Oil | `oil iron door` |
| Code | `enter 3` |
| Combine | `combine` |
| Inventory | `inventory`, `i` |
| Help | `help` |

---

Document version: `1.0.0`
