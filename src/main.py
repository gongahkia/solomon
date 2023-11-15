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

# makes the senko file directory in ~/.config folder
def make_senko_dir() -> None:
    os.system("mkdir ~/.config/senko")

# FUA returns a filename as a string to open using curses CLI --> DEBUG WHY NO WORK
def select_sko_file() -> str:
    file_path:str = "~/.config/senko/"
    make_senko_dir()
    valid_array:[str] = [file_name for file_name in os.listdir(file_path) if file_name.split(".")[1] == "sko"]
    print(valid_array)

# destructures a .sko file into a python dictionary
def read_sko(filename:str) -> {}:
    fhand = open(filename,"r")
    sko_contents:{str:[]}= json.loads(fhand.read())
    fhand.close()
    return sko_contents

# FUA reads through the file, creates a curses frontend for users to select which card set they want
def select_flashcard_set(file_contents:{}) -> {}:
    pass

# FUA add code inside to instantiate screen and everything, for reading through a json and presenting qns
def render_sko(sko_contents:{}) -> None:
    pass

# FUA adds days from card_difficulty from sko_contents to a date, convert to int using format learnt in is111 lab 2, return date in string format for easy checking
def add_days(date:str, days_add:int) -> str:
    pass

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

make_senko_dir()
read_sko("eg.sko")
select_sko_file()
