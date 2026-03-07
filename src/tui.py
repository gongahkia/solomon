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
