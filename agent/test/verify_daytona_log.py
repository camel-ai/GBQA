import json
import sys
from pathlib import Path

# Setup paths
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR / "agent"))

from src.log_analyzer import LogAnalyzer

def verify():
    # 指向刚才那个 10 次失败的任务日志
    log_path = ROOT_DIR / "jobs/2026-05-31__22-49-01/dark-castle__5b7SBPg/agent/gbqa/steps.jsonl"
    
    if not log_path.exists():
        print(f"Log not found at {log_path}")
        return

    print(f"📦 Analyzing real Daytona log: {log_path.name}")
    
    steps = []
    with open(log_path, 'r') as f:
        for line in f:
            if line.strip():
                steps.append(json.loads(line))

    analyzer = LogAnalyzer()
    # 构造 UniversalLogAdapter 能识别的结构
    session_data = {"steps": steps}
    
    results = analyzer.analyze_session(session_data)
    
    print(f"\n🚀 ANALYSIS RESULT:")
    print(f"Summary: {results['summary']}")
    print(f"Anomaly Count: {results['anomaly_count']}")
    
    for i, anomaly in enumerate(results['anomalies']):
        print(f"\n[{i+1}] Type: {anomaly['type']}")
        print(f"    Severity: {anomaly['severity']}")
        print(f"    Turns: {anomaly['turns']}")
        print(f"    Description: {anomaly['description']}")

if __name__ == "__main__":
    verify()
