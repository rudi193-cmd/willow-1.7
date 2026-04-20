#!/usr/bin/env python3
"""
Willow System Dashboard — terminal UI
apps/dashboard.py  b17: DASH2  ΔΣ=42

Run: python3 apps/dashboard.py
Keys: Tab=focus  ←→=page  ↑↓=navigate  Enter=expand  Esc=back  1-7=jump  /=search  r=refresh  q=quit
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

# ── Color pairs ──────────────────────────────────────────────────────────────
C_DEFAULT  = 0
C_BLUE     = 1
C_GREEN    = 2
C_AMBER    = 3
C_DIM      = 4
C_HEADER   = 5
C_PILL     = 6
C_RED      = 7
C_BROWN    = 8
C_SELECT   = 9   # selected card / focused item

# ── Pages ────────────────────────────────────────────────────────────────────
PAGE_OVERVIEW   = 0
PAGE_KART       = 1
PAGE_YGGDRASIL  = 2
PAGE_KNOWLEDGE  = 3
PAGE_SECRETS    = 4
PAGE_AGENTS     = 5
PAGE_LOGS       = 6
PAGE_NAMES = ["Overview", "Kart", "Yggdrasil", "Knowledge", "Secrets", "Agents", "Logs"]

REFRESH_INTERVAL = 30
SWAY_INTERVAL    = 2.0

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
_SWAY_SEQ  = [_POSE_L, _POSE_C, _POSE_R, _POSE_C,
              _POSE_L, _POSE_C, _POSE_R, _POSE_C, _POSE_L, _POSE_C]
_POSE_DIRS = ['L',     'C',     'R',     'C',
              'L',     'C',     'R',     'C',     'L',     'C']

class _AnimState:
    def __init__(self):
        self.lock = threading.Lock()
        self.idx  = 0
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
    def direction(self):
        with self.lock:
            return _POSE_DIRS[self.idx]

ANIM = _AnimState()

# ── Scene elements ────────────────────────────────────────────────────────────
# Flowers: (row_from_bottom, col_from_tree_right, char)
# row_from_bottom: 0=grass line, 1=one above, 2=two above
_FLOWERS = [
    (0,  4,  '✿'),
    (0,  9,  '❀'),
    (0, 15,  '✾'),
    (0, 21,  '✿'),
    (0, 28,  '❁'),
    (0, 34,  '❀'),
    (0, 40,  '✿'),
    (1,  6,  '❀'),
    (1, 13,  '✿'),
    (1, 25,  '✾'),
    (1, 37,  '✿'),
    (2, 10,  '✾'),
    (2, 30,  '❁'),
]

_GRASS = "ˎ,ˏ',ˎ,ˏˎ,',ˎˏ,ˎ,',ˏ,ˎ',ˏˎ,',ˎ,ˏ'"

# ── Nav state ────────────────────────────────────────────────────────────────
class NavState:
    def __init__(self):
        self.page      = PAGE_OVERVIEW
        self.focus     = None        # None | "left" | "right"
        self.card_idx  = 0
        self.expanded  = False
        self.scroll    = 0           # left panel log scroll
        self.search    = ""
        self.searching = False
    def tab(self):
        self.focus = {"right": None, "left": "right", None: "left"}[self.focus]
        self.expanded = False

NAV = NavState()

# ── System data ──────────────────────────────────────────────────────────────
class SystemData:
    def __init__(self):
        self.lock = threading.Lock()
        self.ts              = "—"
        self.pg_knowledge    = "—"
        self.pg_edges        = "—"
        self.pg_entities     = "—"
        self.kart_pending    = "—"
        self.kart_running    = "—"
        self.kart_done       = "—"
        self.kart_tasks      = []   # list of recent task dicts
        self.ollama_running  = False
        self.ollama_ygg      = "—"
        self.ollama_models   = []
        self.manifests_pass  = "—"
        self.manifests_total = "—"
        self.manifests_list  = []   # list of (app_id, signed)
        self.secret_names    = []   # credential names only
        self.log             = ["Willow dashboard starting..."]

    def push_log(self, msg):
        with self.lock:
            self.log.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
            if len(self.log) > 200:
                self.log = self.log[-200:]

DATA = SystemData()

# ── Fetch helpers ─────────────────────────────────────────────────────────────
def _fmt(n):
    if isinstance(n, int):
        if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
        if n >= 1_000:     return f"{n/1_000:.0f}K"
    return str(n)

def fetch_postgres():
    try:
        import psycopg2
        dsn = os.environ.get("WILLOW_DB_URL", "")
        if not dsn: return
        conn = psycopg2.connect(dsn)
        cur  = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM public.knowledge")
        k = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM public.knowledge_edges")
        e = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM public.entities")
        en = cur.fetchone()[0]
        try:
            cur.execute("SELECT status, COUNT(*) FROM kart.kart_task_queue GROUP BY status")
            kart = dict(cur.fetchall())
            cur.execute("""SELECT id, status, command, created_at
                           FROM kart.kart_task_queue
                           ORDER BY created_at DESC LIMIT 20""")
            tasks = [{"id": r[0], "status": r[1], "cmd": r[2][:40], "ts": str(r[3])[:16]}
                     for r in cur.fetchall()]
        except Exception:
            kart, tasks = {}, []
        conn.close()
        with DATA.lock:
            DATA.pg_knowledge = _fmt(k)
            DATA.pg_edges     = _fmt(e)
            DATA.pg_entities  = _fmt(en)
            DATA.kart_pending = str(kart.get("pending", kart.get("queued", 0)))
            DATA.kart_running = str(kart.get("running", 0))
            DATA.kart_done    = str(kart.get("complete", kart.get("completed", 0)))
            DATA.kart_tasks   = tasks
        DATA.push_log(f"pg: {_fmt(k)} atoms · {_fmt(e)} edges")
    except ImportError:
        DATA.push_log("psycopg2 not available")
    except Exception as ex:
        DATA.push_log(f"pg error: {ex}")

def fetch_ollama():
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3) as r:
            data = json.loads(r.read())
        models = [m["name"] for m in data.get("models", [])]
        ygg = sorted([m for m in models if "yggdrasil" in m.lower()], reverse=True)
        latest = ygg[0].split(":")[-1] if ygg else "none"
        with DATA.lock:
            DATA.ollama_running = True
            DATA.ollama_ygg     = latest
            DATA.ollama_models  = models
        DATA.push_log(f"ollama: {len(models)} models · yggdrasil {latest}")
    except Exception:
        with DATA.lock:
            DATA.ollama_running = False
            DATA.ollama_ygg     = "down"
        DATA.push_log("ollama: unreachable")

def fetch_manifests():
    try:
        safe_root = os.environ.get("WILLOW_SAFE_ROOT",
                    str(Path.home() / "SAFE_backup" / "Applications"))
        items, passed, total = [], 0, 0
        if os.path.isdir(safe_root):
            for app in sorted(os.listdir(safe_root)):
                mf  = Path(safe_root) / app / "manifest.json"
                sig = Path(safe_root) / app / "manifest.sig"
                if mf.exists():
                    total += 1
                    signed = sig.exists()
                    if signed: passed += 1
                    items.append((app, signed))
        with DATA.lock:
            DATA.manifests_pass  = str(passed)
            DATA.manifests_total = str(total)
            DATA.manifests_list  = items
        DATA.push_log(f"manifests: {passed}/{total} signed")
    except Exception as ex:
        DATA.push_log(f"manifest error: {ex}")

def fetch_secrets():
    try:
        vault_path = Path.home() / ".willow_creds.db"
        if not vault_path.exists():
            return
        import sqlite3
        conn = sqlite3.connect(str(vault_path))
        rows = conn.execute("SELECT name, env_key FROM credentials ORDER BY name").fetchall()
        conn.close()
        with DATA.lock:
            DATA.secret_names = [{"name": r[0], "env_key": r[1]} for r in rows]
        DATA.push_log(f"secrets: {len(rows)} credentials")
    except Exception as ex:
        DATA.push_log(f"secrets error: {ex}")

def refresh_all():
    with DATA.lock:
        DATA.ts = datetime.now().strftime("%H:%M:%S")
    DATA.push_log("── refreshing ──")
    fetch_postgres()
    fetch_ollama()
    fetch_manifests()
    fetch_secrets()

def background_refresh(stop_evt):
    while not stop_evt.is_set():
        refresh_all()
        stop_evt.wait(REFRESH_INTERVAL)

# ── Drawing helpers ───────────────────────────────────────────────────────────
def safe_addstr(win, y, x, text, attr=0):
    h, w = win.getmaxyx()
    if y < 0 or y >= h or x < 0 or x >= w: return
    max_len = w - x - 1
    if max_len <= 0: return
    try: win.addstr(y, x, text[:max_len], attr)
    except curses.error: pass

def draw_hline(win, y, attr=0):
    h, w = win.getmaxyx()
    if y < 0 or y >= h: return
    try: win.hline(y, 0, curses.ACS_HLINE, w - 1, attr)
    except curses.error: pass

def draw_panel_border(win, focused):
    attr = (curses.color_pair(C_AMBER) | curses.A_BOLD) if focused else \
           (curses.color_pair(C_DIM) | curses.A_DIM)
    try: win.border(
        curses.ACS_VLINE, curses.ACS_VLINE,
        curses.ACS_HLINE, curses.ACS_HLINE,
        curses.ACS_ULCORNER, curses.ACS_URCORNER,
        curses.ACS_LLCORNER, curses.ACS_LRCORNER,
    )
    except curses.error: pass
    # re-colour the border by drawing over with attr
    h, w = win.getmaxyx()
    try:
        win.attron(attr)
        win.hline(0,   0, curses.ACS_HLINE, w - 1)
        win.hline(h-1, 0, curses.ACS_HLINE, w - 1)
        for y in range(1, h - 1):
            win.addch(y, 0,     curses.ACS_VLINE)
            win.addch(y, w - 2, curses.ACS_VLINE)
        win.addch(0,   0,     curses.ACS_ULCORNER)
        win.addch(0,   w - 2, curses.ACS_URCORNER)
        win.addch(h-1, 0,     curses.ACS_LLCORNER)
        win.addch(h-1, w - 2, curses.ACS_LRCORNER)
        win.attroff(attr)
    except curses.error: pass

# ── Willow hero (shared left-panel top) ──────────────────────────────────────
_TREE_H = len(_POSE_C)
_TREE_W = max(len(l) for l in _POSE_C)

def draw_willow_hero(win):
    h, w = win.getmaxyx()
    ANIM.tick()
    frame   = ANIM.frame()
    wind    = ANIM.direction()
    w_off   = {'L': -2, 'C': 0, 'R': 2}[wind]   # flower drift

    # Title row
    safe_addstr(win, 0, 2, "W I L L O W", curses.color_pair(C_BLUE) | curses.A_BOLD)
    safe_addstr(win, 0, 14, "● LIVE", curses.color_pair(C_GREEN))
    # Sun top-right
    sun_x = w - 4
    if sun_x > 20:
        safe_addstr(win, 0, sun_x, "☀", curses.color_pair(C_AMBER) | curses.A_BOLD)

    # Tree — anchored left
    tree_x = 2
    for i, line in enumerate(frame):
        y = 1 + i
        if y >= h: break
        for j, ch in enumerate(line):
            x = tree_x + j
            if x >= w - 1: break
            if ch == '║':
                attr = curses.color_pair(C_BROWN) | curses.A_BOLD
            elif ch in ('/', '\\', 'V'):
                attr = curses.color_pair(C_GREEN)
            elif ch == 'ƒ':
                attr = curses.color_pair(C_GREEN) | curses.A_DIM
            else:
                continue
            try: win.addch(y, x, ch, attr)
            except curses.error: pass

    # Flowers — growing from the ground, drift with wind
    flower_x0 = tree_x + _TREE_W + 3
    grass_row  = _TREE_H + 1
    for (row_from_bot, col, fch) in _FLOWERS:
        y = grass_row - row_from_bot
        x = flower_x0 + col + w_off
        if 1 <= y < h and flower_x0 <= x < w - 2:
            try: win.addch(y, x, fch, curses.color_pair(C_GREEN))
            except curses.error: pass

    # Grass line — shifts 1 char with wind
    grass_row = _TREE_H + 1
    if grass_row < h:
        g_off = {'L': 1, 'C': 0, 'R': -1}[wind]
        for x in range(w - 1):
            gch = _GRASS[(x + g_off) % len(_GRASS)]
            try: win.addch(grass_row, x, gch, curses.color_pair(C_GREEN) | curses.A_DIM)
            except curses.error: pass

    # Agent name — sits on grass line, right-justified
    agent = "Heimdallr · Sonnet 4.6"
    safe_addstr(win, _TREE_H, w - len(agent) - 2, agent, curses.color_pair(C_DIM))

    draw_hline(win, _TREE_H + 2, curses.color_pair(C_DIM))
    return _TREE_H + 3

def draw_stat_strip(win):
    h, w = win.getmaxyx()
    draw_hline(win, h - 2, curses.color_pair(C_DIM))
    with DATA.lock:
        kb = DATA.pg_knowledge; edges = DATA.pg_edges; ygg = DATA.ollama_ygg; ts = DATA.ts
    pills = [f" 49 Tools ", f" {kb} KB ", f" {edges} Edges ", f" ygg:{ygg} ", f" {ts} "]
    x = 1
    for pill in pills:
        safe_addstr(win, h - 1, x, pill, curses.color_pair(C_PILL))
        x += len(pill) + 1
        if x >= w - 2: break

# ── Page tab bar ─────────────────────────────────────────────────────────────
def draw_page_bar(stdscr):
    h, w = stdscr.getmaxyx()
    y = h - 1
    x = 0
    for i, name in enumerate(PAGE_NAMES):
        label = f" {i+1}:{name} "
        if i == NAV.page:
            tab_col = C_AMBER if NAV.focus is not None else C_BLUE
            attr = curses.color_pair(tab_col) | curses.A_BOLD | curses.A_REVERSE
        else:
            attr = curses.color_pair(C_DIM)
        if x + len(label) < w:
            try: stdscr.addstr(y, x, label, attr)
            except curses.error: pass
            x += len(label) + 1
    hint = " Tab=focus ←→=page Enter=expand Esc=back q=quit "
    hx = w - len(hint) - 1
    if hx > x:
        try: stdscr.addstr(y, hx, hint, curses.color_pair(C_DIM))
        except curses.error: pass

# ── Overview page ─────────────────────────────────────────────────────────────
def draw_overview_left(win):
    h, w = win.getmaxyx()
    win.erase()
    content_y = draw_willow_hero(win)
    log_bot = h - 3
    with DATA.lock:
        log = DATA.log[:]
    visible = log_bot - content_y
    offset  = max(0, len(log) - visible - NAV.scroll) if NAV.focus == "left" else max(0, len(log) - visible)
    lines   = log[offset:offset + visible]
    for i, line in enumerate(lines):
        y = content_y + i
        if y >= log_bot: break
        if line.startswith("──"):
            safe_addstr(win, y, 2, line[:w-3], curses.color_pair(C_DIM) | curses.A_DIM)
        elif "error" in line.lower():
            safe_addstr(win, y, 2, line[:w-3], curses.color_pair(C_RED))
        else:
            safe_addstr(win, y, 2, line[:w-3], curses.color_pair(C_DIM))
    draw_hline(win, h - 3, curses.color_pair(C_DIM))
    safe_addstr(win, h - 2, 1, "▸", curses.color_pair(C_BLUE))
    safe_addstr(win, h - 2, 3, "ask heimdallr...", curses.color_pair(C_DIM) | curses.A_DIM)
    draw_stat_strip(win)
    draw_panel_border(win, NAV.focus == "left")
    win.noutrefresh()

def draw_overview_right(win):
    h, w = win.getmaxyx()
    win.erase()
    safe_addstr(win, 0, 1, "System Cards", curses.color_pair(C_HEADER) | curses.A_BOLD)
    add_lbl = "+ add"
    safe_addstr(win, 0, w - len(add_lbl) - 2, add_lbl, curses.color_pair(C_DIM))
    rows, cols = 5, 2
    card_h = max(4, (h - 1) // rows)
    card_w = max(10, (w - 1) // cols)
    with DATA.lock:
        ygg_v  = DATA.ollama_ygg; ygg_run = DATA.ollama_running
        kp     = DATA.kart_pending; kd = DATA.kart_done
        kb     = DATA.pg_knowledge; edges = DATA.pg_edges
        mfp    = DATA.manifests_pass; mft = DATA.manifests_total
    cards = [
        ("Yggdrasil",  ygg_v,  f"{'running' if ygg_run else 'down'}",        "green" if ygg_run else "red"),
        ("Kart Queue", kp,     f"pending · {kd} done",                        "amber" if kp not in ("0","—") else "green"),
        ("SAP Tools",  "49",   "all live · portless",                         "blue"),
        ("Knowledge",  kb,     f"atoms · {edges} edges",                      "blue"),
        ("Agents",     "6",    "heimdallr · kart +4",                         "blue"),
        ("/Skills",    "34",   "active · 8 archived",                         "blue"),
        ("Postgres",   "UP",   "unix socket · peer auth",                     "green"),
        ("SAFE Mfsts", mfp,    f"signed / {mft} total",                       "blue"),
        ("Fleet",      "3",    "groq · cerebras · sambanova",                 "blue"),
        ("",           "+",    "add card",                                    "dim"),
    ]
    focused = NAV.focus == "right"
    for i, (label, value, sub, state) in enumerate(cards):
        row, col = i // cols, i % cols
        y = 1 + row * card_h
        x = col * card_w
        if y + card_h > h or x + card_w > w: continue
        selected = focused and i == NAV.card_idx
        _draw_card(win, y, x, card_h, card_w, label, value, sub, state, selected)
    draw_panel_border(win, focused)
    win.noutrefresh()

def _draw_card(win, y, x, card_h, card_w, label, value, sub, state, selected=False):
    try:
        sub_win = win.derwin(card_h, card_w, y, x)
        sub_win.erase()
        try: sub_win.border()
        except curses.error: pass
        if selected:
            val_attr = curses.color_pair(C_SELECT) | curses.A_BOLD | curses.A_REVERSE
            lbl_attr = curses.color_pair(C_SELECT)
        else:
            lbl_attr = curses.color_pair(C_DIM)
            if state == "green":   val_attr = curses.color_pair(C_GREEN) | curses.A_BOLD
            elif state == "amber": val_attr = curses.color_pair(C_AMBER) | curses.A_BOLD
            elif state == "red":   val_attr = curses.color_pair(C_RED)   | curses.A_BOLD
            else:                  val_attr = curses.color_pair(C_BLUE)  | curses.A_BOLD
        safe_addstr(sub_win, 0, 2, f" {label} ", lbl_attr)
        safe_addstr(sub_win, 1, 2, value[:card_w-3], val_attr)
        safe_addstr(sub_win, 2, 2, sub[:card_w-3], curses.color_pair(C_DIM))
        sub_win.noutrefresh()
    except curses.error: pass

# ── Kart page ─────────────────────────────────────────────────────────────────
def draw_kart_left(win):
    h, w = win.getmaxyx()
    win.erase()
    content_y = draw_willow_hero(win)
    safe_addstr(win, content_y, 2, "Kart Task Queue", curses.color_pair(C_HEADER) | curses.A_BOLD)
    with DATA.lock:
        kp = DATA.kart_pending; kr = DATA.kart_running; kd = DATA.kart_done
    safe_addstr(win, content_y + 1, 2,
        f"pending:{kp}  running:{kr}  done:{kd}",
        curses.color_pair(C_DIM))
    draw_stat_strip(win)
    draw_panel_border(win, NAV.focus == "left")
    win.noutrefresh()

def draw_kart_right(win):
    h, w = win.getmaxyx()
    win.erase()
    safe_addstr(win, 0, 1, "Recent Tasks", curses.color_pair(C_HEADER) | curses.A_BOLD)
    with DATA.lock:
        tasks = DATA.kart_tasks[:]
    focused = NAV.focus == "right"
    if not tasks:
        safe_addstr(win, 2, 2, "No tasks loaded — pg not connected", curses.color_pair(C_DIM))
    else:
        for i, t in enumerate(tasks[:h-3]):
            y = 1 + i
            selected = focused and i == NAV.card_idx
            status_col = C_GREEN if t["status"] in ("complete","completed") else \
                         C_AMBER if t["status"] == "running" else C_DIM
            attr = curses.color_pair(C_SELECT) | curses.A_REVERSE if selected else curses.color_pair(C_DIM)
            s_attr = curses.color_pair(C_SELECT) | curses.A_REVERSE if selected else curses.color_pair(status_col)
            label = f" {t['status'][:8]:<8} {t['cmd'][:w-14]} "
            safe_addstr(win, y, 1, label, attr)
    if NAV.expanded and tasks:
        t = tasks[min(NAV.card_idx, len(tasks)-1)]
        _draw_expanded_kart(win, t)
    win.noutrefresh()

def _draw_expanded_kart(win, t):
    h, w = win.getmaxyx()
    ew = min(w - 4, 60); eh = 8
    ey = max(1, (h - eh) // 2); ex = max(1, (w - ew) // 2)
    try:
        pop = win.derwin(eh, ew, ey, ex)
        pop.erase()
        pop.border()
        safe_addstr(pop, 0, 2, " Task Detail ", curses.color_pair(C_BLUE) | curses.A_BOLD)
        safe_addstr(pop, 1, 2, f"ID:     {t['id']}", curses.color_pair(C_DIM))
        safe_addstr(pop, 2, 2, f"Status: {t['status']}", curses.color_pair(C_GREEN))
        safe_addstr(pop, 3, 2, f"Cmd:    {t['cmd']}", curses.color_pair(C_DIM))
        safe_addstr(pop, 4, 2, f"Time:   {t['ts']}", curses.color_pair(C_DIM))
        safe_addstr(pop, eh-1, 2, " Esc=close ", curses.color_pair(C_DIM))
        pop.noutrefresh()
    except curses.error: pass

# ── Yggdrasil page ────────────────────────────────────────────────────────────
def draw_yggdrasil_left(win):
    h, w = win.getmaxyx()
    win.erase()
    content_y = draw_willow_hero(win)
    safe_addstr(win, content_y, 2, "Yggdrasil — Local SLM", curses.color_pair(C_HEADER) | curses.A_BOLD)
    with DATA.lock:
        ygg = DATA.ollama_ygg; running = DATA.ollama_running
    status = "● LIVE" if running else "○ DOWN"
    scol = C_GREEN if running else C_RED
    safe_addstr(win, content_y + 1, 2, f"Active: yggdrasil:{ygg}  ", curses.color_pair(C_DIM))
    safe_addstr(win, content_y + 2, 2, status, curses.color_pair(scol))
    draw_stat_strip(win)
    draw_panel_border(win, NAV.focus == "left")
    win.noutrefresh()

def draw_yggdrasil_right(win):
    h, w = win.getmaxyx()
    win.erase()
    safe_addstr(win, 0, 1, "Models", curses.color_pair(C_HEADER) | curses.A_BOLD)
    with DATA.lock:
        models = DATA.ollama_models[:]
    focused = NAV.focus == "right"
    ygg_models = [m for m in models if "yggdrasil" in m.lower()]
    other = [m for m in models if "yggdrasil" not in m.lower()]
    items = ygg_models + ["──────────"] + other
    for i, name in enumerate(items[:h-3]):
        y = 1 + i
        if name.startswith("──"):
            safe_addstr(win, y, 2, name[:w-3], curses.color_pair(C_DIM) | curses.A_DIM)
            continue
        selected = focused and i == NAV.card_idx
        attr = curses.color_pair(C_SELECT) | curses.A_REVERSE if selected else \
               curses.color_pair(C_GREEN) if "yggdrasil" in name else curses.color_pair(C_DIM)
        safe_addstr(win, y, 2, f" {name[:w-4]} ", attr)
    draw_panel_border(win, NAV.focus == "right")
    win.noutrefresh()

# ── Knowledge page ────────────────────────────────────────────────────────────
def draw_knowledge_left(win):
    h, w = win.getmaxyx()
    win.erase()
    content_y = draw_willow_hero(win)
    with DATA.lock:
        kb = DATA.pg_knowledge; edges = DATA.pg_edges
    safe_addstr(win, content_y,     2, "Knowledge Graph", curses.color_pair(C_HEADER) | curses.A_BOLD)
    safe_addstr(win, content_y + 1, 2, f"{kb} atoms", curses.color_pair(C_BLUE) | curses.A_BOLD)
    safe_addstr(win, content_y + 2, 2, f"{edges} edges", curses.color_pair(C_DIM))
    safe_addstr(win, content_y + 4, 2, "Press / to search", curses.color_pair(C_DIM) | curses.A_DIM)
    draw_stat_strip(win)
    draw_panel_border(win, NAV.focus == "left")
    win.noutrefresh()

def draw_knowledge_right(win):
    h, w = win.getmaxyx()
    win.erase()
    query = NAV.search
    if NAV.searching:
        safe_addstr(win, 0, 1, f"Search: {query}_", curses.color_pair(C_BLUE) | curses.A_BOLD)
    else:
        safe_addstr(win, 0, 1, f"Search: {query or '(press / to search)'}", curses.color_pair(C_HEADER) | curses.A_BOLD)
    safe_addstr(win, 2, 2, "KB search not yet wired to MCP.", curses.color_pair(C_DIM))
    safe_addstr(win, 3, 2, "Will call willow_knowledge_search on enter.", curses.color_pair(C_DIM) | curses.A_DIM)
    draw_panel_border(win, NAV.focus == "right")
    win.noutrefresh()

# ── Secrets page ──────────────────────────────────────────────────────────────
def draw_secrets_left(win):
    h, w = win.getmaxyx()
    win.erase()
    content_y = draw_willow_hero(win)
    with DATA.lock:
        n = len(DATA.secret_names)
    safe_addstr(win, content_y,     2, "Credential Vault", curses.color_pair(C_HEADER) | curses.A_BOLD)
    safe_addstr(win, content_y + 1, 2, f"{n} credentials stored", curses.color_pair(C_DIM))
    safe_addstr(win, content_y + 2, 2, "Fernet-encrypted SQLite", curses.color_pair(C_DIM) | curses.A_DIM)
    safe_addstr(win, content_y + 4, 2, "↑↓=navigate  Enter=reveal", curses.color_pair(C_DIM) | curses.A_DIM)
    draw_stat_strip(win)
    draw_panel_border(win, NAV.focus == "left")
    win.noutrefresh()

def draw_secrets_right(win):
    h, w = win.getmaxyx()
    win.erase()
    safe_addstr(win, 0, 1, "Credentials  (names only)", curses.color_pair(C_HEADER) | curses.A_BOLD)
    with DATA.lock:
        secrets = DATA.secret_names[:]
    focused = NAV.focus == "right"
    if not secrets:
        safe_addstr(win, 2, 2, "Vault empty or not found.", curses.color_pair(C_DIM))
    for i, s in enumerate(secrets[:h-3]):
        y = 1 + i
        selected = focused and i == NAV.card_idx
        attr = curses.color_pair(C_SELECT) | curses.A_REVERSE if selected else curses.color_pair(C_DIM)
        env = f" → {s['env_key']}" if s['env_key'] else ""
        safe_addstr(win, y, 2, f" {s['name']}{env} "[:w-3], attr)
    if NAV.expanded and secrets:
        s = secrets[min(NAV.card_idx, len(secrets)-1)]
        _draw_secret_confirm(win, s)
    draw_panel_border(win, NAV.focus == "right")
    win.noutrefresh()

def _draw_secret_confirm(win, s):
    h, w = win.getmaxyx()
    ew = min(w - 4, 50); eh = 6
    ey = max(1, (h - eh) // 2); ex = max(1, (w - ew) // 2)
    try:
        pop = win.derwin(eh, ew, ey, ex)
        pop.erase(); pop.border()
        safe_addstr(pop, 0, 2, " Credential ", curses.color_pair(C_AMBER) | curses.A_BOLD)
        safe_addstr(pop, 1, 2, f"Name:    {s['name']}", curses.color_pair(C_DIM))
        safe_addstr(pop, 2, 2, f"Env key: {s['env_key'] or '—'}", curses.color_pair(C_DIM))
        safe_addstr(pop, 3, 2, "Value:   [protected]", curses.color_pair(C_AMBER))
        safe_addstr(pop, eh-1, 2, " Esc=close ", curses.color_pair(C_DIM))
        pop.noutrefresh()
    except curses.error: pass

# ── Agents page ───────────────────────────────────────────────────────────────
def draw_agents_left(win):
    h, w = win.getmaxyx()
    win.erase()
    content_y = draw_willow_hero(win)
    with DATA.lock:
        mfp = DATA.manifests_pass; mft = DATA.manifests_total
    safe_addstr(win, content_y,     2, "Agents & SAFE", curses.color_pair(C_HEADER) | curses.A_BOLD)
    safe_addstr(win, content_y + 1, 2, f"Manifests: {mfp}/{mft} signed", curses.color_pair(C_DIM))
    safe_addstr(win, content_y + 2, 2, "PGP v2 · portless", curses.color_pair(C_DIM) | curses.A_DIM)
    draw_stat_strip(win)
    draw_panel_border(win, NAV.focus == "left")
    win.noutrefresh()

def draw_agents_right(win):
    h, w = win.getmaxyx()
    win.erase()
    safe_addstr(win, 0, 1, "SAFE Manifests", curses.color_pair(C_HEADER) | curses.A_BOLD)
    with DATA.lock:
        items = DATA.manifests_list[:]
    focused = NAV.focus == "right"
    for i, (app_id, signed) in enumerate(items[:h-3]):
        y = 1 + i
        selected = focused and i == NAV.card_idx
        sig_str = "✓" if signed else "✗"
        sig_col = C_GREEN if signed else C_RED
        base_attr = curses.color_pair(C_SELECT) | curses.A_REVERSE if selected else curses.color_pair(C_DIM)
        safe_addstr(win, y, 2, f" {sig_str} {app_id[:w-7]} ", base_attr)
    draw_panel_border(win, NAV.focus == "right")
    win.noutrefresh()

# ── Logs page ─────────────────────────────────────────────────────────────────
def draw_logs_full(left_win, right_win):
    h, w_l = left_win.getmaxyx()
    _, w_r  = right_win.getmaxyx()
    left_win.erase(); right_win.erase()
    safe_addstr(left_win, 0, 1, "Activity Log", curses.color_pair(C_HEADER) | curses.A_BOLD)
    safe_addstr(left_win, 0, w_l - 20, "↑↓=scroll  Esc=back", curses.color_pair(C_DIM))
    with DATA.lock:
        log = DATA.log[:]
    total = len(log)
    visible = h - 2
    offset = max(0, min(NAV.scroll, total - visible))
    lines = log[offset:offset + visible]
    for i, line in enumerate(lines):
        y = 1 + i
        if line.startswith("──"):
            attr = curses.color_pair(C_DIM) | curses.A_DIM
        elif "error" in line.lower():
            attr = curses.color_pair(C_RED)
        else:
            attr = curses.color_pair(C_DIM)
        safe_addstr(left_win, y, 1, line[:w_l-2], attr)
    scrollbar = f" {offset+1}-{min(offset+visible, total)}/{total} "
    safe_addstr(left_win, h-1, w_l - len(scrollbar) - 1, scrollbar, curses.color_pair(C_PILL))
    left_win.noutrefresh()
    right_win.noutrefresh()

# ── Main ──────────────────────────────────────────────────────────────────────
PAGE_DRAWS = {
    PAGE_OVERVIEW:  (draw_overview_left,   draw_overview_right),
    PAGE_KART:      (draw_kart_left,       draw_kart_right),
    PAGE_YGGDRASIL: (draw_yggdrasil_left,  draw_yggdrasil_right),
    PAGE_KNOWLEDGE: (draw_knowledge_left,  draw_knowledge_right),
    PAGE_SECRETS:   (draw_secrets_left,    draw_secrets_right),
    PAGE_AGENTS:    (draw_agents_left,     draw_agents_right),
}

def main(stdscr):
    curses.curs_set(0)
    stdscr.keypad(True)
    stdscr.nodelay(True)
    stdscr.timeout(200)

    if curses.has_colors():
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(C_BLUE,   curses.COLOR_BLUE,   -1)
        curses.init_pair(C_GREEN,  curses.COLOR_GREEN,  -1)
        curses.init_pair(C_AMBER,  curses.COLOR_YELLOW, -1)
        curses.init_pair(C_DIM,    curses.COLOR_WHITE,  -1)
        curses.init_pair(C_HEADER, curses.COLOR_WHITE,  -1)
        curses.init_pair(C_PILL,   curses.COLOR_CYAN,   -1)
        curses.init_pair(C_RED,    curses.COLOR_RED,    -1)
        brown = 130 if curses.COLORS >= 256 else curses.COLOR_YELLOW
        curses.init_pair(C_BROWN,  brown,               -1)
        curses.init_pair(C_SELECT, curses.COLOR_CYAN,   -1)

    stop_evt = threading.Event()
    t = threading.Thread(target=background_refresh, args=(stop_evt,), daemon=True)
    t.start()

    left_win = right_win = None

    def rebuild():
        nonlocal left_win, right_win
        h, w = stdscr.getmaxyx()
        left_w  = max(20, (w * 2) // 3)
        right_w = w - left_w
        left_win  = curses.newwin(h - 1, left_w,  0, 0)
        right_win = curses.newwin(h - 1, right_w, 0, left_w)

    rebuild()

    try:
        while True:
            key = stdscr.getch()

            # ── Search mode ──
            if NAV.searching:
                if key == 27:                        # Esc
                    NAV.searching = False
                elif key in (curses.KEY_ENTER, 10, 13):
                    NAV.searching = False
                elif key in (curses.KEY_BACKSPACE, 127):
                    NAV.search = NAV.search[:-1]
                elif 32 <= key <= 126:
                    NAV.search += chr(key)
            else:
                # ── Global keys ──
                if key == ord('q'):
                    break
                elif key == ord('r'):
                    threading.Thread(target=refresh_all, daemon=True).start()
                    DATA.push_log("manual refresh")
                elif key == ord('/'):
                    NAV.searching = True; NAV.search = ""
                elif key == 9:                        # Tab — cycle focus
                    NAV.tab()
                elif key == 27:                       # Esc
                    if NAV.expanded: NAV.expanded = False
                    else: NAV.focus = None
                elif key in (curses.KEY_ENTER, 10, 13):
                    NAV.expanded = not NAV.expanded
                elif key == curses.KEY_RESIZE:
                    stdscr.clear(); rebuild()

                # ── Direct page jump (always works) ──
                elif ord('1') <= key <= ord('7'):
                    NAV.page = key - ord('1')
                    NAV.card_idx = 0; NAV.expanded = False; NAV.scroll = 0

                # ── Panel-aware arrow keys ──
                elif key == curses.KEY_UP:
                    if NAV.focus == "left" or NAV.page == PAGE_LOGS:
                        NAV.scroll = max(0, NAV.scroll - 1)
                    elif NAV.focus == "right":
                        NAV.card_idx = max(0, NAV.card_idx - 2)  # move up a row

                elif key == curses.KEY_DOWN:
                    if NAV.focus == "left" or NAV.page == PAGE_LOGS:
                        with DATA.lock: total = len(DATA.log)
                        NAV.scroll = min(max(0, total - 1), NAV.scroll + 1)
                    elif NAV.focus == "right":
                        NAV.card_idx += 2  # move down a row

                elif key == curses.KEY_LEFT:
                    if NAV.focus == "right":
                        if NAV.card_idx % 2 == 1:
                            NAV.card_idx -= 1  # move to left column
                    elif NAV.focus is None:
                        NAV.page = (NAV.page - 1) % len(PAGE_NAMES)
                        NAV.card_idx = 0; NAV.expanded = False; NAV.scroll = 0

                elif key == curses.KEY_RIGHT:
                    if NAV.focus == "right":
                        if NAV.card_idx % 2 == 0:
                            NAV.card_idx += 1  # move to right column
                    elif NAV.focus is None:
                        NAV.page = (NAV.page + 1) % len(PAGE_NAMES)
                        NAV.card_idx = 0; NAV.expanded = False; NAV.scroll = 0

            # ── Draw ──
            h, w = stdscr.getmaxyx()
            if h < 12 or w < 40:
                stdscr.erase()
                try: stdscr.addstr(0, 0, "Terminal too small")
                except curses.error: pass
                stdscr.noutrefresh(); curses.doupdate()
                continue

            stdscr.erase()
            draw_page_bar(stdscr)
            stdscr.noutrefresh()

            if NAV.page == PAGE_LOGS:
                draw_logs_full(left_win, right_win)
            else:
                draw_l, draw_r = PAGE_DRAWS[NAV.page]
                draw_l(left_win)
                draw_r(right_win)

            curses.doupdate()

    finally:
        stop_evt.set()

if __name__ == "__main__":
    curses.wrapper(main)
