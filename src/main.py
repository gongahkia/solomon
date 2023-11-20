# mypy: ignore-errors
# silence mypy type errors

# imports
import curses
import json
import os
from datetime import date

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

# checks the syntax of a senko file
def check_sko(filename:str) -> bool:
    try:
        file_path:str = os.path.expanduser(f"~/.config/senko/{filename}")
        fhand = open(file_path,"r")
        sko_contents:{str:[]}= json.loads(fhand.read())
        fhand.close()
        return True
    except:
        return False

# returns a filename as a string to open, renders in curses CLI
def select_sko_file() -> str | None:

    file_path:str = os.path.expanduser("~/.config/senko")
    valid_array:[str] = [file_name for file_name in os.listdir(file_path) if file_name.split(".")[1] == "sko" and check_sko(file_name)]

    screen = curses.initscr()
    screen.keypad(True)
    curses.cbreak()
    curses.curs_set(0)
    if curses.has_colors():
        curses.start_color()
        curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)
        curses.init_pair(3, curses.COLOR_YELLOW, curses.COLOR_BLACK)
        curses.init_pair(5, curses.COLOR_MAGENTA, curses.COLOR_BLACK)

    while True:
        if not len(valid_array) == 0:
            screen.erase()
            coords:{str:int}= {"x":0, "y":2}
            counter:int = 1
            screen.addstr(0, 0, "Type in a valid number", curses.color_pair(3))
            for file_name in valid_array:
                num_files:int = len(read_sko(file_name))
                screen.addstr(coords["y"], coords["x"], f"{counter} | {file_name} | ")
                screen.addstr(coords["y"], len(str(counter)) + len(file_name) + 6, f"{num_files} decks", curses.color_pair(2))
                coords["y"] += 1
                counter += 1
            keypress = chr(screen.getch())
            if not keypress.isnumeric() or int(keypress) > len(valid_array) or int(keypress) < 1:
                continue
            else:
                screen.erase()
                screen.refresh()
                screen.keypad(False)
                curses.echo()
                curses.endwin()
                return valid_array[int(keypress) - 1]
        else:
            screen.erase()
            counter:int = 1
            screen.addstr(0, 0, "No valid senko (.sko) files found.", curses.color_pair(5))
            screen.addstr(2, 0, "[Q]uit", curses.color_pair(3))
            keypress = chr(screen.getch())
            if not keypress == "q":
                continue
            else:
                screen.erase()
                screen.refresh()
                screen.keypad(False)
                curses.echo()
                curses.endwin()
                return None

# destructures a .sko file into a python dictionary
def read_sko(filename:str) -> {}:
    file_path:str = os.path.expanduser(f"~/.config/senko/{filename}")
    fhand = open(file_path,"r")
    sko_contents:{str:[]}= json.loads(fhand.read())
    fhand.close()
    return sko_contents

# reads through the file and allows users to select which card set they want
def select_flashcard_set(file_contents:{}) -> (str,[]):

    name_array:[str] = [set_name for set_name in file_contents]

    screen = curses.initscr()
    screen.keypad(True)
    curses.cbreak()
    curses.curs_set(0)
    if curses.has_colors():
        curses.start_color()
        curses.init_pair(1, curses.COLOR_RED, curses.COLOR_BLACK)
        curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)
        curses.init_pair(3, curses.COLOR_YELLOW, curses.COLOR_BLACK)
        curses.init_pair(5, curses.COLOR_MAGENTA, curses.COLOR_BLACK)

    while True:
        screen.erase()
        coords:{str:int}= {"x":0, "y":2}
        counter:int = 1
        screen.addstr(0, 0, "Type in a valid number", curses.color_pair(3))

        # rendering flashcard options
        for flashcard_set in name_array:
            cards_due = cards_due_per_set(file_contents[flashcard_set])
            match cards_due:
                case "Empty":
                    screen.addstr(coords["y"], coords["x"], f"{counter} | {flashcard_set} | ")
                    screen.addstr(coords["y"], len(str(counter)) + len(flashcard_set) + 6, cards_due, curses.color_pair(5))
                    coords["y"] += 1
                    counter += 1
                    
                case 0:
                    screen.addstr(coords["y"], coords["x"], f"{counter} | {flashcard_set} | ")
                    screen.addstr(coords["y"], len(str(counter)) + len(flashcard_set) + 6, str(cards_due), curses.color_pair(2))
                    coords["y"] += 1
                    counter += 1

                case _:
                    screen.addstr(coords["y"], coords["x"], f"{counter} | {flashcard_set} | ")
                    screen.addstr(coords["y"], len(str(counter)) + len(flashcard_set) + 6, str(cards_due), curses.color_pair(1))
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

# renders relevant card information, returns the difficulty
def render_sko_card(card:{}) -> str:

    screen = curses.initscr()
    screen.keypad(True)
    curses.cbreak()
    curses.curs_set(0)

    if curses.has_colors():
        curses.start_color()
        curses.init_pair(1, curses.COLOR_RED, curses.COLOR_BLACK)
        curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)
        curses.init_pair(3, curses.COLOR_YELLOW, curses.COLOR_BLACK)
        curses.init_pair(5, curses.COLOR_MAGENTA, curses.COLOR_BLACK)

    while True:
        screen.erase()
        screen.addstr(0, 0, card["card_name"])
        screen.addstr(2, 0, "[S]how card", curses.color_pair(3))

        keypress = chr(screen.getch())

        if not keypress == "s":
            continue
        else:
            break

    while True:
        screen.erase()
        if card["card_name"]:
            screen.addstr(0, 0, card["card_name"])
        else:
            screen.addstr(0, 0, "")
        if card["card_info"]:
            screen.addstr(1, 0, card["card_info"])
        else:
            screen.addstr(0, 0, "")
        if card["card_add_info"]:
            screen.addstr(2, 0, card["card_add_info"])
        else:
            screen.addstr(0, 0, "")

        screen.addstr(4, 0, "[Q] Easy", curses.color_pair(2))
        screen.addstr(5, 0, "[W] Medium", curses.color_pair(5))
        screen.addstr(6, 0, "[E] Hard", curses.color_pair(1))

        keypress_choose = chr(screen.getch())
        difficulty:str = ""

        match keypress_choose:
            case "q":
                difficulty = "easy"
                break
            case "w":
                difficulty = "medium"
                break
            case "e":
                difficulty = "hard"
                break
            case _:
                continue

    screen.erase()
    screen.refresh()
    screen.keypad(False)
    curses.echo()
    curses.endwin()
    return difficulty

# runs whenever a card set is run
def render_sko_loop(sko_setname:str, sko_setcontents:[]) -> ():
    today_str:str= date.today().strftime("%d/%m/%Y")

    while True:
    
        # empty set
        if len(sko_setcontents) == 0:

            screen = curses.initscr()
            screen.keypad(True)
            curses.noecho()
            curses.cbreak()
            curses.curs_set(0)

            if curses.has_colors():
                curses.start_color()
                curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)
                curses.init_pair(3, curses.COLOR_YELLOW, curses.COLOR_BLACK)
                curses.init_pair(5, curses.COLOR_MAGENTA, curses.COLOR_BLACK)

            while True:

                screen.erase()
                screen.addstr(0, 0, f"{sko_setname} is currently empty. Go make some new cards!", curses.color_pair(5))
                screen.addstr(2, 0, "[Q]uit", curses.color_pair(3))

                keypress:str = chr(screen.getch())

                if keypress != "q":
                    continue
                else:
                    screen.refresh()
                    curses.nocbreak()
                    screen.keypad(False)
                    curses.echo()
                    curses.endwin()
                    return (sko_setname, sko_setcontents)

        # break condition
        date_array:[str] = [card["card_date"] for card in sko_setcontents]
        count:int = 0
        for dated in date_array:
            if check_future(dated):
                count += 1

        if count == len(date_array):

            # completed decks screen
            screen = curses.initscr()
            screen.keypad(True)
            curses.noecho()
            curses.cbreak()
            curses.curs_set(0)

            while True:

                screen.erase()
                screen.addstr(0, 0, f"You have finished all {sko_setname} cards for the day! Take a break!", curses.color_pair(2))
                screen.addstr(2, 0, "[Q]uit", curses.color_pair(3))

                keypress:str = chr(screen.getch())

                if keypress != "q":
                    continue
                else:
                    screen.refresh()
                    curses.nocbreak()
                    screen.keypad(False)
                    curses.echo()
                    curses.endwin()
                    return (sko_setname, sko_setcontents)

        # loop content
        for card in sko_setcontents:

            if check_overdue(card["card_date"]):
                card["card_date"] = today_str

            if card["card_date"] == today_str:
                difficulty:str = render_sko_card(card)
                match difficulty: # edit below to change how often the card should be shown
                    case "easy":
                        card["card_date"] = add_days(card["card_date"], 3)
                    case "medium":
                        card["card_date"] = add_days(card["card_date"], 2)
                    case "hard":
                        card["card_date"] = add_days(card["card_date"], 0)

# adds days to sko_contents to a date
def add_days(given_date:str, days_add:int) -> str:
    new_dat:int = int(given_date.split("/")[0]) + (int(given_date.split("/")[1]) * 30) + (int(given_date.split("/")[2]) * 365) + days_add
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

def check_overdue(given_date:str) -> bool:
    today_str:str= date.today().strftime("%d/%m/%Y")
    tod_dat:int = int(today_str.split("/")[0]) + (int(today_str.split("/")[1]) * 30) + (int(today_str.split("/")[2]) * 365)
    given_dat:int = int(given_date.split("/")[0]) + (int(given_date.split("/")[1]) * 30) + (int(given_date.split("/")[2]) * 365)
    return tod_dat > given_dat

def check_future(given_date:str) -> bool:
    today_str:str= date.today().strftime("%d/%m/%Y")
    tod_dat:int = int(today_str.split("/")[0]) + (int(today_str.split("/")[1]) * 30) + (int(today_str.split("/")[2]) * 365)
    given_dat:int = int(given_date.split("/")[0]) + (int(given_date.split("/")[1]) * 30) + (int(given_date.split("/")[2]) * 365)
    return tod_dat < given_dat

# counts the number of cards due per Senko card set
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

def edit_sko_card(card:{}) -> {}:

    edit_option:str = ""
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
        curses.init_pair(5, curses.COLOR_MAGENTA, curses.COLOR_BLACK)

    while True:
        screen.erase()
        screen.addstr(0, 0, "Choose which attribute to edit.", curses.color_pair(3))
        screen.addstr(2,0,f"[N]ame            | {card['card_name']}")
        screen.addstr(3,0,f"[I]nfo            | {card['card_info']}")
        screen.addstr(4,0,f"[A]dditional info | {card['card_add_info']}")
        screen.addstr(5,0,f"Date              | {card['card_date']}", curses.color_pair(1)) # rendered in diff color to ensure it appears uneditable

        keypress:str = chr(screen.getch())

        if keypress == "n" or keypress == "i" or keypress == "a" or keypress == "q":
            edit_option = keypress
            break
        else:
            continue

    match edit_option:

        case "n":

            card_name_buffer:str = card["card_name"]

            while True:

                screen.erase()
                screen.addstr(0,0,"Editing card name", curses.color_pair(3))
                screen.addstr(2,0,f"Name            | {card_name_buffer}_", curses.color_pair(2))
                screen.addstr(3,0,f"Info            | {card['card_info']}")
                screen.addstr(4,0,f"Additional info | {card['card_add_info']}")
                screen.addstr(5,0,f"Date            | {card['card_date']}", curses.color_pair(1))
                screen.refresh()

                keypress= screen.getch()

                if keypress == curses.KEY_ENTER or keypress == 10 or keypress == 13:
                    screen.refresh()
                    card["card_name"] = card_name_buffer
                    curses.nocbreak()
                    screen.keypad(False)
                    curses.echo()
                    curses.endwin()
                    return card

                elif keypress == ord("\t") or keypress == 9: # tab
                    card_name_buffer += "\t"

                elif keypress == curses.KEY_BACKSPACE or keypress == 127:
                    card_name_buffer = card_name_buffer[:-1]
                
                else:
                    card_name_buffer += chr(keypress)

        case "i":

            card_info_buffer:str = card["card_info"]

            while True:

                screen.erase()
                screen.addstr(0,0,"Editing card info", curses.color_pair(3))
                screen.addstr(2,0,f"Name            | {card['card_name']}")
                screen.addstr(3,0,f"Info            | {card_info_buffer}_", curses.color_pair(2))
                screen.addstr(4,0,f"Additional info | {card['card_add_info']}")
                screen.addstr(5,0,f"Date            | {card['card_date']}", curses.color_pair(1))
                screen.refresh()

                keypress= screen.getch()

                if keypress == curses.KEY_ENTER or keypress == 10 or keypress == 13:
                    screen.refresh()
                    card["card_info"] = card_info_buffer
                    curses.nocbreak()
                    screen.keypad(False)
                    curses.echo()
                    curses.endwin()
                    return card

                elif keypress == ord("\t") or keypress == 9: # tab
                    card_info_buffer += "\t"

                elif keypress == curses.KEY_BACKSPACE or keypress == 127:
                    card_info_buffer = card_info_buffer[:-1]
                
                else:
                    card_info_buffer += chr(keypress)

        case "a":

            card_add_info_buffer:str = card["card_add_info"]

            while True:

                screen.erase()
                screen.addstr(0,0,"Editing card additional info", curses.color_pair(3))
                screen.addstr(2,0,f"Name            | {card['card_name']}")
                screen.addstr(3,0,f"Info            | {card['card_info']}")
                screen.addstr(4,0,f"Additional info | {card_add_info_buffer}_", curses.color_pair(2))
                screen.addstr(5,0,f"Date            | {card['card_date']}", curses.color_pair(1))
                screen.refresh()

                keypress= screen.getch()

                if keypress == curses.KEY_ENTER or keypress == 10 or keypress == 13:
                    screen.refresh()
                    card["card_add_info"] = card_add_info_buffer
                    curses.nocbreak()
                    screen.keypad(False)
                    curses.echo()
                    curses.endwin()
                    return card

                elif keypress == ord("\t") or keypress == 9: # tab
                    card_add_info_buffer += "\t"

                elif keypress == curses.KEY_BACKSPACE or keypress == 127:
                    card_add_info_buffer = card_add_info_buffer[:-1]
                
                else:
                    card_add_info_buffer += chr(keypress)

        case "q":
            return None

# FUA provides the frontend for editing flashcards in curses cli, returns the edited dictionary and uses edit_sko_card(), function should allow selection of a given card
def edit_sko_loop(sko_setname:str, sko_setcontents:[]) -> []:
    pass

# FUA takes in nothing and returns a new card to be added to the current set, provides a front end for creating a card, in similar vein of editing indivudal card as edit_sko_card()
def add_sko_card() -> {}:

    today_str:str= date.today().strftime("%d/%m/%Y")
    card:{str:str} = {
            "card_name": "",
            "card_info": "",
            "card_add_info": "",
            "card_date": today_str # add an interesting way to type in dates where it auto adds the / for you and checks validity of date
        }
    keypress_buffer:str = ""

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
        curses.init_pair(5, curses.COLOR_MAGENTA, curses.COLOR_BLACK)

    while True:
        screen.erase()
        screen.addstr(0, 0,"Add player name.", curses.color_pair(3))
        screen.addstr(2,0,f"Name            | {keypress_buffer}_", curses.color_pair(2))
        screen.addstr(3,0,f"Info            | {card['card_info']}")
        screen.addstr(4,0,f"Additional info | {card['card_add_info']}")
        screen.addstr(5,0,f"Date            | {card['card_date']}")
        screen.refresh()

        keypress = screen.getch()

        if keypress == curses.KEY_ENTER or keypress == 10 or keypress == 13:
            screen.refresh()
            card["card_name"] = keypress_buffer
            break

        elif keypress == ord("\t") or keypress == 9: # tab
            keypress_buffer += "\t"

        elif keypress == curses.KEY_BACKSPACE or keypress == 127:
            keypress_buffer = keypress_buffer[:-1]
        
        else:
            keypress_buffer += chr(keypress)

    keypress_buffer = ""

    while True:
        screen.erase()
        screen.addstr(0, 0,"Add player name.", curses.color_pair(3))
        screen.addstr(2,0,f"Name            | {card['card_name']}")
        screen.addstr(3,0,f"Info            | {keypress_buffer}_", curses.color_pair(2))
        screen.addstr(4,0,f"Additional info | {card['card_add_info']}")
        screen.addstr(5,0,f"Date            | {card['card_date']}") 
        screen.refresh()

        keypress = screen.getch()

        if keypress == curses.KEY_ENTER or keypress == 10 or keypress == 13:
            screen.refresh()
            card["card_info"] = keypress_buffer
            break

        elif keypress == ord("\t") or keypress == 9: # tab
            keypress_buffer += "\t"

        elif keypress == curses.KEY_BACKSPACE or keypress == 127:
            keypress_buffer = keypress_buffer[:-1]
        
        else:
            keypress_buffer += chr(keypress)

    keypress_buffer = ""

    while True:
        screen.erase()
        screen.addstr(0, 0,"Add player name.", curses.color_pair(3))
        screen.addstr(2,0,f"Name            | {card['card_name']}")
        screen.addstr(3,0,f"Info            | {card['card_info']}")
        screen.addstr(4,0,f"Additional info | {keypress_buffer}_", curses.color_pair(2))
        screen.addstr(5,0,f"Date            | {card['card_date']}") 
        screen.refresh()

        keypress = screen.getch()

        if keypress == curses.KEY_ENTER or keypress == 10 or keypress == 13:
            screen.refresh()
            card["card_add_info"] = keypress_buffer
            break

        elif keypress == ord("\t") or keypress == 9: # tab
            keypress_buffer += "\t"

        elif keypress == curses.KEY_BACKSPACE or keypress == 127:
            keypress_buffer = keypress_buffer[:-1]
        
        else:
            keypress_buffer += chr(keypress)

    keypress_buffer = today_str

    while True:
        screen.erase()
        screen.addstr(0, 0,"Add player name.", curses.color_pair(3))
        screen.addstr(2,0,f"Name            | {card['card_name']}")
        screen.addstr(3,0,f"Info            | {card['card_info']}")
        screen.addstr(4,0,f"Additional info | {card['card_add_info']}")
        screen.addstr(5,0,f"Date            | {keypress_buffer}_", curses.color_pair(2))
        screen.refresh()

        keypress = screen.getch()

        if keypress == curses.KEY_ENTER or keypress == 10 or keypress == 13:
            screen.refresh()
            card["card_date"] = keypress_buffer
            curses.nocbreak()
            screen.keypad(False)
            curses.echo()
            curses.endwin()
            return card

        elif keypress == ord("\t") or keypress == 9: # tab
            keypress_buffer += "\t"

        elif keypress == curses.KEY_BACKSPACE or keypress == 127:
            keypress_buffer = keypress_buffer[:-1]
        
        else:
            keypress_buffer += chr(keypress)

# FUA add flashcards to an existing senko dictionary and return the edited dictionary, runs check_sko(), and integrate the add_sko_card() function here
def add_sko_loop(sko_setname:str, sko_setcontents:[]) -> []:
    pass

# FUA delete flashcards from an existing senko dictionary and return the edited dictionary
def delete_sko_loop(sko_setname:str, sko_setcontents:[]) -> []:
    pass

# FUA provides the frontend for choosing what mode of senko you want to use, use, add, edit existing, delete cards, include running check_sko() for valid or invalid files
def menu_sko() -> None:
    pass

# updates the overall senko file's dictionary which can then be written to the file using write_sko(), this should update the existing key
def update_sko_allsets(sko_all_sets:{}, sko_setname:str, sko_setcontents:[]) -> {}:
    sko_all_sets[sko_setname] = sko_setcontents
    return sko_all_sets

# writes the inputted dictionary to the Senko file for saving
def write_sko(filename:str, sko_contents:{}) -> None:
    file_path:str = os.path.expanduser(f"~/.config/senko/{filename}")
    fhand = open(file_path,"w")
    fhand.write(json.dumps(sko_contents))
    fhand.close()
    return None

"""
sko_filename:str = select_sko_file()
sko_all_sets:{} = read_sko(sko_filename)
sko_setname_setcontents:(str,[]) = select_flashcard_set(sko_all_sets)
sko_setname:str = sko_setname_setcontents[0]
sko_setcontents:[] = sko_setname_setcontents[1] # this should be the only global copy that is transformed using all functions
write_sko(sko_filename, update_sko_allsets(sko_all_sets, sko_setname, render_sko_loop(sko_setname, sko_setcontents)[1]))

eg_card:{} = {
            "card_name": "apple",
            "card_info": "a kind of fruit",
            "card_add_info": "I like to eat apples and other fruits.",
            "card_date": "17/11/2023"
        }
print(edit_sko_card(eg_card))
"""

print(add_sko_card())

# write_sko(sko_filename, update_sko_allsets(sko_all_sets, sko_setname, sko_setcontents))
