import pytest, json, time
from u2u.packets import Packet, PacketType, PacketError
from u2u.identity import Identity

@pytest.fixture
def ident(tmp_path):
    return Identity.generate(tmp_path / "id.json")

def test_packet_types_exist():
    assert PacketType.KNOCK
    assert PacketType.NOTE
    assert PacketType.ASK
    assert PacketType.REPLY
    assert PacketType.ALERT
    assert PacketType.SHARE

def test_build_and_sign(ident):
    p = Packet.build(
        ptype=PacketType.NOTE,
        from_addr="sean@localhost:8550",
        to_addr="jeles@192.168.1.42:8550",
        payload={"subject": "hi", "body": "test"},
        identity=ident,
    )
    assert p["header"]["type"] == "NOTE"
    assert p["header"]["from"] == "sean@localhost:8550"
    assert "sig" in p["header"]

def test_validate_good_packet(ident):
    p = Packet.build(
        PacketType.NOTE, "sean@a:8550", "jeles@b:8550",
        {"subject": "x", "body": "y"}, ident,
    )
    assert Packet.validate(p, ident.public_key_hex)

def test_validate_tampered_payload(ident):
    p = Packet.build(
        PacketType.NOTE, "sean@a:8550", "jeles@b:8550",
        {"subject": "x", "body": "y"}, ident,
    )
    p["payload"]["body"] = "tampered"
    assert not Packet.validate(p, ident.public_key_hex)

def test_serialize_deserialize(ident):
    p = Packet.build(
        PacketType.NOTE, "sean@a:8550", "jeles@b:8550",
        {"subject": "x", "body": "y"}, ident,
    )
    wire = Packet.serialize(p)
    assert isinstance(wire, bytes)
    assert wire.endswith(b"\n")
    p2 = Packet.deserialize(wire)
    assert p2["header"]["type"] == "NOTE"

def test_expired_packet_fails(ident):
    p = Packet.build(
        PacketType.NOTE, "sean@a:8550", "jeles@b:8550",
        {"subject": "x", "body": "y"}, ident, ttl=-1,
    )
    assert not Packet.validate(p, ident.public_key_hex)
