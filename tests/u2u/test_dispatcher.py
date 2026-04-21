import pytest
from u2u.dispatcher import register, dispatch, registered_types, clear
from u2u.packets import PacketType

@pytest.fixture(autouse=True)
def reset():
    clear()
    yield
    clear()

def test_register_and_dispatch():
    results = []
    register(PacketType.NOTE, lambda p: results.append(p) or {"ok": True})
    dispatch({"header": {"type": "NOTE"}, "payload": {"body": "hi"}})
    assert len(results) == 1
    assert results[0]["payload"]["body"] == "hi"

def test_dispatch_unknown_type_returns_none():
    result = dispatch({"header": {"type": "UNKNOWN"}, "payload": {}})
    assert result is None

def test_dispatch_returns_handler_result():
    register(PacketType.ASK, lambda p: {"answer": 42})
    result = dispatch({"header": {"type": "ASK"}, "payload": {}})
    assert result == {"answer": 42}

def test_handler_exception_returns_none():
    def bad_handler(p):
        raise RuntimeError("boom")
    register(PacketType.ALERT, bad_handler)
    result = dispatch({"header": {"type": "ALERT"}, "payload": {}})
    assert result is None

def test_registered_types():
    register(PacketType.NOTE, lambda p: None)
    register(PacketType.SHARE, lambda p: None)
    types = registered_types()
    assert "NOTE" in types
    assert "SHARE" in types

def test_last_registration_wins():
    register(PacketType.NOTE, lambda p: {"v": 1})
    register(PacketType.NOTE, lambda p: {"v": 2})
    result = dispatch({"header": {"type": "NOTE"}, "payload": {}})
    assert result == {"v": 2}
