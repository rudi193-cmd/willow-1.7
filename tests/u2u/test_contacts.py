import pytest
from u2u.contacts import ContactStore, Contact

def test_add_and_get(tmp_path):
    store = ContactStore(tmp_path / "contacts.json")
    store.add("jeles@192.168.1.42:8550", public_key_hex="abcd1234", name="Jeles")
    c = store.get("jeles@192.168.1.42:8550")
    assert c.name == "Jeles"
    assert c.public_key_hex == "abcd1234"

def test_save_and_reload(tmp_path):
    path = tmp_path / "contacts.json"
    store = ContactStore(path)
    store.add("jeles@192.168.1.42:8550", public_key_hex="abcd1234", name="Jeles")
    store.save()
    store2 = ContactStore(path)
    assert store2.get("jeles@192.168.1.42:8550").name == "Jeles"

def test_unknown_returns_none(tmp_path):
    store = ContactStore(tmp_path / "contacts.json")
    assert store.get("nobody@nowhere:8550") is None

def test_block_contact(tmp_path):
    store = ContactStore(tmp_path / "contacts.json")
    store.add("spam@evil:8550", public_key_hex="ff", name="Spam")
    store.block("spam@evil:8550")
    assert store.get("spam@evil:8550").blocked is True

def test_all_returns_list(tmp_path):
    store = ContactStore(tmp_path / "contacts.json")
    store.add("a@host:8550", public_key_hex="aa", name="A")
    store.add("b@host:8550", public_key_hex="bb", name="B")
    assert len(store.all()) == 2

def test_block_unknown_returns_false(tmp_path):
    store = ContactStore(tmp_path / "contacts.json")
    result = store.block("nobody@nowhere:8550")
    assert result is False

def test_load_malformed_json_raises(tmp_path):
    path = tmp_path / "contacts.json"
    path.write_text("not valid json{{{")
    with pytest.raises(ValueError, match="Cannot load contacts"):
        ContactStore(path)
