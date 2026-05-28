import subprocess
import time
import os
import signal
import requests
import sys

# 设置路径
PROJECT_ROOT = os.getcwd()
AGENT_DIR = os.path.join(PROJECT_ROOT, "agent")
BACKEND_DIR = os.path.join(PROJECT_ROOT, "hub", "dark-castle", "backend")
VENV_PYTHON = os.path.join(PROJECT_ROOT, "venv", "bin", "python")
PORT = 5099

# 1. 启动服务器
print(f">>> 启动服务器在端口 {PORT}...")
server_env = os.environ.copy()
server_env["PYTHONPATH"] = BACKEND_DIR
server_env["PORT"] = str(PORT)

server_proc = subprocess.Popen(
    [VENV_PYTHON, "app.py"],
    cwd=BACKEND_DIR,
    env=server_env,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    preexec_fn=os.setsid
)

# 2. 等待直到服务器 Ready
ready = False
for i in range(20):
    try:
        r = requests.get(f"http://localhost:{PORT}/api/health", timeout=2)
        if r.status_code == 200:
            print(">>> 服务器已就绪 (READY)")
            ready = True
            break
    except:
        pass
    print(f"    等待服务器中 ({i+1})...")
    time.sleep(2)

if not ready:
    print(">>> 错误：服务器无法启动")
    os.killpg(os.getpgid(server_proc.pid), signal.SIGTERM)
    sys.exit(1)

# 3. 运行 Agent (强制执行 10 步)
print(">>> 运行 Agent 任务 (Force Debug)...")
config_path = os.path.join(AGENT_DIR, "config_debug_force.yaml")
with open(config_path, "w") as f:
    f.write(f"""
llm:
  temperature: 0.1
agent:
  max_steps: 10
  enable_code_reading: true
games:
  dark-castle:
    port: {PORT}
    profile: |
      MISSION: Investigating a weird bug where 'take matches' fails in the Hall.
      CRITICAL INSTRUCTION: You MUST use white-box debugging. 
      Step 1. Use 'code_write_file' to insert 'print(f"DEBUG_HOOK: target={{command.target}}")' inside 'handle_take' in 'game/actions.py'. 
      Step 2. Try 'take matches' again to trigger it. 
      Step 3. Use 'code_read_debug_logs' to check the output of the print statement.
report:
  output_dir: "reports/final_verify"
""")

agent_env = os.environ.copy()
agent_env["PYTHONPATH"] = AGENT_DIR

# 确保在运行 agent 时传递相对于 agent 目录或绝对路径的 config
subprocess.run(
    [VENV_PYTHON, os.path.join(AGENT_DIR, "run_agent.py"), "--game", "dark-castle", "--config", config_path],
    env=agent_env
)

# 4. 停止服务器
print(">>> 停止服务器...")
os.killpg(os.getpgid(server_proc.pid), signal.SIGTERM)

# 5. 查找报告并搜寻关键字
print("\n>>> 正在验证报告内容...")
report_base = os.path.join(AGENT_DIR, "reports", "final_verify", "dark-castle")
latest_run = sorted(os.listdir(report_base))[-1]
report_path = os.path.join(report_base, latest_run, "report.md")

with open(report_path, "r") as f:
    content = f.read()
    if "--- Debug Logs ---" in content:
        print("\n🏆 成功！在 report.md 中发现了调试日志标记！")
        print("\n报告片段预览：")
        print("-" * 50)
        # 截取一段包含日志的内容
        idx = content.find("--- Debug Logs ---")
        print(content[idx:idx+200])
        print("-" * 50)
    else:
        print("\n❌ 失败：报告中没有找到调试日志标记。")
        print("报告全量内容预览：")
        print(content[:2000])
