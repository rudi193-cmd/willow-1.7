import asyncio
import pytest
from u2u.identity import Identity
from u2u.packets import PacketType
from u2u.sender import send_packet, _parse_endpoint


def test_parse_endpoint_basic():
    host, port = _parse_endpoint("sean@192.168.1.10:8550")
    assert host == "192.168.1.10"
    assert port == 8550

def test_parse_endpoint_localhost():
    host, port = _parse_endpoint("jeles@localhost:9000")
    assert host == "localhost"
    assert port == 9000

def test_parse_endpoint_username_with_at():
    # user@domain@host:port — rsplit('@', 1) takes the last @
    host, port = _parse_endpoint("user@example.com@10.0.0.1:8550")
    assert host == "10.0.0.1"
    assert port == 8550

@pytest.mark.asyncio
async def test_send_fails_on_bad_endpoint(tmp_path):
    ident = Identity.generate(tmp_path / "id.json")
    result = await send_packet(
        PacketType.NOTE,
        from_addr="sean@localhost:8550",
        to_addr="jeles@host:notaport",
        payload={"subject": "x", "body": "y"},
        identity=ident,
    )
    assert result is False

@pytest.mark.asyncio
async def test_send_fails_on_no_listener(tmp_path):
    """Sending to a port with no listener returns False, doesn't raise."""
    ident = Identity.generate(tmp_path / "id.json")
    result = await send_packet(
        PacketType.NOTE,
        from_addr="sean@localhost:8550",
        to_addr="jeles@127.0.0.1:19999",  # nothing listening here
        payload={"subject": "test", "body": "hi"},
        identity=ident,
    )
    assert result is False
