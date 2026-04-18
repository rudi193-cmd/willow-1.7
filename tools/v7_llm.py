#!/usr/bin/env python3
"""
v7_llm.py — Fleet LLM client for Yggdrasil v7 data pipeline.

Supports Groq, SambaNova, OpenRouter via OpenAI-compatible API.
All providers share the same HTTP call shape.

Config (env vars):
  WILLOW_V7_PROVIDER   groq | sambanova | openrouter  (default: groq)
  WILLOW_V7_MODEL      model name override
  GROQ_API_KEY
  SAMBANOVA_API_KEY
  OPENROUTER_API_KEY

b17: V7LM1
ΔΣ=42
"""

import json
import os
import time
import urllib.error
import urllib.request

_PROVIDERS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.3-70b-versatile",
        "key_env": "GROQ_API_KEY",
    },
    "sambanova": {
        "base_url": "https://api.sambanova.ai/v1",
        "default_model": "Meta-Llama-3.3-70B-Instruct",
        "key_env": "SAMBANOVA_API_KEY",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "google/gemini-flash-1.5",
        "key_env": "OPENROUTER_API_KEY",
    },
}

_MAX_RETRIES = 3
_RETRY_DELAY = 2.0


def _provider_config() -> tuple[str, str, str]:
    """Return (base_url, model, api_key) for the configured provider."""
    name = os.environ.get("WILLOW_V7_PROVIDER", "groq").lower()
    if name not in _PROVIDERS:
        raise ValueError(f"Unknown provider {name!r}. Choose: {list(_PROVIDERS)}")
    cfg = _PROVIDERS[name]
    model = os.environ.get("WILLOW_V7_MODEL", cfg["default_model"])
    key = os.environ.get(cfg["key_env"], "")
    if not key:
        raise ValueError(f"API key not set: {cfg['key_env']}")
    return cfg["base_url"], model, key


def call_llm(prompt: str, system: str = "", temperature: float = 0.3, max_tokens: int = 300) -> str:
    """
    Call the configured fleet LLM. Returns the response text.
    Retries up to _MAX_RETRIES times on transient errors.
    """
    base_url, model, api_key = _provider_config()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode()

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    url = f"{base_url}/chat/completions"
    last_err = None

    for attempt in range(_MAX_RETRIES):
        try:
            req = urllib.request.Request(url, data=payload, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
                return data["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:200]
            last_err = f"HTTP {e.code}: {body}"
            if e.code in (429, 500, 502, 503):
                time.sleep(_RETRY_DELAY * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = str(e)
            time.sleep(_RETRY_DELAY * (attempt + 1))

    raise RuntimeError(f"LLM call failed after {_MAX_RETRIES} attempts: {last_err}")


def provider_info() -> str:
    """Return human-readable provider/model string for logging."""
    name = os.environ.get("WILLOW_V7_PROVIDER", "groq")
    cfg = _PROVIDERS.get(name, {})
    model = os.environ.get("WILLOW_V7_MODEL", cfg.get("default_model", "?"))
    return f"{name}/{model}"
