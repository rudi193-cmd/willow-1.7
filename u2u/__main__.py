# willow-1.7/u2u/__main__.py
# b17: U2UM1
"""CLI: python3 -m u2u [listen|send|status]"""

import argparse
import asyncio
import sys
from pathlib import Path

_CONTACTS_PATH = Path.home() / ".willow" / "u2u_contacts.json"
_IDENTITY_PATH = Path.home() / ".willow" / "u2u_identity.json"
_DEFAULT_PORT  = 8550


def cmd_status(args):
    from u2u.identity import Identity
    from u2u.contacts import ContactStore
    ident = Identity.load_or_generate(_IDENTITY_PATH)
    store = ContactStore(_CONTACTS_PATH)
    print(f"U2U identity : {ident.public_key_hex[:16]}...")
    print(f"Contacts     : {len(store.all())}")
    for c in store.all():
        status = "BLOCKED" if c.blocked else "ok"
        print(f"  {c.name or c.addr} [{status}]")


def cmd_listen(args):
    from u2u.identity import Identity
    from u2u.contacts import ContactStore
    from u2u.consent import ConsentGate
    from u2u.listener import U2UListener
    from u2u.packets import PacketType
    from u2u import dispatcher

    ident = Identity.load_or_generate(_IDENTITY_PATH)
    store = ContactStore(_CONTACTS_PATH)
    gate  = ConsentGate(store)

    def _on_note(p):
        h = p["header"]
        pl = p["payload"]
        print(f"\n[NOTE] from {h['from']}")
        print(f"  {pl.get('subject','')}: {pl.get('body','')}")

    def _on_knock(p):
        h = p["header"]
        print(f"\n[KNOCK] {h['from']} wants to connect.")

    dispatcher.register(PacketType.NOTE,  _on_note)
    dispatcher.register(PacketType.KNOCK, _on_knock)

    host = args.host
    port = args.port

    async def _run():
        listener = U2UListener(host=host, port=port, identity=ident, consent=gate)
        async with listener.serve():
            print(f"U2U listening on {host}:{port}  (Ctrl+C to stop)")
            try:
                await asyncio.Event().wait()
            except (asyncio.CancelledError, KeyboardInterrupt):
                pass

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        print("\nStopped.")


def cmd_send(args):
    from u2u.identity import Identity
    from u2u.contacts import ContactStore
    from u2u.sender import send
    from u2u.packets import PacketType

    ident = Identity.load_or_generate(_IDENTITY_PATH)
    store = ContactStore(_CONTACTS_PATH)
    contact = store.get(args.to)
    if contact is None:
        print(f"Unknown contact: {args.to}. Add them first.", file=sys.stderr)
        sys.exit(1)

    my_addr = f"{args.from_name}@{args.endpoint}"
    ok = send(PacketType.NOTE, my_addr, args.to,
              {"subject": args.subject, "body": args.body}, ident)
    print("sent" if ok else "failed")


def main():
    p = argparse.ArgumentParser(prog="python3 -m u2u", description="U2U direct messaging")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("status", help="Show identity and contacts")

    lp = sub.add_parser("listen", help="Start U2U listener")
    lp.add_argument("--host", default="0.0.0.0")
    lp.add_argument("--port", type=int, default=_DEFAULT_PORT)

    sp = sub.add_parser("send", help="Send a NOTE to a contact")
    sp.add_argument("to", help="contact address e.g. jeles@192.168.1.42:8550")
    sp.add_argument("subject")
    sp.add_argument("body")
    sp.add_argument("--from-name", default="sean", dest="from_name")
    sp.add_argument("--endpoint", default=f"localhost:{_DEFAULT_PORT}")

    args = p.parse_args()
    if args.cmd == "status":   cmd_status(args)
    elif args.cmd == "listen": cmd_listen(args)
    elif args.cmd == "send":   cmd_send(args)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
