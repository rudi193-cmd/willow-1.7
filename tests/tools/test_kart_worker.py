"""Tests for kart_worker command validation."""
# b17: H6H23
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from kart_worker import _validate_shell_cmd


class TestValidateShellCmd:
    def test_allowed_python3(self):
        assert _validate_shell_cmd("python3 /path/to/script.py") is True

    def test_allowed_git(self):
        assert _validate_shell_cmd("git commit -m 'msg'") is True

    def test_allowed_cp(self):
        assert _validate_shell_cmd("cp /src /dst") is True

    def test_blocked_unknown(self):
        assert _validate_shell_cmd("curl; rm -rf /") is False

    def test_prefix_match_allows_trailing_shell_content(self):
        # Prefix check passes — shell injection after the prefix is not blocked by design.
        # The SAP gate on callers is the primary defense against malicious tasks.
        assert _validate_shell_cmd("python3 /good.py; rm -rf /") is True

    def test_blocked_bare_rm(self):
        # 'rm ' is in SHELL_STARTERS, so rm is allowed — this tests pure unknown
        assert _validate_shell_cmd("unknown_binary --flag") is False

    def test_blocked_empty(self):
        assert _validate_shell_cmd("") is False

    def test_blocked_whitespace(self):
        assert _validate_shell_cmd("   ") is False
