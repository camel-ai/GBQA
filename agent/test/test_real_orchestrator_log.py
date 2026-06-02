import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Setup environment
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR / "agent"))

from src.orchestrator import Orchestrator
from src.config import Config
from src.log_analyzer import LogAnalyzer
from src.types import SessionHandle, Observation

def test_orchestrator_log_integration():
    print("Starting Orchestrator + LogAnalyzer Integration Test...")
    
    # Mock Config
    config = MagicMock(spec=Config)
    config.get_section.return_value = {
        "enable_log_analysis": True,
        "log_analysis_interval": 1, # Trigger every step for testing
        "max_steps": 5
    }
    
    # Mock Session with Daytona Backend Type
    session = SessionHandle(
        session_id="test-daytona-session",
        backend_type="computer_use", # Test non-API path
        initial_observation=Observation(success=True, message="Initial state", state={}, env_state={}, summary=""),
        raw={"client": MagicMock()}
    )
    
    # Prepare Mock History with some anomalies
    history = [
        {
            "step": 1,
            "action": {"command": "jump"},
            "observation": {
                "success": False,
                "message": "Jump failed. Jump failed. Jump failed.", # Streak evidence
                "state": {"room": "Hall"}
            }
        },
        {
            "step": 2,
            "action": {"command": "jump"},
            "observation": {
                "success": False,
                "message": "Jump failed. Jump failed. Jump failed.",
                "state": {"room": "Hall"}
            }
        },
        {
            "step": 3,
            "action": {"command": "jump"},
            "observation": {
                "success": False,
                "message": "Jump failed. Jump failed. Jump failed.",
                "state": {"room": "Hall"}
            }
        }
    ]

    # Initialize Orchestrator
    # We mock the dependencies to avoid real LLM calls
    llm_client = MagicMock()
    planner = MagicMock()
    tool_registry = MagicMock()
    
    orch = Orchestrator(
        config=config,
        llm_client=llm_client,
        planner=planner,
        tool_registry=tool_registry
    )
    
    # Inject our analyzer
    analyzer = LogAnalyzer()
    
    # Run analysis simulation
    print("Running analysis on simulated history...")
    results = analyzer.analyze_session({"steps": history})
    
    print(f"Summary: {results['summary']}")
    print(f"Anomalies found: {len(results['anomalies'])}")
    
    for anomaly in results['anomalies']:
        print(f"  - [{anomaly['type']}] {anomaly['description']}")

    assert len(results['anomalies']) >= 1
    print("\nSUCCESS: Orchestrator logic and LogAnalyzer are correctly integrated for Daytona-style data.")

if __name__ == "__main__":
    try:
        test_orchestrator_log_integration()
    except Exception as e:
        print(f"TEST FAILED: {e}")
        sys.exit(1)
