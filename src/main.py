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

def select_flashcard_set(stdscr, file_contents:{}) -> (str,[]):
    name_array:[str] = [set_name for set_name in file_contents]
    while True:
        stdscr.erase()
        coords:{str:int}= {"x":0, "y":2}
        counter:int = 1
        stdscr.addstr(0, 0, "Type in a valid number to select flashcard set.", curses.color_pair(3))
        for flashcard_set in name_array:
            cards_due = cards_due_per_set(file_contents[flashcard_set])
            match cards_due:
                case "Empty":
                    stdscr.addstr(coords["y"], coords["x"], f"{counter} | {flashcard_set} | ")
                    stdscr.addstr(coords["y"], len(str(counter)) + len(flashcard_set) + 6, cards_due, curses.color_pair(5))
                case 0:
                    stdscr.addstr(coords["y"], coords["x"], f"{counter} | {flashcard_set} | ")
                    stdscr.addstr(coords["y"], len(str(counter)) + len(flashcard_set) + 6, str(cards_due), curses.color_pair(2))
                case _:
                    stdscr.addstr(coords["y"], coords["x"], f"{counter} | {flashcard_set} | ")
                    stdscr.addstr(coords["y"], len(str(counter)) + len(flashcard_set) + 6, str(cards_due), curses.color_pair(1))
            coords["y"] += 1
            counter += 1
        keypress = chr(stdscr.getch())
        if not keypress.isnumeric() or int(keypress) > len(name_array) or int(keypress) < 1:
            continue
        else:
            return (name_array[int(keypress) - 1], file_contents[name_array[int(keypress) - 1]])

def render_sko_card(stdscr, card:{}) -> str:
    while True:
        stdscr.erase()
        stdscr.addstr(0, 0, card["card_name"])
        stdscr.addstr(2, 0, "[S]how card", curses.color_pair(3))
        keypress = chr(stdscr.getch())
        if keypress == "s":
            break
    while True:
        stdscr.erase()
        if card["card_name"]:
            stdscr.addstr(0, 0, card["card_name"])
        if card["card_info"]:
            stdscr.addstr(1, 0, card["card_info"])
        if card["card_add_info"]:
            stdscr.addstr(2, 0, card["card_add_info"])
        stdscr.addstr(4, 0, "[Q] Easy", curses.color_pair(2))
        stdscr.addstr(5, 0, "[W] Medium", curses.color_pair(5))
        stdscr.addstr(6, 0, "[E] Hard", curses.color_pair(1))
        keypress_choose = chr(stdscr.getch())
        match keypress_choose:
            case "q":
                return "easy"
            case "w":
                return "medium"
            case "e":
                return "hard"

def render_sko_loop(stdscr, sko_setname:str, sko_setcontents:[]) -> ():
    today_str:str= date.today().strftime("%d/%m/%Y")
    while True:
        if len(sko_setcontents) == 0:
            while True:
                stdscr.erase()
                stdscr.addstr(0, 0, f"{sko_setname} is currently empty. Go make some new cards!", curses.color_pair(5))
                stdscr.addstr(2, 0, "[Q]uit", curses.color_pair(3))
                if chr(stdscr.getch()) == "q":
                    return (sko_setname, sko_setcontents)
        date_array:[str] = [card["card_date"] for card in sko_setcontents]
        count:int = 0
        for dated in date_array:
            if check_future(dated):
                count += 1
        if count == len(date_array):
            while True:
                stdscr.erase()
                stdscr.addstr(0, 0, f"You have finished all {sko_setname} cards for the day! Take a break!", curses.color_pair(2))
                stdscr.addstr(2, 0, "[Q]uit", curses.color_pair(3))
                if chr(stdscr.getch()) == "q":
                    return (sko_setname, sko_setcontents)
        for card in sko_setcontents:
            if check_overdue(card["card_date"]):
                card["card_date"] = today_str
            if card["card_date"] == today_str:
                difficulty:str = render_sko_card(stdscr, card)
                match difficulty:
                    case "easy":
                        card["card_date"] = add_days(card["card_date"], 3)
                    case "medium":
                        card["card_date"] = add_days(card["card_date"], 2)
                    case "hard":
                        card["card_date"] = add_days(card["card_date"], 0)

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
    sko_setname_setcontents = select_flashcard_set(stdscr, sko_all_sets)
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
