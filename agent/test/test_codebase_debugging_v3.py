import pytest
from unittest.mock import MagicMock
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agent.src.codebase_types import UniversalCodebaseAdapter
from agent.src.tool_registry import ToolRegistry, register_code_tools

@pytest.fixture
def mock_sandbox_backend():
    backend = MagicMock()
    # Mock shell.run and its async wrapper
    backend.shell.run.return_value = MagicMock(stdout="file1.py\nfile2.py")
    backend._run_async = lambda x: x
    return backend

def test_universal_adapter_shell_list(mock_sandbox_backend):
    adapter = UniversalCodebaseAdapter(shell_client=mock_sandbox_backend)
    files = adapter.list_files()
    assert len(files) == 2
    assert files[0].path == "file1.py"
    mock_sandbox_backend.shell.run.assert_any_call("find /sandbox/software -maxdepth 2 -not -path '*/.*'")

def test_universal_adapter_shell_read(mock_sandbox_backend):
    mock_sandbox_backend.shell.run.return_value = MagicMock(stdout="class Game:")
    adapter = UniversalCodebaseAdapter(shell_client=mock_sandbox_backend)
    content = adapter.read_file("game.py")
    assert content == "class Game:"
    mock_sandbox_backend.shell.run.assert_called_with("cat /sandbox/software/game.py")

def test_universal_adapter_shell_write_with_backup(mock_sandbox_backend):
    # First read (for backup)
    mock_sandbox_backend.shell.run.side_effect = [
        MagicMock(stdout="original code"), # read for backup
        MagicMock(stdout="")               # actual write
    ]
    adapter = UniversalCodebaseAdapter(shell_client=mock_sandbox_backend)
    
    success = adapter.write_file("buggy.py", "fixed code")
    assert success is True
    # Verify backup exists
    assert adapter._backups["buggy.py"] == "original code"
    # Verify the write command uses heredoc
    args, _ = mock_sandbox_backend.shell.run.call_args
    assert "cat > /sandbox/software/buggy.py <<'GBQA_CODE_EOF_" in args[0]
    assert "fixed code" in args[0]


def test_universal_adapter_local_filesystem_fallback(tmp_path):
    source_root = tmp_path / "software"
    source_root.mkdir()
    app_file = source_root / "app.py"
    app_file.write_text("def bug():\n    return 'old'\n", encoding="utf-8")

    adapter = UniversalCodebaseAdapter(shell_client=None, root_dir=str(source_root))
    files = adapter.list_files()
    assert any(item.path == "app.py" for item in files)

    assert "return 'old'" in adapter.read_file("app.py")
    matches = adapter.search_code("return 'old'")
    assert matches[0]["path"] == "app.py"
    assert adapter.write_file("app.py", "def bug():\n    return 'new'\n")
    assert "return 'new'" in app_file.read_text(encoding="utf-8")
    assert adapter.restore_file("app.py")
    assert "return 'old'" in app_file.read_text(encoding="utf-8")


def test_code_tool_patch_fallback_updates_existing_content(tmp_path):
    source_root = tmp_path / "software"
    source_root.mkdir()
    app_file = source_root / "app.py"
    app_file.write_text("def bug():\n    return 'old'\n", encoding="utf-8")

    registry = ToolRegistry()
    adapter = UniversalCodebaseAdapter(shell_client=None, root_dir=str(source_root))
    register_code_tools(registry, adapter)
    registry.activate_skill("code")

    result = registry.invoke(
        "code_write_file",
        {
            "path": "app.py",
            "patch": {"search": "return 'old'", "replace": "return 'new'"},
        },
        {},
    )

    assert result.observation.success
    assert "return 'new'" in app_file.read_text(encoding="utf-8")
    assert "return 'old'" not in app_file.read_text(encoding="utf-8")
