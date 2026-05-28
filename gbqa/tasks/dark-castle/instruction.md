# Dark Castle QA Task

Explore Dark Castle: Night of Awakening as a QA agent. Your goal is to discover real gameplay or state-consistency bugs and report each bug with enough evidence for reproduction.

Focus on:

- invalid state transitions
- descriptions that reveal hidden information too early
- inventory and room-state inconsistencies
- mismatches between text feedback and backend state

Write bug findings through the GBQA agent report artifacts. The verifier will compare your reported bugs against the task ground truth.

After you have found several bugs, you should still try to reach the exit of the castle, instead of terminate.
