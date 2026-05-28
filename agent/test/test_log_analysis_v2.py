import pytest
from datetime import datetime, timedelta
from agent.src.log_analyzer import LogAnalyzer
from agent.src.log_types import (
    CommandState,
    DefaultLogAdapter,
    NormalizedCommand,
    NormalizedSession,
    PlaywrightLogAdapter,
)


@pytest.fixture
def web_analyzer():
    return LogAnalyzer(adapter=PlaywrightLogAdapter())


@pytest.fixture
def analyzer():
    return LogAnalyzer()


def test_playwright_movement_verbs(web_analyzer):
    t1 = datetime.now()
    commands = [
        NormalizedCommand(
            turn=1,
            command="look",
            success=True,
            message="On Home",
            state=CommandState(location="http://example.com/home"),
            timestamp=t1
        ),
        NormalizedCommand(
            turn=2,
            command="navigate to contact", # 'navigate' is a valid movement verb for Web
            success=True,
            message="On Contact",
            state=CommandState(location="http://example.com/contact"),
            timestamp=t1 + timedelta(seconds=1)
        ),
    ]
    session = NormalizedSession(commands=commands, total_turns=2)
    results = web_analyzer.analyze_session(session)
    
    # Should NOT have anomaly because 'navigate' is allowed
    anomalies = [a for a in results["anomalies"] if a["type"] == "state_inconsistency"]
    assert len(anomalies) == 0


def test_playwright_unexpected_navigation(web_analyzer):
    t1 = datetime.now()
    commands = [
        NormalizedCommand(
            turn=1,
            command="look",
            success=True,
            message="On Home",
            state=CommandState(location="http://example.com/home"),
            timestamp=t1
        ),
        NormalizedCommand(
            turn=2,
            command="scroll down", # 'scroll' is NOT a movement verb
            success=True,
            message="Scrolled",
            state=CommandState(location="http://example.com/contact"), # Unexpectedly moved!
            timestamp=t1 + timedelta(seconds=1)
        ),
    ]
    session = NormalizedSession(commands=commands, total_turns=2)
    results = web_analyzer.analyze_session(session)
    
    # Should have anomaly
    anomalies = [a for a in results["anomalies"] if a["type"] == "state_inconsistency"]
    assert len(anomalies) == 1
    assert "Location changed" in anomalies[0]["description"]


@pytest.fixture
def mock_session_dict():
    """A standard GBQA style session dict."""
    return {
        "result": "in_progress",
        "total_turns": 2,
        "commands": [
            {
                "turn": 1,
                "command": "look",
                "timestamp": "2026-05-27T10:00:00",
                "response": {"success": True, "message": "You see a room."},
                "state_snapshot": {"room": "Hall", "inventory": []},
            },
            {
                "turn": 2,
                "command": "take sword",
                "timestamp": "2026-05-27T10:00:05",
                "response": {"success": True, "message": "Taken."},
                "state_snapshot": {"room": "Hall", "inventory": ["sword"]},
            },
        ],
    }


def test_default_adapter_normalization(mock_session_dict):
    adapter = DefaultLogAdapter()
    session = adapter.normalize_session(mock_session_dict)

    assert isinstance(session, NormalizedSession)
    assert len(session.commands) == 2
    assert session.commands[1].command == "take sword"
    assert session.commands[1].success is True
    assert session.commands[1].state.inventory == ["sword"]
    assert isinstance(session.commands[0].timestamp, datetime)


def test_streak_detection(analyzer):
    commands = [
        NormalizedCommand(i, "cmd", False, "Error") for i in range(1, 5)
    ]
    session = NormalizedSession(commands=commands, total_turns=4)
    
    results = analyzer.analyze_session(session)
    anomalies = [a for a in results["anomalies"] if a["type"] == "failed_command_streak"]
    
    assert len(anomalies) == 1
    assert anomalies[0]["severity"] == "medium"
    assert len(anomalies[0]["turns"]) == 4


def test_repeated_command_detection(analyzer):
    commands = [
        NormalizedCommand(i, "jump", True, "Ok") for i in range(1, 5)
    ]
    session = NormalizedSession(commands=commands, total_turns=4)
    
    results = analyzer.analyze_session(session)
    anomalies = [a for a in results["anomalies"] if a["type"] == "repeated_command"]
    
    assert len(anomalies) == 1
    assert "jump" in anomalies[0]["description"]


def test_state_inconsistency_inventory(analyzer):
    t1 = datetime.now()
    commands = [
        NormalizedCommand(
            turn=1,
            command="look",
            success=True,
            message="Ok",
            state=CommandState(location="Room", inventory=["key"]),
            timestamp=t1
        ),
        NormalizedCommand(
            turn=2,
            command="jump", # Not a remove verb
            success=True,
            message="Ok",
            state=CommandState(location="Room", inventory=[]), # Key vanished!
            timestamp=t1 + timedelta(seconds=1)
        ),
    ]
    session = NormalizedSession(commands=commands, total_turns=2)
    
    results = analyzer.analyze_session(session)
    anomalies = [a for a in results["anomalies"] if a["type"] == "state_inconsistency"]
    
    assert len(anomalies) == 1
    assert "vanished" in anomalies[0]["description"]


def test_state_inconsistency_location(analyzer):
    t1 = datetime.now()
    commands = [
        NormalizedCommand(
            turn=1,
            command="look",
            success=True,
            message="Ok",
            state=CommandState(location="Hall"),
            timestamp=t1
        ),
        NormalizedCommand(
            turn=2,
            command="sing", # Not a move verb
            success=True,
            message="Ok",
            state=CommandState(location="Kitchen"), # Teleported!
            timestamp=t1 + timedelta(seconds=1)
        ),
    ]
    session = NormalizedSession(commands=commands, total_turns=2)
    
    results = analyzer.analyze_session(session)
    anomalies = [a for a in results["anomalies"] if a["type"] == "state_inconsistency"]
    
    assert len(anomalies) == 1
    assert "Location changed" in anomalies[0]["description"]


def test_backward_compatibility_with_dict(analyzer, mock_session_dict):
    # This should work without explicitly using adapter
    results = analyzer.analyze_session(mock_session_dict)
    assert results["total_turns"] == 2
    assert results["anomaly_count"] == 0 # Clean session


def test_error_pattern_detection(analyzer):
    commands = [
        NormalizedCommand(1, "test", False, "Fatal KeyError happened"),
    ]
    session = NormalizedSession(commands=commands, total_turns=1)
    results = analyzer.analyze_session(session)
    
    anomalies = [a for a in results["anomalies"] if a["type"] == "error_in_response"]
    assert len(anomalies) == 1
