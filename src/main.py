# mypy: ignore-errors
# silence mypy type errors

# imports
import curses
import json
import os

"""
# print("senko test")
screen = curses.initscr()
screen.keypad(True)
curses.noecho()
curses.cbreak()
curses.curs_set(0)

if curses.has_colors():
    curses.start_color()
    curses.init_pair(1, curses.COLOR_RED, curses.COLOR_BLACK)
    curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(3, curses.COLOR_YELLOW, curses.COLOR_BLACK)
    curses.init_pair(4, curses.COLOR_BLUE, curses.COLOR_BLACK)
    curses.init_pair(5, curses.COLOR_MAGENTA, curses.COLOR_BLACK)
    curses.init_pair(6, curses.COLOR_CYAN, curses.COLOR_BLACK)
    curses.init_pair(7, curses.COLOR_WHITE, curses.COLOR_BLACK)

screen.erase()
screen.addstr("nice")
screen.timeout(0)
screen.refresh()
curses.napms(1000)

curses.nocbreak()
screen.keypad(False)
curses.echo()
curses.endwin()
"""

# returns a filename as a string to open, renders in curses CLI
def select_sko_file() -> str:

    file_path:str = os.path.expanduser("~/.config/senko")
    valid_array:[str] = [file_name for file_name in os.listdir(file_path) if file_name.split(".")[1] == "sko"]

    screen = curses.initscr()
    screen.keypad(True)
    curses.cbreak()
    curses.curs_set(0)
    if curses.has_colors():
        curses.start_color()
        curses.init_pair(3, curses.COLOR_YELLOW, curses.COLOR_BLACK)
        curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)

    while True:
        screen.erase()
        coords:{str:int}= {"x":0, "y":2}
        counter:int = 1
        screen.addstr(0, 0, "Type in a valid number", curses.color_pair(3))
        for file_name in valid_array:
            screen.addstr(coords["y"], coords["x"], f"{counter} | {file_name}")
            coords["y"] += 1
            counter += 1
        keypress = chr(screen.getch())
        if not keypress.isnumeric() or int(keypress) > len(valid_array) or int(keypress) < 1:
            continue
        else:
            screen.erase()
            screen.addstr(0,0,"Loading your senko set...", curses.color_pair(2))
            screen.refresh()
            screen.keypad(False)
            curses.echo()
            curses.endwin()
            return valid_array[int(keypress) - 1]

# destructures a .sko file into a python dictionary
def read_sko(filename:str) -> {}:
    file_path:str = os.path.expanduser(f"~/.config/senko/{filename}")
    fhand = open(file_path,"r")
    sko_contents:{str:[]}= json.loads(fhand.read())
    fhand.close()
    return sko_contents

# reads through the file and allows users to select which card set they want
def select_flashcard_set(file_contents:{}) -> (str,{}):

    name_array:[str] = [set_name for set_name in file_contents]

    screen = curses.initscr()
    screen.keypad(True)
    curses.cbreak()
    curses.curs_set(0)
    if curses.has_colors():
        curses.start_color()
        curses.init_pair(3, curses.COLOR_YELLOW, curses.COLOR_BLACK)
        curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)

    while True:
        screen.erase()
        coords:{str:int}= {"x":0, "y":2}
        counter:int = 1
        screen.addstr(0, 0, "Type in a valid number", curses.color_pair(3))
        for flashcard_set in name_array:
            screen.addstr(coords["y"], coords["x"], f"{counter} | {flashcard_set}")
            coords["y"] += 1
            counter += 1
        keypress = chr(screen.getch())
        if not keypress.isnumeric() or int(keypress) > len(name_array) or int(keypress) < 1:
            continue
        else:
            screen.erase()
            screen.addstr(0,0,"Loading your senko set...", curses.color_pair(2))
            screen.refresh()
            screen.keypad(False)
            curses.echo()
            curses.endwin()
            return (name_array[int(keypress) - 1], file_contents[name_array[int(keypress) - 1]])

# FUA add code inside to instantiate screen and everything, for reading through a json and presenting qns, takes in input for difficulty of each card
def render_sko(sko_contents:{}) -> {}:
    pass

# adds days from card_difficulty from sko_contents to a date
def add_days(date:str, days_add:int) -> str:
    new_dat:int = int(date.split("/")[0]) + (int(date.split("/")[1]) * 30) + (int(date.split("/")[2]) * 365) + days_add
    new_year:int = new_dat // 365 
    new_month:int = (new_dat % 365) // 30
    new_month_str:str = f"{new_month}"
    new_day:int = (new_dat % 365) % 30
    new_day_str:str = f"{new_day}"
    if new_month < 10:
        new_month_str:str = f"0{new_month}"
    if new_day < 10:
        new_day_str:str = f"0{new_day}"
    return f"{new_day_str}/{new_month_str}/{new_year}"

# FUA provides the frontend for editing flashcards in curses cli, returns the edited dictionary
def edit_sko(sko_contents:{}) -> {}:
    pass

# FUA add flashcards to an existing senko dictionary and return the edited dictionary
def add_sko(sko_contents:{}) -> {}:
    pass

# FUA delete flashcards from an existing senko dictionary and return the edited dictionary
def delete_sko(sko_contents:{}) -> {}:
    pass

# FUA checks the validity of a senko file, for each value, and checks whether a set is empty, if so warn the user accordingly
def check_sko(filename:str) -> bool:
    pass

# FUA writes the inputted dictionary to the Senko file for saving
def write_sko(filename:str, sko_contents:{}) -> None:
    pass

print(select_flashcard_set(read_sko(select_sko_file())))