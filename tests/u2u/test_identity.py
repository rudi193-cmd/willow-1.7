import pytest
from pathlib import Path
from u2u.identity import Identity

def test_generate_creates_keypair(tmp_path):
    ident = Identity.generate(tmp_path / "identity.json")
    assert ident.public_key_hex
    assert len(ident.public_key_hex) == 64

def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "identity.json"
    ident = Identity.generate(path)
    loaded = Identity.load(path)
    assert loaded.public_key_hex == ident.public_key_hex

def test_sign_and_verify(tmp_path):
    ident = Identity.generate(tmp_path / "identity.json")
    message = b"hello u2u"
    sig = ident.sign(message)
    assert ident.verify(message, sig, ident.public_key_hex)

def test_verify_fails_wrong_message(tmp_path):
    ident = Identity.generate(tmp_path / "identity.json")
    sig = ident.sign(b"correct")
    assert not ident.verify(b"wrong", sig, ident.public_key_hex)

def test_verify_fails_wrong_key(tmp_path):
    a = Identity.generate(tmp_path / "a.json")
    b = Identity.generate(tmp_path / "b.json")
    sig = a.sign(b"hello")
    assert not b.verify(b"hello", sig, b.public_key_hex)
