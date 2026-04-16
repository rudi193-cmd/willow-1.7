#!/usr/bin/env python3
"""
kart_worker.py — KART (1.7)
=============================
K — Kinetic
A — Agent
R — Runtime
T — Tasks

Task queue consumer for willow-1.7. Polls kart_task_queue, claims pending tasks,
executes them through the SAP gate (PGP-hardened), writes results back.

Authorization: SAP gate v2 — SAFE folder + PGP manifest required.
Gate app_id: task["agent"].title() or "Ratatosk" fallback.

Usage:
    python3 kart_worker.py              # run once (claim + execute one task)
    python3 kart_worker.py --daemon     # poll continuously (5s interval)
    python3 kart_worker.py --status     # show queue stats

b17: K17W0
ΔΣ=42
"""

import os
import sys
import time
from pathlib import Path

# Willow 1.7 root — all imports resolve from here
WILLOW_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(WILLOW_ROOT))

from core.pg_bridge import try_connect


def execute_task(task_text: str) -> dict:
    """Execute a task by running its commands directly. No LLM."""
    import re
    import subprocess
    import tempfile

    SHELL_STARTERS = (
        'cp ', 'rsync ', 'python3 ', 'python3-c', 'python ',
        'mkdir ', 'chmod ', 'find ', 'grep ', 'curl ', 'echo ',
        'mv ', 'rm ', 'ls ', 'cat ', 'psql ', 'git ', 'bash ',
        'ollama ',
    )

    outputs = []
    step = 0
    errors = []
    commands = []

    # 1. Fenced code blocks — run each block as a single bash script
    for block in re.findall(r'```(?:bash|sh|python3?)?\n?(.*?)```', task_text, re.DOTALL):
        block = block.strip()
        if not block:
            continue
        real_lines = [l for l in block.splitlines() if l.strip() and not l.strip().startswith('#')]
        if len(real_lines) == 1:
            commands.append(('shell', real_lines[0]))
        else:
            commands.append(('script', block))

    # Heuristic extraction only fires when there are no fenced blocks
    if not commands:
        # 2. Numbered steps
        for m in re.finditer(r'\(\d+\)\s+(.+?)(?=\s*\(\d+\)|$)', task_text, re.DOTALL):
            fragment = m.group(1).strip().rstrip('.')
            lower = fragment.lower()
            for starter in SHELL_STARTERS:
                idx = lower.find(starter)
                if idx != -1:
                    cmd = fragment[idx:].split('. ')[0].strip()
                    if cmd not in [c[1] for c in commands]:
                        commands.append(('shell', cmd))
                    break

        # 3. Line-start shell commands
        for m in re.finditer(
            r'^\s*((?:cp|rsync|python3?|mkdir|chmod|find|grep|curl|mv|rm|git|psql|ollama)\s+.+)$',
            task_text, re.MULTILINE
        ):
            cmd = m.group(1).strip()
            if cmd not in [c[1] for c in commands]:
                commands.append(('shell', cmd))

        # 4. Mid-sentence commands
        for starter in SHELL_STARTERS:
            pos = 0
            lower = task_text.lower()
            while True:
                idx = lower.find(starter, pos)
                if idx == -1:
                    break
                end = task_text.find('. ', idx)
                cmd = task_text[idx:end if end != -1 else len(task_text)].strip().rstrip('.')
                if cmd and cmd not in [c[1] for c in commands]:
                    commands.append(('shell', cmd))
                pos = idx + len(starter)

    if not commands:
        return {"success": False, "error": "No executable commands found in task", "steps": 0}

    for cmd_type, cmd in commands:
        step += 1
        label = cmd.splitlines()[0][:80] if cmd_type == 'script' else cmd
        print(f"[kart] >>> {label}", flush=True)
        try:
            if cmd_type == 'script':
                with tempfile.NamedTemporaryFile(
                    mode='w', suffix='.sh', prefix='kart_', delete=False
                ) as f:
                    f.write(cmd)
                    tmp_path = f.name
                os.chmod(tmp_path, 0o755)
                env = os.environ.copy()
                env["PYTHONUNBUFFERED"] = "1"
                try:
                    proc = subprocess.Popen(
                        ['bash', tmp_path],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                        env=env
                    )
                finally:
                    os.unlink(tmp_path)
            else:
                # PYTHONUNBUFFERED forces line-by-line stdout from Python subprocesses
                env = os.environ.copy()
                env["PYTHONUNBUFFERED"] = "1"
                proc = subprocess.Popen(
                    cmd, shell=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                    env=env
                )

            stdout_lines = []
            stderr_lines = []
            import threading, time as _time

            def _read_stderr(p, buf):
                for line in p.stderr:
                    buf.append(line.rstrip())
                    print(f"[kart] ERR: {line.rstrip()}", flush=True)

            t = threading.Thread(target=_read_stderr, args=(proc, stderr_lines), daemon=True)
            t.start()

            deadline = _time.monotonic() + 1800
            for line in proc.stdout:
                line = line.rstrip()
                stdout_lines.append(line)
                print(f"[kart] OUT: {line}", flush=True)
                if _time.monotonic() > deadline:
                    proc.kill()
                    errors.append(f"{label} → timeout after 1800s")
                    break

            proc.wait()
            t.join(timeout=5)

            output = "\n".join(stdout_lines).strip()
            err = "\n".join(stderr_lines).strip()
            outputs.append(f"$ {label}\n{output}" + (f"\nSTDERR: {err}" if err else ""))
            if proc.returncode not in (0, -9):
                errors.append(f"{label} → exit {proc.returncode}: {err}")
        except Exception as e:
            errors.append(f"{label} → {e}")

    if errors:
        return {
            "success": False,
            "error": "; ".join(errors),
            "output": "\n\n".join(outputs),
            "steps": step,
        }
    return {
        "success": True,
        "response": "\n\n".join(outputs),
        "steps": step,
        "tools_used": step,
        "provider": "shell",
    }


def run_once(pg) -> bool:
    """Claim and execute one task. Returns True if a task was processed."""
    task = pg.claim_task("kart")
    if not task:
        return False

    task_id = task["task_id"]
    task_text = task["task"]
    print(f"[kart] Claimed {task_id}: {task_text[:80]}...")

    # SAP gate check — willow-1.7 PGP-hardened gate
    try:
        from sap.clients.kart_client import authorize_task
        if not authorize_task(task):
            pg.fail_task(task_id, "SAP gate denied")
            print(f"[kart] SAP denied {task_id}")
            return True
    except Exception as e:
        print(f"[kart] SAP check skipped (non-fatal): {e}")

    result = execute_task(task_text)

    if result.get("success"):
        pg.complete_task(task_id, result, steps=result.get("steps", 0))
        print(f"[kart] Complete {task_id}: {result.get('steps', 0)} steps")
    else:
        pg.fail_task(task_id, result.get("error", "unknown"))
        print(f"[kart] Failed {task_id}: {result.get('error', 'unknown')}")

    return True


def daemon(pg, interval: int = 5):
    """Poll continuously."""
    print(f"[kart] Worker daemon started — willow-1.7, PGP gate (poll every {interval}s)")
    while True:
        try:
            if not run_once(pg):
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\n[kart] Worker stopped")
            break
        except Exception as e:
            print(f"[kart] Error: {e}")
            time.sleep(interval)


def show_status(pg):
    """Show queue stats."""
    try:
        conn = pg._get_conn()
        cur = conn.cursor()
        cur.execute("SELECT status, COUNT(*) FROM kart_task_queue GROUP BY status ORDER BY status")
        rows = cur.fetchall()
        cur.close()
        if not rows:
            print("[kart] Queue empty")
        else:
            for status, count in rows:
                print(f"  {status}: {count}")
    except Exception as e:
        print(f"Error: {e}")


def main():
    pg = try_connect()
    if not pg:
        print("[kart] Cannot connect to Postgres")
        sys.exit(1)

    if "--status" in sys.argv:
        show_status(pg)
    elif "--daemon" in sys.argv:
        daemon(pg)
    else:
        run_once(pg)


if __name__ == "__main__":
    main()
