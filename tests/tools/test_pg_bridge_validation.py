"""Tests for pg_bridge schema name validation.
b17: PGVT1
ΔΣ=42
"""
import sys
import pytest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "core"))

from pg_bridge import _validate_schema_name


class TestValidateSchemaName:
    def test_valid_simple(self):
        assert _validate_schema_name("hanuman") == "hanuman"

    def test_valid_with_underscore(self):
        assert _validate_schema_name("safe_app") == "safe_app"

    def test_valid_with_numbers(self):
        assert _validate_schema_name("agent2") == "agent2"

    def test_rejects_injection(self):
        with pytest.raises(ValueError):
            _validate_schema_name("public; DROP TABLE knowledge")

    def test_rejects_uppercase(self):
        with pytest.raises(ValueError):
            _validate_schema_name("Hanuman")

    def test_rejects_starts_with_number(self):
        with pytest.raises(ValueError):
            _validate_schema_name("1agent")

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            _validate_schema_name("")

    def test_rejects_hyphen(self):
        with pytest.raises(ValueError):
            _validate_schema_name("safe-app")
