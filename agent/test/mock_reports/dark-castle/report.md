# QA Agent Report - dark-castle

Total steps: 0
Total bugs: 3

## Bugs
### The final key can be assembled after finding only two fragments.
- Confidence: 0.99
- Description: Reproduction: obtain any pair of key pieces and then run `combine`. Actual behavior: the game creates the completed escape key even though the third fragment has not been collected yet.

### Bedroom narration exposes the drawer key before the player opens the drawer.
- Confidence: 0.98
- Description: Reproduction: enter the bedroom and look around before interacting with the bedside drawer. Actual behavior: the textual room description already discloses the small key even though it should still be concealed.

### After dropping an item, the refreshed room text fails to mention it.
- Confidence: 0.97
- Description: Reproduction: pick up any portable object, move to another room, drop it, and then use `look`. Actual behavior: the backend state changes correctly, but the updated location description omits the dropped object.

## Summary
Synthetic report used to verify evaluation against the released Dark Castle ground truth.
