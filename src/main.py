# mypy: ignore-errors
# silence mypy type errors

import curses
import json
import os
from datetime import date, datetime, timedelta
from tui import run_app

def check_sko(filename:str) -> bool:
    required_keys = ["card_name", "card_info", "card_add_info", "card_date"]
    try:
        file_path:str = os.path.expanduser(f"~/.config/senko/{filename}")
        with open(file_path, "r") as fhand:
            sko_contents = json.load(fhand)
        for set_cards in sko_contents.values():
            for card in set_cards:
                if not all(k in card for k in required_keys):
                    return False
        return True
    except (json.JSONDecodeError, IOError, KeyError):
        return False

def select_sko_file(stdscr) -> str | None:
    from tui import select_from_list, text_input, COLORS
    from srs import cards_due_count
    config_dir = os.path.expanduser("~/.config/senko")
    while True:
        valid_array = [f for f in os.listdir(config_dir) if f.endswith(".sko") and check_sko(f)]
        # compute aggregate stats
        total_files = len(valid_array)
        total_cards = 0
        total_due = 0
        items = []
        for fname in valid_array:
            data = read_sko(fname)
            n_sets = len(data)
            n_cards = sum(len(cards) for cards in data.values())
            n_due = sum(cards_due_count(cards) for cards in data.values())
            total_cards += n_cards
            total_due += n_due
            color = COLORS["error"] if n_due > 0 else COLORS["success"]
            items.append((f"{fname} | {n_sets} sets | {n_cards} cards", f"{n_due} due", color))
        header = f"Senko | {total_files} files | {total_cards} cards | {total_due} due today"
        footer = "[Enter] Open  [n] New file  [d] Delete file  [q] Back"
        if not items:
            items = [("No files found.", "Create one with [n]", COLORS["muted"])]
        choice = select_from_list(stdscr, header, items, footer=footer, extra_bindings=[("n", "New file"), ("d", "Delete file")])
        if choice is None:
            return None
        elif isinstance(choice, tuple):
            idx, key = choice
            if key == "n":
                stdscr.erase()
                name = text_input(stdscr, "Filename: ", y=0, x=0)
                if name:
                    if not name.endswith(".sko"):
                        name += ".sko"
                    fpath = os.path.join(config_dir, name)
                    with open(fpath, "w") as f:
                        json.dump({}, f)
                continue
            elif key == "d" and valid_array and idx is not None and idx < len(valid_array):
                fname = valid_array[idx]
                stdscr.erase()
                stdscr.addstr(0, 0, f"Delete {fname}? [y/n]", curses.color_pair(COLORS["error"]))
                stdscr.refresh()
                if chr(stdscr.getch()) == "y":
                    os.remove(os.path.join(config_dir, fname))
                continue
            else:
                continue
        else:
            if not valid_array:
                continue
            return valid_array[choice]

def read_sko(filename:str) -> {}:
    file_path:str = os.path.expanduser(f"~/.config/senko/{filename}")
    with open(file_path, "r") as fhand:
        return json.load(fhand)

def select_flashcard_set(stdscr, file_contents:{}, filename:str=None) -> (str,[]):
    from tui import select_from_list, text_input, COLORS
    from srs import cards_due_count
    while True:
        name_array = list(file_contents.keys())
        items = []
        for set_name in name_array:
            cards = file_contents[set_name]
            n_cards = len(cards)
            if n_cards == 0:
                items.append((f"{set_name} | {n_cards} cards", "Empty", COLORS["muted"]))
            else:
                n_due = cards_due_count(cards)
                color = COLORS["error"] if n_due > 0 else COLORS["success"]
                items.append((f"{set_name} | {n_cards} cards", f"{n_due} due", color))
        if not items:
            items = [("No sets found.", "Create one with [n]", COLORS["muted"])]
        footer = "[Enter] Open  [n] New set  [r] Rename  [d] Delete  [q] Back"
        choice = select_from_list(stdscr, "Select flashcard set", items, footer=footer, extra_bindings=[("n", "New set"), ("r", "Rename set"), ("d", "Delete set")])
        if choice is None:
            return None
        elif isinstance(choice, tuple):
            idx, key = choice
            if key == "n":
                stdscr.erase()
                name = text_input(stdscr, "Set name: ", y=0, x=0)
                if name and name not in file_contents:
                    file_contents[name] = []
                    if filename:
                        write_sko(filename, file_contents)
                continue
            elif key == "r" and name_array and idx is not None and idx < len(name_array):
                old_name = name_array[idx]
                stdscr.erase()
                new_name = text_input(stdscr, "New name: ", initial=old_name, y=0, x=0)
                if new_name and new_name != old_name:
                    file_contents[new_name] = file_contents.pop(old_name)
                    if filename:
                        write_sko(filename, file_contents)
                continue
            elif key == "d" and name_array and idx is not None and idx < len(name_array):
                set_name = name_array[idx]
                stdscr.erase()
                stdscr.addstr(0, 0, f"Delete '{set_name}'? [y/n]", curses.color_pair(COLORS["error"]))
                stdscr.refresh()
                if chr(stdscr.getch()) == "y":
                    del file_contents[set_name]
                    if filename:
                        write_sko(filename, file_contents)
                continue
            else:
                continue
        else:
            if not name_array:
                continue
            selected = name_array[choice]
            return (selected, file_contents[selected])

def render_sko_loop(stdscr, sko_setname:str, sko_setcontents:[], config:dict=None) -> ():
    import time as _time
    from srs import cards_due, sm2_review
    from tui import COLORS
    if len(sko_setcontents) == 0:
        while True:
            stdscr.erase()
            stdscr.addstr(0, 0, f"{sko_setname} is currently empty. Go make some new cards!", curses.color_pair(COLORS["muted"]))
            stdscr.addstr(2, 0, "[Q]uit", curses.color_pair(COLORS["prompt"]))
            if chr(stdscr.getch()) == "q":
                return (sko_setname, sko_setcontents)
    due_cards = cards_due(sko_setcontents)
    if not due_cards:
        # find earliest future date
        future_dates = []
        for c in sko_setcontents:
            try:
                future_dates.append(datetime.strptime(c["card_date"], "%d/%m/%Y").date())
            except (ValueError, KeyError):
                pass
        next_date = min(future_dates).strftime("%d/%m/%Y") if future_dates else "N/A"
        while True:
            stdscr.erase()
            stdscr.addstr(0, 0, f"All caught up! {len(sko_setcontents)} cards in deck. Next review: {next_date}", curses.color_pair(COLORS["success"]))
            stdscr.addstr(2, 0, "[Q]uit", curses.color_pair(COLORS["prompt"]))
            if chr(stdscr.getch()) == "q":
                return (sko_setname, sko_setcontents)
    start_time = _time.time()
    reviewed = 0
    total_due = len(due_cards)
    for card in due_cards:
        reviewed += 1
        max_y, max_x = stdscr.getmaxyx()
        # front screen
        quit_session = False
        while True:
            stdscr.erase()
            stdscr.addstr(0, 0, sko_setname, curses.color_pair(COLORS["accent"]))
            progress = f"({reviewed}/{total_due})"
            try:
                stdscr.addstr(0, max_x - len(progress) - 1, progress)
            except curses.error:
                pass
            center_y = max_y // 2
            name = card.get("card_name", "")
            try:
                stdscr.addstr(center_y, max(0, (max_x - len(name)) // 2), name, curses.A_BOLD)
            except curses.error:
                pass
            try:
                stdscr.addstr(max_y - 1, 0, "[Space] Show answer  [q] Quit session"[:max_x-1], curses.color_pair(COLORS["muted"]))
            except curses.error:
                pass
            stdscr.refresh()
            key = stdscr.getch()
            if key == ord(" "):
                break
            elif key == ord("q"):
                quit_session = True
                break
        if quit_session:
            break
        # back screen
        while True:
            stdscr.erase()
            stdscr.addstr(0, 0, card.get("card_name", ""), curses.A_BOLD)
            progress = f"({reviewed}/{total_due})"
            try:
                stdscr.addstr(0, max_x - len(progress) - 1, progress)
            except curses.error:
                pass
            info = card.get("card_info", "")
            if info:
                stdscr.addstr(2, 0, info[:max_x-1])
            add_info = card.get("card_add_info", "")
            if add_info:
                try:
                    stdscr.addstr(3, 0, add_info[:max_x-1], curses.color_pair(COLORS["muted"]))
                except curses.error:
                    pass
            try:
                stdscr.addstr(5, 0, "[1] Again  [2] Hard  [3] Good  [4] Easy"[:max_x-1], curses.color_pair(COLORS["prompt"]))
            except curses.error:
                pass
            stdscr.refresh()
            key = stdscr.getch()
            if key in (ord("1"), ord("2"), ord("3"), ord("4")):
                grade = int(chr(key)) - 1
                sm2_review(card, grade, config)
                break
    # session summary
    elapsed = _time.time() - start_time
    while True:
        stdscr.erase()
        stdscr.addstr(0, 0, f"{reviewed} cards reviewed in {elapsed/60:.1f} min", curses.color_pair(COLORS["success"]))
        stdscr.addstr(2, 0, "[Q]uit", curses.color_pair(COLORS["prompt"]))
        stdscr.refresh()
        if chr(stdscr.getch()) == "q":
            return (sko_setname, sko_setcontents)

def add_days(given_date:str, days_add:int) -> str:
    dt = datetime.strptime(given_date, "%d/%m/%Y")
    return (dt + timedelta(days=days_add)).strftime("%d/%m/%Y")

def check_overdue(given_date:str) -> bool:
    return date.today() > datetime.strptime(given_date, "%d/%m/%Y").date()

def check_future(given_date:str) -> bool:
    return date.today() < datetime.strptime(given_date, "%d/%m/%Y").date()

def cards_due_per_set(sko_setcontents:[]) -> int | str | None:
    today_str:str= date.today().strftime("%d/%m/%Y")
    if len(sko_setcontents) == 0:
        return "Empty"
    elif len(sko_setcontents) > 0:
        count:int = 0
        date_array:[str] = [card["card_date"] for card in sko_setcontents]
        for dated in date_array:
            if check_overdue(dated) or dated == today_str:
                count += 1
        return count
    else:
        return None

def edit_sko_card(stdscr, card:{}) -> {}:
    edit_option:str = ""
    while True:
        stdscr.erase()
        stdscr.addstr(0, 0, "Choose which attribute to edit.", curses.color_pair(3))
        stdscr.addstr(2,0,f"[N]ame            | {card['card_name']}")
        stdscr.addstr(3,0,f"[I]nfo            | {card['card_info']}")
        stdscr.addstr(4,0,f"[A]dditional info | {card['card_add_info']}")
        stdscr.addstr(5,0,f"Date              | {card['card_date']}", curses.color_pair(1))
        keypress:str = chr(stdscr.getch())
        if keypress in ("n", "i", "a", "q"):
            edit_option = keypress
            break
    match edit_option:
        case "n":
            card_name_buffer:str = card["card_name"]
            while True:
                stdscr.erase()
                stdscr.addstr(0,0,"Editing card name", curses.color_pair(3))
                stdscr.addstr(2,0,f"Name            | {card_name_buffer}_", curses.color_pair(2))
                stdscr.addstr(3,0,f"Info            | {card['card_info']}")
                stdscr.addstr(4,0,f"Additional info | {card['card_add_info']}")
                stdscr.addstr(5,0,f"Date            | {card['card_date']}", curses.color_pair(1))
                stdscr.refresh()
                keypress= stdscr.getch()
                if keypress in (curses.KEY_ENTER, 10, 13):
                    card["card_name"] = card_name_buffer
                    return card
                elif keypress in (curses.KEY_BACKSPACE, 127):
                    card_name_buffer = card_name_buffer[:-1]
                elif 32 <= keypress <= 126:
                    card_name_buffer += chr(keypress)
        case "i":
            card_info_buffer:str = card["card_info"]
            while True:
                stdscr.erase()
                stdscr.addstr(0,0,"Editing card info", curses.color_pair(3))
                stdscr.addstr(2,0,f"Name            | {card['card_name']}")
                stdscr.addstr(3,0,f"Info            | {card_info_buffer}_", curses.color_pair(2))
                stdscr.addstr(4,0,f"Additional info | {card['card_add_info']}")
                stdscr.addstr(5,0,f"Date            | {card['card_date']}", curses.color_pair(1))
                stdscr.refresh()
                keypress= stdscr.getch()
                if keypress in (curses.KEY_ENTER, 10, 13):
                    card["card_info"] = card_info_buffer
                    return card
                elif keypress in (curses.KEY_BACKSPACE, 127):
                    card_info_buffer = card_info_buffer[:-1]
                elif 32 <= keypress <= 126:
                    card_info_buffer += chr(keypress)
        case "a":
            card_add_info_buffer:str = card["card_add_info"]
            while True:
                stdscr.erase()
                stdscr.addstr(0,0,"Editing card additional info", curses.color_pair(3))
                stdscr.addstr(2,0,f"Name            | {card['card_name']}")
                stdscr.addstr(3,0,f"Info            | {card['card_info']}")
                stdscr.addstr(4,0,f"Additional info | {card_add_info_buffer}_", curses.color_pair(2))
                stdscr.addstr(5,0,f"Date            | {card['card_date']}", curses.color_pair(1))
                stdscr.refresh()
                keypress= stdscr.getch()
                if keypress in (curses.KEY_ENTER, 10, 13):
                    card["card_add_info"] = card_add_info_buffer
                    return card
                elif keypress in (curses.KEY_BACKSPACE, 127):
                    card_add_info_buffer = card_add_info_buffer[:-1]
                elif 32 <= keypress <= 126:
                    card_add_info_buffer += chr(keypress)
        case "q":
            return None

def add_sko_card(stdscr) -> {}:
    today_str:str= date.today().strftime("%d/%m/%Y")
    card:{str:str} = {"card_name": "", "card_info": "", "card_add_info": "", "card_date": today_str}
    keypress_buffer:str = ""
    while True:
        stdscr.erase()
        stdscr.addstr(0, 0,"Add card name.", curses.color_pair(3))
        stdscr.addstr(2,0,f"Name            | {keypress_buffer}_", curses.color_pair(2))
        stdscr.addstr(3,0,f"Info            | {card['card_info']}")
        stdscr.addstr(4,0,f"Additional info | {card['card_add_info']}")
        stdscr.addstr(5,0,f"Date            | {card['card_date']}")
        stdscr.refresh()
        keypress = stdscr.getch()
        if keypress in (curses.KEY_ENTER, 10, 13):
            card["card_name"] = keypress_buffer
            break
        elif keypress in (curses.KEY_BACKSPACE, 127):
            keypress_buffer = keypress_buffer[:-1]
        elif 32 <= keypress <= 126:
            keypress_buffer += chr(keypress)
    keypress_buffer = ""
    while True:
        stdscr.erase()
        stdscr.addstr(0, 0,"Add card info.", curses.color_pair(3))
        stdscr.addstr(2,0,f"Name            | {card['card_name']}")
        stdscr.addstr(3,0,f"Info            | {keypress_buffer}_", curses.color_pair(2))
        stdscr.addstr(4,0,f"Additional info | {card['card_add_info']}")
        stdscr.addstr(5,0,f"Date            | {card['card_date']}")
        stdscr.refresh()
        keypress = stdscr.getch()
        if keypress in (curses.KEY_ENTER, 10, 13):
            card["card_info"] = keypress_buffer
            break
        elif keypress in (curses.KEY_BACKSPACE, 127):
            keypress_buffer = keypress_buffer[:-1]
        elif 32 <= keypress <= 126:
            keypress_buffer += chr(keypress)
    keypress_buffer = ""
    while True:
        stdscr.erase()
        stdscr.addstr(0, 0,"Add additional info.", curses.color_pair(3))
        stdscr.addstr(2,0,f"Name            | {card['card_name']}")
        stdscr.addstr(3,0,f"Info            | {card['card_info']}")
        stdscr.addstr(4,0,f"Additional info | {keypress_buffer}_", curses.color_pair(2))
        stdscr.addstr(5,0,f"Date            | {card['card_date']}")
        stdscr.refresh()
        keypress = stdscr.getch()
        if keypress in (curses.KEY_ENTER, 10, 13):
            card["card_add_info"] = keypress_buffer
            break
        elif keypress in (curses.KEY_BACKSPACE, 127):
            keypress_buffer = keypress_buffer[:-1]
        elif 32 <= keypress <= 126:
            keypress_buffer += chr(keypress)
    keypress_buffer = today_str
    while True:
        stdscr.erase()
        stdscr.addstr(0, 0,"Add card date.", curses.color_pair(3))
        stdscr.addstr(2,0,f"Name            | {card['card_name']}")
        stdscr.addstr(3,0,f"Info            | {card['card_info']}")
        stdscr.addstr(4,0,f"Additional info | {card['card_add_info']}")
        stdscr.addstr(5,0,f"Date            | {keypress_buffer}_", curses.color_pair(2))
        stdscr.refresh()
        keypress = stdscr.getch()
        if keypress in (curses.KEY_ENTER, 10, 13):
            card["card_date"] = keypress_buffer
            return card
        elif keypress in (curses.KEY_BACKSPACE, 127):
            keypress_buffer = keypress_buffer[:-1]
        elif 32 <= keypress <= 126:
            keypress_buffer += chr(keypress)

def delete_sko_loop(stdscr, sko_setname:str, sko_setcontents:[]) -> []:
    if not len(sko_setcontents) == 0:
        while True:
            stdscr.erase()
            y_coord:int = 2
            stdscr.addstr(0, 0, f"Type in a valid number to delete card from {sko_setname}.", curses.color_pair(3))
            for card in sko_setcontents:
                stdscr.addstr(y_coord, 0, f"{y_coord-1} | {card['card_name']}")
                y_coord += 1
            stdscr.addstr(y_coord + 1, 0, "[Q]uit", curses.color_pair(3))
            keypress = chr(stdscr.getch())
            if keypress == "q":
                return (sko_setname, sko_setcontents)
            elif not keypress.isnumeric() or int(keypress) > len(sko_setcontents) or int(keypress) < 1:
                continue
            else:
                del sko_setcontents[int(keypress)-1]
                return (sko_setname, sko_setcontents)
    else:
        while True:
            stdscr.erase()
            stdscr.addstr(0, 0, f"{sko_setname} is currently empty. Go make some new cards!", curses.color_pair(5))
            stdscr.addstr(2, 0, "[Q]uit", curses.color_pair(3))
            if chr(stdscr.getch()) == "q":
                return (sko_setname, sko_setcontents)

def update_sko_allsets(sko_all_sets:{}, sko_setname:str, sko_setcontents:[]) -> {}:
    sko_all_sets[sko_setname] = sko_setcontents
    return sko_all_sets

def write_sko(filename:str, sko_contents:{}) -> None:
    file_path:str = os.path.expanduser(f"~/.config/senko/{filename}")
    with open(file_path, "w") as fhand:
        json.dump(sko_contents, fhand)

def edit_sko_loop(stdscr, sko_setname:str, sko_setcontents:[]) -> []:
    if not len(sko_setcontents) == 0:
        while True:
            stdscr.erase()
            y_coord:int = 2
            stdscr.addstr(0, 0, f"Type in a valid number to edit card from {sko_setname}.", curses.color_pair(3))
            for card in sko_setcontents:
                stdscr.addstr(y_coord, 0, f"{y_coord-1} | {card['card_name']}")
                y_coord += 1
            keypress = chr(stdscr.getch())
            if not keypress.isnumeric() or int(keypress) > len(sko_setcontents) or int(keypress) < 1:
                continue
            else:
                result = edit_sko_card(stdscr, sko_setcontents[int(keypress)-1])
                if result is not None:
                    sko_setcontents[int(keypress)-1] = result
                return (sko_setname, sko_setcontents)
    else:
        while True:
            stdscr.erase()
            stdscr.addstr(0, 0, f"{sko_setname} is currently empty. Go make some new cards!", curses.color_pair(5))
            stdscr.addstr(2, 0, "[Q]uit", curses.color_pair(3))
            if chr(stdscr.getch()) == "q":
                return (sko_setname, sko_setcontents)

def add_sko_loop(stdscr, sko_setname:str, sko_setcontents:[]) -> []:
    if not len(sko_setcontents) == 0:
        while True:
            stdscr.erase()
            y_coord:int = 2
            stdscr.addstr(0, 0, f"{sko_setname}")
            for card in sko_setcontents:
                stdscr.addstr(y_coord, 0, f"{y_coord-1} | {card['card_name']}")
                y_coord += 1
            stdscr.addstr(y_coord + 1, 0, f"[A]dd card to {sko_setname}", curses.color_pair(3))
            stdscr.addstr(y_coord + 2, 0, "[Q]uit", curses.color_pair(3))
            keypress = chr(stdscr.getch())
            if keypress == "q":
                return (sko_setname, sko_setcontents)
            elif keypress == "a":
                sko_setcontents.append(add_sko_card(stdscr))
                return (sko_setname, sko_setcontents)
    else:
        while True:
            stdscr.erase()
            stdscr.addstr(0, 0, f"{sko_setname}")
            stdscr.addstr(2, 0, f"{sko_setname} is currently empty.", curses.color_pair(5))
            stdscr.addstr(4, 0, f"[A]dd card to {sko_setname}", curses.color_pair(3))
            stdscr.addstr(5, 0, "[Q]uit", curses.color_pair(3))
            keypress:str = chr(stdscr.getch())
            if keypress == "q":
                return (sko_setname, sko_setcontents)
            elif keypress == "a":
                sko_setcontents.append(add_sko_card(stdscr))
                return (sko_setname, sko_setcontents)

def _stub_screen(stdscr, label):
    stdscr.erase()
    stdscr.addstr(0, 0, f"{label} — coming soon.", curses.color_pair(5))
    stdscr.addstr(2, 0, "Press any key to return.", curses.color_pair(3))
    stdscr.refresh()
    stdscr.getch()

def _menu_dispatch(stdscr, action):
    """shared flow for see/add/edit/delete actions."""
    sko_filename = select_sko_file(stdscr)
    if sko_filename is None:
        return
    sko_all_sets = read_sko(sko_filename)
    sko_setname_setcontents = select_flashcard_set(stdscr, sko_all_sets, sko_filename)
    if sko_setname_setcontents is None:
        return
    sko_setname = sko_setname_setcontents[0]
    sko_setcontents = sko_setname_setcontents[1]
    match action:
        case "review":
            result = render_sko_loop(stdscr, sko_setname, sko_setcontents)
        case "add":
            result = add_sko_loop(stdscr, sko_setname, sko_setcontents)
        case "edit":
            result = edit_sko_loop(stdscr, sko_setname, sko_setcontents)
        case "delete":
            result = delete_sko_loop(stdscr, sko_setname, sko_setcontents)
    write_sko(sko_filename, update_sko_allsets(sko_all_sets, sko_setname, result[1]))

def menu_sko(stdscr) -> None:
    from tui import select_from_list, COLORS
    menu_items = [
        ("Review cards", "", COLORS["accent"]),
        ("Browse decks", "", COLORS["info"]),
        ("Import cards", "", COLORS["success"]),
        ("Export cards", "", COLORS["success"]),
        ("Statistics", "", COLORS["muted"]),
        ("Settings", "", COLORS["prompt"]),
        ("Quit", "", COLORS["error"]),
    ]
    while True:
        choice = select_from_list(stdscr, "Senko flashcards", menu_items, footer="Spot issues? Ping me on Github @gongahkia.")
        if choice is None or choice == 6: # quit
            return
        elif isinstance(choice, tuple):
            continue
        match choice:
            case 0: # review
                _menu_dispatch(stdscr, "review")
            case 1: # browse decks
                _menu_dispatch(stdscr, "review")
            case 2: # import
                _stub_screen(stdscr, "Import")
            case 3: # export
                _stub_screen(stdscr, "Export")
            case 4: # statistics
                _stub_screen(stdscr, "Statistics")
            case 5: # settings
                _stub_screen(stdscr, "Settings")

run_app(menu_sko)
