#!/usr/bin/env python3
"""
Willow System Dashboard — terminal UI
apps/dashboard.py  b17: DASH1  ΔΣ=42

Run: python3 apps/dashboard.py
Keys: q=quit  r=refresh
"""
import curses
import threading
import time
import os
import json
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ── Color pair IDs ──────────────────────────────────────────────────────────
C_DEFAULT  = 0
C_BLUE     = 1   # WILLOW logo, card values
C_GREEN    = 2   # UP / live / good
C_AMBER    = 3   # warnings / pending
C_DIM      = 4   # subdued labels / subtext
C_HEADER   = 5   # section headers
C_PILL     = 6   # stat pills
C_RED      = 7   # errors
C_BROWN    = 8   # trunk

REFRESH_INTERVAL = 30  # seconds
SWAY_INTERVAL    = 2.0  # seconds per frame

# ── Willow animation ─────────────────────────────────────────────────────────

_POSE_L = [
    r"ƒƒ\ ƒ ƒ ƒ  /ƒ ƒ ",
    r"ƒ ƒ\ ƒ ƒ  / ƒ ƒ ",
    r"ƒ  ƒ\ ƒ  /  ƒ ƒ ",
    r"ƒ  ƒ \  / ƒ  ƒ  ",
    r"ƒ  ƒ  \/  ƒ  ƒ  ",
    r"ƒ  ƒ  ║   ƒ  ƒ  ",
    r"ƒ  ƒ ƒ║    ƒ  ƒ ",
    r"ƒ    ƒ║     ƒ  ƒ",
    r"ƒ     ║ƒ     ƒ  ",
    r"ƒ     ║ƒ      ƒ ",
]

_POSE_C = [
    r"ƒƒ\ ƒ ƒ ƒ /ƒ ƒ  ",
    r"ƒ ƒ\ ƒ ƒ / ƒ ƒ  ",
    r"ƒ  ƒ\   /  ƒ ƒ  ",
    r"ƒ  ƒ \ / ƒ  ƒ   ",
    r"ƒ  ƒ  ║  ƒ  ƒ   ",
    r"ƒ   ƒ ║  ƒ  ƒ   ",
    r"ƒ   ƒ ║ƒ  ƒ  ƒ  ",
    r"ƒ    ƒ║    ƒ  ƒ ",
    r"ƒ     ║ƒ    ƒ  ƒ",
    r"ƒ     ║ƒ     ƒ  ",
]

_POSE_R = [
    r"ƒ\ ƒ ƒ ƒ ƒ/ƒƒ   ",
    r"ƒ \ ƒ ƒ ƒ /ƒ ƒ  ",
    r"ƒ  \ ƒ ƒ /  ƒ ƒ ",
    r"ƒ ƒ \   /ƒ  ƒ ƒ ",
    r"ƒ ƒ  \ / ƒ  ƒ ƒ ",
    r"ƒ ƒ   ║  ƒ  ƒ ƒ ",
    r"ƒ  ƒ ƒ║   ƒ  ƒ  ",
    r"ƒ    ƒ║    ƒ  ƒ ",
    r"ƒ     ║ƒ    ƒ ƒ ",
    r"      ║ƒ     ƒ ƒ",
]

_SWAY_SEQ = [_POSE_L, _POSE_C, _POSE_R, _POSE_C,
             _POSE_L, _POSE_C, _POSE_R, _POSE_C, _POSE_L, _POSE_C]

class _AnimState:
    def __init__(self):
        self.lock = threading.Lock()
        self.idx = 0
        self.last = time.time()

    def tick(self):
        now = time.time()
        with self.lock:
            if now - self.last >= SWAY_INTERVAL:
                self.idx = (self.idx + 1) % len(_SWAY_SEQ)
                self.last = now

    def frame(self):
        with self.lock:
            return _SWAY_SEQ[self.idx]

ANIM = _AnimState()

# ── Data model ──────────────────────────────────────────────────────────────

class SystemData:
    def __init__(self):
        self.lock = threading.Lock()
        self.ts = "—"
        self.pg_knowledge = "—"
        self.pg_edges = "—"
        self.pg_entities = "—"
        self.kart_pending = "—"
        self.kart_running = "—"
        self.kart_done = "—"
        self.ollama_running = False
        self.ollama_ygg = "—"
        self.manifests_pass = "—"
        self.manifests_total = "—"
        self.local_collections = "—"
        self.local_records = "—"
        self.log = ["Willow dashboard starting..."]
        self.error = None

    def push_log(self, msg):
        with self.lock:
            self.log.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
            if len(self.log) > 40:
                self.log = self.log[-40:]

DATA = SystemData()


# ── Fetch helpers ────────────────────────────────────────────────────────────

def _fmt(n):
    if isinstance(n, int):
        if n >= 1_000_000:
            return f"{n/1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n/1_000:.0f}K"
    return str(n)


def fetch_postgres():
    try:
        import psycopg2
        dsn = os.environ.get("WILLOW_DB_URL", "")
        if not dsn:
            return
        conn = psycopg2.connect(dsn)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM public.knowledge")
        k = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM public.knowledge_edges")
        e = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM public.entities")
        en = cur.fetchone()[0]
        try:
            cur.execute("SELECT status, COUNT(*) FROM kart.kart_task_queue GROUP BY status")
            kart = dict(cur.fetchall())
        except Exception:
            kart = {}
        conn.close()
        with DATA.lock:
            DATA.pg_knowledge = _fmt(k)
            DATA.pg_edges = _fmt(e)
            DATA.pg_entities = _fmt(en)
            DATA.kart_pending = str(kart.get("pending", kart.get("queued", 0)))
            DATA.kart_running = str(kart.get("running", 0))
            DATA.kart_done = str(kart.get("complete", kart.get("completed", 0)))
        DATA.push_log(f"pg: {_fmt(k)} atoms · {_fmt(e)} edges")
    except ImportError:
        DATA.push_log("psycopg2 not available — pg skipped")
    except Exception as ex:
        DATA.push_log(f"pg error: {ex}")


def fetch_ollama():
    try:
        url = "http://localhost:11434/api/tags"
        with urllib.request.urlopen(url, timeout=3) as r:
            data = json.loads(r.read())
        models = [m["name"] for m in data.get("models", [])]
        ygg = sorted([m for m in models if "yggdrasil" in m.lower()], reverse=True)
        latest = ygg[0].split(":")[-1] if ygg else "none"
        with DATA.lock:
            DATA.ollama_running = True
            DATA.ollama_ygg = latest
        DATA.push_log(f"ollama: {len(models)} models · yggdrasil {latest}")
    except Exception:
        with DATA.lock:
            DATA.ollama_running = False
            DATA.ollama_ygg = "down"
        DATA.push_log("ollama: unreachable")


def fetch_manifests():
    try:
        safe_root = os.environ.get(
            "WILLOW_SAFE_ROOT",
            str(Path.home() / "SAFE_backup" / "Applications")
        )
        passed, total = 0, 0
        if os.path.isdir(safe_root):
            for app in os.listdir(safe_root):
                app_dir = Path(safe_root) / app
                mf = app_dir / "manifest.json"
                sig = app_dir / "manifest.sig"
                if mf.exists():
                    total += 1
                    if sig.exists():
                        passed += 1
        with DATA.lock:
            DATA.manifests_pass = str(passed)
            DATA.manifests_total = str(total)
        DATA.push_log(f"manifests: {passed}/{total} signed")
    except Exception as ex:
        DATA.push_log(f"manifest error: {ex}")


def fetch_local_store():
    try:
        from core.willow_store import WillowStore
        store = WillowStore()
        cols = len(store.list_collections()) if hasattr(store, "list_collections") else "—"
        with DATA.lock:
            DATA.local_collections = str(cols)
        DATA.push_log(f"local store: {cols} collections")
    except Exception:
        pass


def refresh_all():
    with DATA.lock:
        DATA.ts = datetime.now().strftime("%H:%M:%S")
    DATA.push_log("── refreshing ──")
    fetch_postgres()
    fetch_ollama()
    fetch_manifests()
    fetch_local_store()


def background_refresh(stop_evt):
    while not stop_evt.is_set():
        refresh_all()
        stop_evt.wait(REFRESH_INTERVAL)


# ── Drawing helpers ──────────────────────────────────────────────────────────

def safe_addstr(win, y, x, text, attr=0):
    h, w = win.getmaxyx()
    if y < 0 or y >= h or x < 0 or x >= w:
        return
    max_len = w - x - 1
    if max_len <= 0:
        return
    try:
        win.addstr(y, x, text[:max_len], attr)
    except curses.error:
        pass


def draw_hline(win, y, attr=0):
    h, w = win.getmaxyx()
    if y < 0 or y >= h:
        return
    try:
        win.hline(y, 0, curses.ACS_HLINE, w - 1, attr)
    except curses.error:
        pass


def draw_box_label(win, y, x, label, attr=0):
    safe_addstr(win, y, x, f"[ {label} ]", attr)


# ── Left panel ───────────────────────────────────────────────────────────────

def draw_willow(win, start_y, start_x):
    ANIM.tick()
    frame = ANIM.frame()
    for i, line in enumerate(frame):
        y = start_y + i
        for j, ch in enumerate(line):
            x = start_x + j
            if ch == '║':
                attr = curses.color_pair(C_BROWN) | curses.A_BOLD
            elif ch in ('/', '\\', 'V'):
                attr = curses.color_pair(C_GREEN)
            elif ch == 'ƒ':
                attr = curses.color_pair(C_GREEN) | curses.A_DIM
            else:
                continue
            try:
                win.addch(y, x, ch, attr)
            except curses.error:
                pass


def draw_left(win):
    h, w = win.getmaxyx()
    win.bkgd(' ', curses.color_pair(C_DEFAULT))
    win.erase()

    # ── Willow hero block ──
    tree_h = len(_POSE_C)
    tree_w = max(len(l) for l in _POSE_C)

    # WILLOW title
    safe_addstr(win, 0, 2, "W I L L O W", curses.color_pair(C_BLUE) | curses.A_BOLD)
    safe_addstr(win, 0, 14, "● LIVE", curses.color_pair(C_GREEN))

    # Animated tree — offset right so WILLOW text has space
    tree_x = max(2, (w - tree_w) // 2)
    draw_willow(win, 1, tree_x)

    # Agent name — bottom right of hero block
    agent = "Heimdallr · Sonnet 4.6"
    safe_addstr(win, tree_h, w - len(agent) - 2, agent, curses.color_pair(C_DIM))
    draw_hline(win, tree_h + 1, curses.color_pair(C_DIM))

    # Activity log (chat body)
    log_top = tree_h + 2
    log_bot = h - 4  # leave room for prompt + stat strip
    log_h = log_bot - log_top
    with DATA.lock:
        lines = DATA.log[-(log_h):]
    for i, line in enumerate(lines):
        y = log_top + i
        if y >= log_bot:
            break
        if line.startswith("──"):
            safe_addstr(win, y, 2, line[:w-3], curses.color_pair(C_DIM) | curses.A_DIM)
        elif "error" in line.lower():
            safe_addstr(win, y, 2, line[:w-3], curses.color_pair(C_RED))
        else:
            safe_addstr(win, y, 2, line[:w-3], curses.color_pair(C_DIM))

    # Prompt row
    draw_hline(win, h - 3, curses.color_pair(C_DIM))
    safe_addstr(win, h - 2, 1, "▸", curses.color_pair(C_BLUE))
    safe_addstr(win, h - 2, 3, "ask heimdallr...", curses.color_pair(C_DIM) | curses.A_DIM)

    # Stat pill strip
    draw_hline(win, h - 2, curses.color_pair(C_DIM))
    with DATA.lock:
        kb = DATA.pg_knowledge
        edges = DATA.pg_edges
        ygg = DATA.ollama_ygg
        ts = DATA.ts
    pills = [
        f" 49 Tools ",
        f" {kb} KB ",
        f" {edges} Edges ",
        f" ygg:{ygg} ",
        f" {ts} ",
    ]
    x = 1
    for pill in pills:
        attr = curses.color_pair(C_PILL)
        safe_addstr(win, h - 1, x, pill, attr)
        x += len(pill) + 1
        if x >= w - 2:
            break

    win.noutrefresh()


# ── Right panel cards ────────────────────────────────────────────────────────

def _card_color(state):
    if state == "green":
        return curses.color_pair(C_GREEN)
    if state == "amber":
        return curses.color_pair(C_AMBER)
    if state == "red":
        return curses.color_pair(C_RED)
    return curses.color_pair(C_BLUE)


def draw_card(win, y, x, card_h, card_w, label, value, sub, state="blue"):
    if y + card_h > win.getmaxyx()[0] or x + card_w > win.getmaxyx()[1]:
        return
    try:
        sub_win = win.derwin(card_h, card_w, y, x)
        sub_win.erase()
        try:
            sub_win.border()
        except curses.error:
            pass
        safe_addstr(sub_win, 0, 2, f" {label} ", curses.color_pair(C_DIM))
        val_attr = _card_color(state) | curses.A_BOLD
        safe_addstr(sub_win, 1, 2, value[:card_w-3], val_attr)
        safe_addstr(sub_win, 2, 2, sub[:card_w-3], curses.color_pair(C_DIM))
        sub_win.noutrefresh()
    except curses.error:
        pass


def draw_right(win):
    h, w = win.getmaxyx()
    win.erase()

    # Header
    safe_addstr(win, 0, 1, "System Cards", curses.color_pair(C_HEADER) | curses.A_BOLD)
    add_label = "+ add"
    safe_addstr(win, 0, w - len(add_label) - 2, add_label, curses.color_pair(C_DIM))

    card_area_top = 1
    card_area_h = h - card_area_top
    rows = 5
    cols = 2
    card_h = max(4, card_area_h // rows)
    card_w = max(10, (w - 1) // cols)

    with DATA.lock:
        ygg_v = DATA.ollama_ygg
        ygg_run = DATA.ollama_running
        kart_p = DATA.kart_pending
        kart_r = DATA.kart_running
        kart_d = DATA.kart_done
        kb = DATA.pg_knowledge
        edges = DATA.pg_edges
        mf_pass = DATA.manifests_pass
        mf_total = DATA.manifests_total

    cards = [
        ("Yggdrasil",    ygg_v,    f"{'running' if ygg_run else 'down'}",    "green" if ygg_run else "red"),
        ("Kart Queue",   kart_p,   f"pending · {kart_d} done",               "amber" if kart_p not in ("0","—") else "green"),
        ("SAP Tools",    "49",     "all live · portless",                     "blue"),
        ("Knowledge",    kb,       f"atoms · {edges} edges",                  "blue"),
        ("Agents",       "6",      "heimdallr · kart +4",                     "blue"),
        ("/Skills",      "34",     "active · 8 archived",                     "blue"),
        ("Postgres",     "UP",     "unix socket · peer auth",                 "green"),
        ("SAFE Mfsts",   mf_pass,  f"signed / {mf_total} total",             "blue"),
        ("Fleet",        "3",      "groq · cerebras · sambanova",             "blue"),
        ("",             "+",      "add card",                                "dim"),
    ]

    for i, (label, value, sub, state) in enumerate(cards):
        row = i // cols
        col = i % cols
        y = card_area_top + row * card_h
        x = col * card_w
        if y + card_h <= h and x + card_w <= w:
            draw_card(win, y, x, card_h, card_w, label, value, sub, state)

    win.noutrefresh()


# ── Main ─────────────────────────────────────────────────────────────────────

def main(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(500)

    if curses.has_colors():
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(C_BLUE,   curses.COLOR_BLUE,    -1)
        curses.init_pair(C_GREEN,  curses.COLOR_GREEN,   -1)
        curses.init_pair(C_AMBER,  curses.COLOR_YELLOW,  -1)
        curses.init_pair(C_DIM,    curses.COLOR_WHITE,   -1)
        curses.init_pair(C_HEADER, curses.COLOR_WHITE,   -1)
        curses.init_pair(C_PILL,   curses.COLOR_CYAN,    -1)
        curses.init_pair(C_RED,    curses.COLOR_RED,     -1)
        brown = 130 if curses.COLORS >= 256 else curses.COLOR_YELLOW
        curses.init_pair(C_BROWN,  brown,                -1)

    stop_evt = threading.Event()
    t = threading.Thread(target=background_refresh, args=(stop_evt,), daemon=True)
    t.start()

    left_win = right_win = None

    def rebuild_windows():
        nonlocal left_win, right_win
        h, w = stdscr.getmaxyx()
        left_w = max(20, (w * 2) // 3)
        right_w = w - left_w
        left_win = curses.newwin(h, left_w, 0, 0)
        right_win = curses.newwin(h, right_w, 0, left_w)

    rebuild_windows()

    try:
        while True:
            key = stdscr.getch()
            if key == ord('q'):
                break
            if key == ord('r'):
                threading.Thread(target=refresh_all, daemon=True).start()
                DATA.push_log("manual refresh")
            if key == curses.KEY_RESIZE:
                stdscr.clear()
                rebuild_windows()

            h, w = stdscr.getmaxyx()
            if h < 10 or w < 40:
                stdscr.erase()
                safe_addstr(stdscr, 0, 0, "Terminal too small — resize to continue")
                stdscr.noutrefresh()
                curses.doupdate()
                time.sleep(0.5)
                continue

            draw_left(left_win)
            draw_right(right_win)
            curses.doupdate()

    finally:
        stop_evt.set()


if __name__ == "__main__":
    curses.wrapper(main)
