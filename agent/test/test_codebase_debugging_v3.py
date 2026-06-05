import pytest
from unittest.mock import MagicMock
from agent.src.codebase_types import UniversalCodebaseAdapter

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
    assert "cat > /sandbox/software/buggy.py <<'GBQA_CODE_EOF'" in args[0]
    assert "fixed code" in args[0]
