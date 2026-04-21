import pytest
from u2u.contacts import ContactStore
from u2u.consent import ConsentGate, ConsentResult
from u2u.packets import PacketType

@pytest.fixture
def store(tmp_path):
    s = ContactStore(tmp_path / "contacts.json")
    s.add("friend@host:8550", public_key_hex="aabb", name="Friend")
    return s

def test_known_contact_note_allowed(store):
    gate = ConsentGate(store)
    assert gate.check("friend@host:8550", PacketType.NOTE) == ConsentResult.ALLOW

def test_unknown_sender_knock_goes_pending(store):
    gate = ConsentGate(store)
    assert gate.check("stranger@host:8550", PacketType.KNOCK) == ConsentResult.PENDING

def test_unknown_sender_note_denied(store):
    gate = ConsentGate(store)
    assert gate.check("stranger@host:8550", PacketType.NOTE) == ConsentResult.DENY

def test_blocked_contact_denied(store):
    store.block("friend@host:8550")
    gate = ConsentGate(store)
    assert gate.check("friend@host:8550", PacketType.NOTE) == ConsentResult.DENY

def test_known_knock_allowed(store):
    gate = ConsentGate(store)
    assert gate.check("friend@host:8550", PacketType.KNOCK) == ConsentResult.ALLOW

def test_reply_always_allowed(store):
    gate = ConsentGate(store)
    assert gate.check("friend@host:8550", PacketType.REPLY) == ConsentResult.ALLOW
