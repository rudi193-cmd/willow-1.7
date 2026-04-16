# apps/ — SAP Application Stubs
<!-- b17: APP17 · ΔΣ=42 -->

This directory is reserved for SAP application code that is co-located with the server but separate from the infrastructure.

It is currently empty.

---

## What Goes Here

Applications that:
- Are tightly coupled to the willow-1.7 server (not standalone repos)
- Need access to `sap/clients/` directly
- Do not warrant their own repository

For larger applications (UTETY faculty chat, Law Gazelle, die-namic), the convention is a separate repository (e.g., `safe-app-utety-chat`) pointed at by `WILLOW_UTETY_ROOT` or equivalent environment variables. Those repos live outside this one.

---

## Creating a SAP Application

A minimal SAP application needs:

**1. SAFE folder** (on the SAFE drive or `$WILLOW_SAFE_ROOT`)
```
$WILLOW_SAFE_ROOT/<app_id>/
  safe-app-manifest.json
  safe-app-manifest.json.sig
  cache/context.json          (optional — pre-cached KB context)
```

**2. Manifest**
```json
{
  "app_id": "my-app",
  "name": "My Application",
  "data_streams": [
    {"id": "knowledge"},
    {"id": "reference"}
  ]
}
```

**3. Signature**
```bash
gpg --detach-sign safe-app-manifest.json
# produces safe-app-manifest.json.sig
```

**4. Application code** — uses `AppClient` or a custom gate+context+deliver chain:
```python
from sap.clients.generic_client import AppClient

client = AppClient(
    app_id="my-app",
    personas_path="personas.py",
    persona_name="MyAgent",
)
response = client.ask("What should I do next?")
```

See `sap/clients/README.md` for the full client API.
