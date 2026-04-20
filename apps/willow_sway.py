#!/usr/bin/env python3
"""
Willow sway animation — standalone test
apps/willow_sway.py  b17: SWAY1  ΔΣ=42

Run: python3 apps/willow_sway.py
Keys: q=quit
"""
import curses
import time

# ── Three key poses ──────────────────────────────────────────────────────────
# All 8 lines × 22 chars. Spaces pad to width.

POSE_L = [
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

POSE_C = [
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

POSE_R = [
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

# 10-frame sway sequence: L → C → R → C → L → C → R → C → L → C
FRAMES = [POSE_L, POSE_C, POSE_R, POSE_C, POSE_L, POSE_C, POSE_R, POSE_C, POSE_L, POSE_C]
FRAME_DELAY = 2.0  # seconds per frame


def main(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(50)

    if curses.has_colors():
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_GREEN, -1)
        curses.init_pair(2, curses.COLOR_WHITE, -1)

    frame_idx = 0
    last_frame_time = time.time()

    while True:
        key = stdscr.getch()
        if key == ord('q'):
            break

        now = time.time()
        if now - last_frame_time >= FRAME_DELAY:
            frame_idx = (frame_idx + 1) % len(FRAMES)
            last_frame_time = now

        stdscr.erase()
        h, w = stdscr.getmaxyx()

        frame = FRAMES[frame_idx]
        tree_h = len(frame)
        tree_w = max(len(l) for l in frame)

        start_y = max(0, (h - tree_h) // 2)
        start_x = max(0, (w - tree_w) // 2)

        for i, line in enumerate(frame):
            y = start_y + i
            if y >= h:
                break
            for j, ch in enumerate(line):
                x = start_x + j
                if x >= w - 1:
                    break
                if ch == '║' or ch == '|':
                    attr = curses.color_pair(2) | curses.A_BOLD
                elif ch in ('/', '\\'):
                    attr = curses.color_pair(1)
                elif ch == 'ƒ':
                    attr = curses.color_pair(1) | curses.A_DIM
                else:
                    attr = curses.color_pair(2) | curses.A_DIM
                try:
                    stdscr.addch(y, x, ch, attr)
                except curses.error:
                    pass

        # Label
        label = "[ q to quit ]"
        try:
            stdscr.addstr(h - 1, max(0, (w - len(label)) // 2), label,
                          curses.color_pair(2) | curses.A_DIM)
        except curses.error:
            pass

        stdscr.noutrefresh()
        curses.doupdate()


if __name__ == "__main__":
    curses.wrapper(main)
