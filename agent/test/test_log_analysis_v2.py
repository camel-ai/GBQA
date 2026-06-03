from datetime import datetime, timedelta
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.log_analyzer import LogAnalyzer
from src.log_types import (
    CommandState,
    NormalizedCommand,
    NormalizedSession,
    UniversalLogAdapter,
)


def test_universal_adapter_api_format():
    """Test standard GBQA API format."""
    adapter = UniversalLogAdapter()
    raw = {
        "commands": [
            {
                "turn": 1,
                "command": "look",
                "response": {"success": True, "message": "Ok"},
                "state_snapshot": {"room": "Hall", "inventory": ["key"]}
            }
        ]
    }
    session = adapter.normalize_session(raw)
    assert len(session.commands) == 1
    assert session.commands[0].command == "look"
    assert session.commands[0].state.location == "Hall"
    assert session.commands[0].state.inventory == ["key"]


def test_universal_adapter_daytona_format():
    """Test Harbor/Daytona nested format."""
    adapter = UniversalLogAdapter()
    raw = {
        "steps": [
            {
                "step": 1,
                "action": {"command": "navigate"},
                "observation": {
                    "success": True,
                    "url": "http://test.com",
                    "items": ["cookie"]
                }
            }
        ]
    }
    session = adapter.normalize_session(raw)
    assert len(session.commands) == 1
    assert session.commands[0].command == "navigate"
    assert session.commands[0].state.location == "http://test.com"
    assert session.commands[0].state.inventory == ["cookie"]


def test_streak_detection():
    analyzer = LogAnalyzer()
    commands = [
        NormalizedCommand(i, "cmd", False, "Error") for i in range(1, 5)
    ]
    session = NormalizedSession(commands=commands, total_turns=4)
    results = analyzer.analyze_session(session)
    anomalies = [a for a in results["anomalies"] if a["type"] == "failed_command_streak"]
    assert len(anomalies) == 1


def test_repeated_command_detection():
    analyzer = LogAnalyzer()
    commands = [
        NormalizedCommand(i, "jump", True, "Ok") for i in range(1, 5)
    ]
    session = NormalizedSession(commands=commands, total_turns=4)
    results = analyzer.analyze_session(session)
    anomalies = [a for a in results["anomalies"] if a["type"] == "repeated_command"]
    assert len(anomalies) == 1


def test_state_inconsistency_location():
    analyzer = LogAnalyzer()
    t1 = datetime.now()
    # Using the universal adapter's default move verbs
    commands = [
        NormalizedCommand(1, "look", True, "Ok", state=CommandState(location="Hall"), timestamp=t1),
        NormalizedCommand(2, "sing", True, "Ok", state=CommandState(location="Kitchen"), timestamp=t1 + timedelta(seconds=1)),
    ]
    session = NormalizedSession(commands=commands, total_turns=2)
    results = analyzer.analyze_session(session)
    anomalies = [a for a in results["anomalies"] if a["type"] == "state_inconsistency"]
    assert len(anomalies) == 1
    assert "Location changed" in anomalies[0]["description"]


def test_error_pattern_detection():
    analyzer = LogAnalyzer()
    commands = [
        NormalizedCommand(1, "test", False, "Fatal KeyError happened"),
    ]
    session = NormalizedSession(commands=commands, total_turns=1)
    results = analyzer.analyze_session(session)
    anomalies = [a for a in results["anomalies"] if a["type"] == "error_in_response"]
    assert len(anomalies) == 1


def test_inventory_shrink_anomaly_does_not_crash():
    session = NormalizedSession(
        commands=[
            NormalizedCommand(
                turn=1,
                command="look",
                success=True,
                message="ok",
                state=CommandState(location="hall", inventory=["key"]),
            ),
            NormalizedCommand(
                turn=2,
                command="look",
                success=True,
                message="ok",
                state=CommandState(location="hall", inventory=[]),
            ),
        ],
        total_turns=2,
    )

    result = LogAnalyzer().analyze_session(session)

    assert result["anomaly_count"] == 1
    assert result["anomalies"][0]["type"] == "state_inconsistency"


def main():
    test_universal_adapter_api_format()
    test_universal_adapter_daytona_format()
    test_streak_detection()
    test_repeated_command_detection()
    test_state_inconsistency_location()
    test_error_pattern_detection()
    test_inventory_shrink_anomaly_does_not_crash()
    print("log analysis v2 tests passed")


if __name__ == "__main__":
    main()
