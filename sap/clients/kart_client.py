"""
SAP Kart Client
b17: K8756
ΔΣ=42

The wire between Kart and SAP.

Kart has previously bypassed SAP entirely — dispatching shell commands and writing
to Postgres without passing through the consent layer. This client closes that gap.

Usage (in any Kart task or orchestrator):

    from sap.clients.kart_client import authorize_task, build_task_context

    # Gate check before executing
    if not authorize_task(task):
        raise PermissionError(f"Task {task['task_id']} not SAP-authorized")

    # Assemble context for task execution
    ctx = build_task_context(task)
"""

import logging
from typing import Optional

from sap.core.gate import authorized
from sap.core.context import assemble
from sap.core.deliver import to_string

logger = logging.getLogger("sap.clients.kart")

# Default app_id for Kart tasks that don't specify one.
# SAFE folder: SAFE/Applications/utety-chat/professors/Kart/
KART_DEFAULT_APP = "Kart"


def authorize_task(task: dict) -> bool:
    """
    Check whether a Kart task is SAP-authorized.

    Looks for app_id in:
    - task["metadata"]["sap_app_id"]  — explicit per-task authorization
    - task["agent"]                   — agent name maps to SAFE folder
    - Falls back to KART_DEFAULT_APP

    Returns True if authorized, False if not.
    Denied tasks are logged to sap/log/gaps.jsonl automatically by gate.py.
    """
    metadata = task.get("metadata") or {}
    if isinstance(metadata, str):
        import json
        try:
            metadata = json.loads(metadata)
        except Exception:
            metadata = {}

    raw_app_id = (
        metadata.get("sap_app_id")
        or task.get("agent", "").title()
        or KART_DEFAULT_APP
    )
    app_id = raw_app_id or KART_DEFAULT_APP

    result = authorized(app_id)
    if not result:
        logger.warning(
            "Kart task %s denied by SAP gate (app_id=%s)",
            task.get("task_id", "unknown"),
            app_id,
        )
    return result


def build_task_context(task: dict, max_chars: int = 2000) -> Optional[str]:
    """
    Assemble SAP context string for a Kart task.

    Uses the task subject + description as the query.
    Returns formatted context string for injection into task execution,
    or None if not authorized.
    """
    metadata = task.get("metadata") or {}
    if isinstance(metadata, str):
        import json
        try:
            metadata = json.loads(metadata)
        except Exception:
            metadata = {}

    app_id = metadata.get("sap_app_id") or task.get("agent", "").title() or KART_DEFAULT_APP
    query = f"{task.get('subject', '')} {task.get('description', '')}".strip()

    ctx = assemble(app_id, query=query, max_chars=max_chars)
    return to_string(ctx) if ctx else None
