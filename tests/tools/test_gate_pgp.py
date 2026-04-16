"""Tests for PGP fingerprint pinning in sap/core/gate.py.
b17: GPT1
ΔΣ=42
"""
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sap.core.gate import _verify_pgp


def _make_validsig_line(primary_fp: str, subkey_fp: str = None) -> str:
    if subkey_fp is None:
        subkey_fp = primary_fp
    # VALIDSIG format: fingerprint date timestamp sig-timestamp expire ver pk-algo hash-algo sig-class primary-fp
    return (
        f"[GNUPG:] VALIDSIG {subkey_fp} 2026-04-16 1744800000 0 0 4 22 2 00 {primary_fp}"
    )


SEAN_FP = "96B92D78875F60BE229A0A348F414B8C1B402BB0"
OTHER_FP = "DEADBEEF" * 5  # 40 chars, clearly not Sean's


class TestVerifyPgp:
    def _run(self, manifest_path, returncode, stdout="", stderr=""):
        mock_result = MagicMock()
        mock_result.returncode = returncode
        mock_result.stdout = stdout.encode()
        mock_result.stderr = stderr.encode()
        with patch("subprocess.run", return_value=mock_result), \
             patch("sap.core.gate._EXPECTED_FP", SEAN_FP):
            return _verify_pgp(manifest_path)

    def test_valid_signature_correct_key(self, tmp_path):
        manifest = tmp_path / "safe-app-manifest.json"
        manifest.write_text("{}")
        sig = tmp_path / "safe-app-manifest.json.sig"
        sig.write_text("fake-sig")
        stdout = _make_validsig_line(SEAN_FP)
        ok, reason = self._run(manifest, returncode=0, stdout=stdout)
        assert ok is True
        assert reason == "signature verified"

    def test_wrong_key_rejected(self, tmp_path):
        manifest = tmp_path / "safe-app-manifest.json"
        manifest.write_text("{}")
        sig = tmp_path / "safe-app-manifest.json.sig"
        sig.write_text("fake-sig")
        stdout = _make_validsig_line(OTHER_FP)
        ok, reason = self._run(manifest, returncode=0, stdout=stdout)
        assert ok is False
        assert "unexpected key" in reason

    def test_gpg_failure_rejected(self, tmp_path):
        manifest = tmp_path / "safe-app-manifest.json"
        manifest.write_text("{}")
        sig = tmp_path / "safe-app-manifest.json.sig"
        sig.write_text("fake-sig")
        ok, reason = self._run(manifest, returncode=2, stderr="BAD signature")
        assert ok is False
        assert "gpg verify failed" in reason

    def test_no_validsig_line_rejected(self, tmp_path):
        manifest = tmp_path / "safe-app-manifest.json"
        manifest.write_text("{}")
        sig = tmp_path / "safe-app-manifest.json.sig"
        sig.write_text("fake-sig")
        ok, reason = self._run(manifest, returncode=0, stdout="[GNUPG:] GOODSIG something\n")
        assert ok is False
        assert "no VALIDSIG" in reason

    def test_missing_sig_file(self, tmp_path):
        manifest = tmp_path / "safe-app-manifest.json"
        manifest.write_text("{}")
        # no .sig file
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result):
            ok, reason = _verify_pgp(manifest)
        assert ok is False
        assert "No signature file" in reason

    def test_subkey_signature_uses_primary_fp(self, tmp_path):
        """VALIDSIG field 11 is primary key fp — not the subkey used to sign."""
        manifest = tmp_path / "safe-app-manifest.json"
        manifest.write_text("{}")
        sig = tmp_path / "safe-app-manifest.json.sig"
        sig.write_text("fake-sig")
        subkey_fp = "A" * 40
        stdout = _make_validsig_line(primary_fp=SEAN_FP, subkey_fp=subkey_fp)
        ok, reason = self._run(manifest, returncode=0, stdout=stdout)
        assert ok is True  # primary key matches even though subkey is different
