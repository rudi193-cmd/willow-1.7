import asyncio
import pytest
from u2u.identity import Identity
from u2u.contacts import ContactStore
from u2u.consent import ConsentGate
from u2u import dispatcher
from u2u.listener import U2UListener
from u2u.sender import send_packet
from u2u.packets import PacketType

TEST_PORT = 18550  # avoid 8550 in tests

@pytest.fixture(autouse=True)
def reset_dispatcher():
    dispatcher.clear()
    yield
    dispatcher.clear()

@pytest.fixture
def ident(tmp_path):
    return Identity.generate(tmp_path / "id.json")

@pytest.fixture
def store(tmp_path, ident):
    s = ContactStore(tmp_path / "contacts.json")
    s.add(f"sender@localhost:{TEST_PORT}", public_key_hex=ident.public_key_hex, name="Sender")
    return s

async def test_send_and_receive(ident, store, tmp_path):
    received = []
    dispatcher.register(PacketType.NOTE, lambda p: received.append(p))

    gate = ConsentGate(store)
    listener = U2UListener(
        host="127.0.0.1", port=TEST_PORT,
        identity=ident, consent=gate,
    )

    async with listener.serve():
        await asyncio.sleep(0.05)
        ok = await send_packet(
            PacketType.NOTE,
            from_addr=f"sender@localhost:{TEST_PORT}",
            to_addr=f"receiver@127.0.0.1:{TEST_PORT}",
            payload={"subject": "hello", "body": "world"},
            identity=ident,
        )
        assert ok
        await asyncio.sleep(0.1)

    assert len(received) == 1
    assert received[0]["payload"]["subject"] == "hello"

async def test_unknown_sender_note_dropped(ident, tmp_path):
    received = []
    dispatcher.register(PacketType.NOTE, lambda p: received.append(p))

    store = ContactStore(tmp_path / "empty.json")  # no contacts
    gate = ConsentGate(store)
    listener = U2UListener(host="127.0.0.1", port=TEST_PORT+1, identity=ident, consent=gate)

    async with listener.serve():
        await asyncio.sleep(0.05)
        await send_packet(
            PacketType.NOTE,
            from_addr="stranger@127.0.0.1:9999",
            to_addr=f"receiver@127.0.0.1:{TEST_PORT+1}",
            payload={"subject": "hi", "body": "ignored"},
            identity=ident,
        )
        await asyncio.sleep(0.1)

    assert len(received) == 0

async def test_tampered_packet_dropped(ident, store):
    received = []
    dispatcher.register(PacketType.NOTE, lambda p: received.append(p))

    gate = ConsentGate(store)
    listener = U2UListener(host="127.0.0.1", port=TEST_PORT+2, identity=ident, consent=gate)

    # Build a valid packet then tamper with it
    from u2u.packets import Packet
    packet = Packet.build(
        PacketType.NOTE,
        from_addr=f"sender@localhost:{TEST_PORT}",
        to_addr=f"receiver@127.0.0.1:{TEST_PORT+2}",
        payload={"subject": "legit", "body": "original"},
        identity=ident,
    )
    packet["payload"]["body"] = "tampered"
    wire = Packet.serialize(packet)

    async with listener.serve():
        await asyncio.sleep(0.05)
        reader, writer = await asyncio.open_connection("127.0.0.1", TEST_PORT+2)
        writer.write(wire)
        await writer.drain()
        writer.close()
        await asyncio.sleep(0.1)

    assert len(received) == 0
