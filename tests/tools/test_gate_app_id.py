"""Tests for app_id sanitization in sap/core/gate.py.
b17: GAI1
ΔΣ=42
"""
import sys
import pytest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sap.core.gate import _validate_app_id


class TestValidateAppId:
    def test_valid_simple(self):
        assert _validate_app_id("safe-app-utety-chat") == "safe-app-utety-chat"

    def test_valid_underscore(self):
        assert _validate_app_id("hanuman") == "hanuman"

    def test_valid_alphanumeric(self):
        assert _validate_app_id("agent2") == "agent2"

    def test_rejects_path_traversal(self):
        with pytest.raises(ValueError):
            _validate_app_id("../../../etc/passwd")

    def test_rejects_slash(self):
        with pytest.raises(ValueError):
            _validate_app_id("safe/app")

    def test_rejects_null_byte(self):
        with pytest.raises(ValueError):
            _validate_app_id("safe\x00app")

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            _validate_app_id("")

    def test_rejects_dotdot_embedded(self):
        with pytest.raises(ValueError):
            _validate_app_id("safe..app")

    def test_rejects_starts_with_dot(self):
        with pytest.raises(ValueError):
            _validate_app_id(".hidden")

    def test_authorized_logs_invalid_app_id(self):
        """authorized() with hostile app_id calls _log_gap and returns False."""
        from unittest.mock import patch
        with patch("sap.core.gate._log_gap") as mock_gap:
            from sap.core.gate import authorized
            result = authorized("../../etc/passwd")
        assert result is False
        mock_gap.assert_called_once()
        call_args = mock_gap.call_args
        assert "Invalid app_id" in call_args[0][1]

    def test_get_manifest_rejects_hostile_app_id(self):
        """get_manifest() with hostile app_id returns None without calling authorized()."""
        from unittest.mock import patch
        from sap.core.gate import get_manifest
        with patch("sap.core.gate.authorized") as mock_auth:
            result = get_manifest("../../../etc/passwd")
        assert result is None
        mock_auth.assert_not_called()
