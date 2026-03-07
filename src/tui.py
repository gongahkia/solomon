import curses

COLORS = {"error": 1, "success": 2, "prompt": 3, "info": 4, "muted": 5, "accent": 6, "default": 7}

def init_colors():
    if curses.has_colors():
        curses.start_color()
        curses.init_pair(1, curses.COLOR_RED, curses.COLOR_BLACK)
        curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)
        curses.init_pair(3, curses.COLOR_YELLOW, curses.COLOR_BLACK)
        curses.init_pair(4, curses.COLOR_BLUE, curses.COLOR_BLACK)
        curses.init_pair(5, curses.COLOR_MAGENTA, curses.COLOR_BLACK)
        curses.init_pair(6, curses.COLOR_CYAN, curses.COLOR_BLACK)
        curses.init_pair(7, curses.COLOR_WHITE, curses.COLOR_BLACK)

def run_app(main_fn):
    def _wrapper(stdscr):
        init_colors()
        curses.curs_set(0)
        main_fn(stdscr)
    curses.wrapper(_wrapper)

def select_from_list(stdscr, title, items, footer="", y_offset=2, extra_bindings=None):
    """items: list of (main_text, detail_text, detail_color_pair) tuples.
    Returns int index on Enter, None on q/Esc, or (None, key_char) on unhandled keys."""
    cursor = 0
    while True:
        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()
        stdscr.addstr(0, 0, title[:max_x-1], curses.color_pair(COLORS["prompt"]))
        visible_height = max_y - y_offset - 2 # reserve 1 for footer
        if visible_height < 1:
            visible_height = 1
        scroll_offset = 0
        if cursor >= scroll_offset + visible_height:
            scroll_offset = cursor - visible_height + 1
        if cursor < scroll_offset:
            scroll_offset = cursor
        for i in range(scroll_offset, min(scroll_offset + visible_height, len(items))):
            row = y_offset + (i - scroll_offset)
            if row >= max_y - 1:
                break
            main_text, detail_text, detail_color = items[i]
            prefix = "> " if i == cursor else "  "
            attr = curses.A_REVERSE if i == cursor else 0
            line = f"{prefix}{main_text}"
            try:
                stdscr.addstr(row, 0, line[:max_x-1], attr)
                if detail_text:
                    detail_x = len(line) + 1
                    if detail_x < max_x - 1:
                        stdscr.addstr(row, detail_x, detail_text[:max_x-detail_x-1], curses.color_pair(detail_color) | attr)
            except curses.error:
                pass
        if footer:
            try:
                stdscr.addstr(max_y - 1, 0, footer[:max_x-1], curses.color_pair(COLORS["muted"]))
            except curses.error:
                pass
        stdscr.refresh()
        key = stdscr.getch()
        if key in (ord('j'), curses.KEY_DOWN):
            if cursor < len(items) - 1:
                cursor += 1
        elif key in (ord('k'), curses.KEY_UP):
            if cursor > 0:
                cursor -= 1
        elif key in (curses.KEY_ENTER, 10, 13):
            return cursor
        elif key in (ord('q'), 27): # q or Esc
            return None
        elif key == ord('?') and extra_bindings is not None:
            default_binds = [("j / Down", "Move down"), ("k / Up", "Move up"), ("Enter", "Select"), ("q / Esc", "Go back"), ("?", "Show help")]
            show_help(stdscr, default_binds + extra_bindings)
        else:
            try:
                return (None, chr(key))
            except (ValueError, OverflowError):
                pass

def show_help(stdscr, bindings):
    stdscr.erase()
    max_y, max_x = stdscr.getmaxyx()
    stdscr.addstr(0, 0, "Keybindings", curses.color_pair(COLORS["prompt"]))
    for i, (key, desc) in enumerate(bindings):
        row = i + 2
        if row >= max_y - 1:
            break
        try:
            stdscr.addstr(row, 0, f"  {key:<14} {desc}"[:max_x-1])
        except curses.error:
            pass
    try:
        stdscr.addstr(max_y - 1, 0, "Press any key to close"[:max_x-1], curses.color_pair(COLORS["muted"]))
    except curses.error:
        pass
    stdscr.refresh()
    stdscr.getch()
