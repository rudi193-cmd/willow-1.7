# willow-1.7/u2u/dispatcher.py
# b17: U2UD1
"""U2U inbound packet dispatcher — routes by type to registered handlers."""

import logging
from typing import Callable, Optional
from u2u.packets import PacketType

log = logging.getLogger("u2u.dispatcher")

_REGISTRY: dict[str, Callable] = {}


def register(ptype: PacketType, handler: Callable) -> None:
    """Register a handler for a packet type. Last registration wins."""
    _REGISTRY[ptype.value] = handler
    log.debug("registered handler for %s: %s", ptype.value, handler.__name__)


def dispatch(packet: dict) -> Optional[dict]:
    """Route packet to handler. Returns handler result or None."""
    ptype = packet.get("header", {}).get("type", "")
    handler = _REGISTRY.get(ptype)
    if handler is None:
        log.debug("no handler for type=%s — dropped", ptype)
        return None
    try:
        return handler(packet)
    except Exception as e:
        log.error("handler error type=%s: %s", ptype, e)
        return None


def registered_types() -> list[str]:
    return list(_REGISTRY.keys())


def clear() -> None:
    """Clear all handlers. Used in tests."""
    _REGISTRY.clear()
