"""
SAP Generic App Client
b17: 26H27
ΔΣ=42

One client to rule them all. Works for any safe-app that has:
- A SAFE folder at SAFE/Applications/<app_id>/
- A personas.py with a PERSONAS dict and get_persona(name) function

Usage:
    from sap.clients.generic_client import AppClient

    client = AppClient(
        app_id="LawGazelle",
        personas_path="/home/sean-campbell/github/safe-apps/safe-app-law-gazelle/personas.py",
        persona_name="Gazelle",
    )
    response = client.ask("I have a landlord who won't return my deposit.")
"""

import logging
import os
from pathlib import Path
from typing import Optional

from sap.core.gate import authorized
from sap.core.context import assemble
from sap.core.deliver import to_string

logger = logging.getLogger("sap.clients.generic")

DEFAULT_MODEL = "llama3.2:1b"


def _load_persona_from(personas_path: Path, persona_name: str) -> str:
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("_app_personas", personas_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        # Try get_persona() first, fall back to PERSONAS dict
        get_fn = getattr(mod, "get_persona", None)
        if get_fn:
            return get_fn(persona_name) or ""
        personas = getattr(mod, "PERSONAS", {})
        return personas.get(persona_name, "")
    except Exception as e:
        logger.warning("Could not load personas from %s: %s", personas_path, e)
        return ""


def _ask_ollama(model: str, system_prompt: str, user_message: str) -> Optional[str]:
    options = {"num_thread": int(os.environ.get("SAP_OLLAMA_THREADS", "4"))}

    try:
        import ollama
        client = ollama.Client(host="http://localhost:11434", timeout=300)
        response = client.chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            options=options,
        )
        return response["message"]["content"]
    except ImportError:
        pass
    except Exception as e:
        logger.warning("Ollama library failed (%s) — trying HTTP", e)

    try:
        import requests
        r = requests.post(
            "http://localhost:11434/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "options": options,
                "stream": False,
            },
            timeout=300,
        )
        if r.ok:
            return r.json()["message"]["content"]
        logger.warning("Ollama HTTP error %s — falling back to fleet", r.status_code)
    except Exception as e:
        logger.warning("Ollama HTTP failed (%s) — falling back to fleet", e)

    return _ask_fleet(system_prompt, user_message)


def _ask_fleet(system_prompt: str, user_message: str) -> Optional[str]:
    import json, requests as _req
    creds_path = Path(os.environ.get(
        "WILLOW_CREDENTIALS",
        str(Path(__file__).parent.parent.parent / "credentials.json")
    ))
    try:
        creds = json.loads(creds_path.read_text(encoding="utf-8"))
    except Exception:
        creds = {}

    def _call(url, model, key, provider):
        try:
            r = _req.post(url,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": model,
                      "messages": [{"role": "system", "content": system_prompt},
                                   {"role": "user", "content": user_message}],
                      "max_tokens": 2048},
                timeout=60)
            if r.ok:
                logger.info("Fleet response via %s", provider)
                return r.json()["choices"][0]["message"]["content"]
            return "RATE_LIMITED" if r.status_code == 429 else None
        except Exception as e:
            logger.warning("%s failed: %s", provider, e)
        return None

    for k in ("GROQ_API_KEY", "GROQ_API_KEY_2", "GROQ_API_KEY_3"):
        key = creds.get(k, "")
        if key and key.startswith("gsk_"):
            r = _call("https://api.groq.com/openai/v1/chat/completions",
                      "llama-3.1-8b-instant", key, "Groq")
            if r and r != "RATE_LIMITED":
                return r

    for k in ("CEREBRAS_API_KEY", "CEREBRAS_API_KEY_2", "CEREBRAS_API_KEY_3"):
        key = creds.get(k, "")
        if key and key.startswith("csk-"):
            r = _call("https://api.cerebras.ai/v1/chat/completions",
                      "llama3.1-8b", key, "Cerebras")
            if r and r != "RATE_LIMITED":
                return r

    logger.error("All fleet providers exhausted")
    return None


class AppClient:
    """
    SAP-authorized client for any safe-app with a personas.py.

    Parameters
    ----------
    app_id : str
        Must match the SAFE/Applications/<app_id>/ folder name.
    personas_path : str | Path
        Path to the app's personas.py file.
    persona_name : str
        Key in the PERSONAS dict to use.
    model : str
        Ollama model name. Defaults to DEFAULT_MODEL.
    """

    def __init__(self, app_id: str, personas_path, persona_name: str,
                 model: str = DEFAULT_MODEL,
                 category_filter: Optional[list] = None):
        if not authorized(app_id):
            raise PermissionError(
                f"{app_id} is not SAP-authorized. "
                f"Seed SAFE/Applications/{app_id}/ to grant access."
            )
        self.app_id = app_id
        self.model = model
        self.category_filter = category_filter  # restrict KB queries to these categories
        self.persona_prompt = _load_persona_from(Path(personas_path), persona_name)
        if not self.persona_prompt:
            logger.warning("No persona '%s' in %s — using fallback", persona_name, personas_path)
            self.persona_prompt = f"You are {persona_name}."

    def ask(self, question: str) -> Optional[str]:
        ctx = assemble(
            self.app_id,
            query=question,
            max_chars=1500,
            category_filter=self.category_filter,
        )
        sap_context = to_string(ctx) if ctx else ""
        system_prompt = "\n\n".join(filter(None, [self.persona_prompt, sap_context]))
        return _ask_ollama(self.model, system_prompt, question)
