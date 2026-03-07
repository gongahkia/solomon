from datetime import date, datetime, timedelta

def sm2_review(card:dict, grade:int, config:dict=None) -> dict:
    min_ease = 1.3
    easy_bonus = 1.3
    if config and "srs" in config:
        min_ease = config["srs"].get("minimum_ease", 1.3)
        easy_bonus = config["srs"].get("easy_bonus", 1.3)
    ef = card.get("ease_factor", 2.5)
    interval = card.get("interval", 0)
    reps = card.get("repetitions", 0)
    match grade:
        case 0: # again
            reps = 0
            interval = 1
            ef = max(min_ease, ef - 0.2)
        case 1: # hard
            reps = 0
            interval = max(1, interval)
            ef = max(min_ease, ef - 0.15)
        case 2: # good
            if reps == 0:
                interval = 1
            elif reps == 1:
                interval = 6
            else:
                interval = round(interval * ef)
            reps += 1
        case 3: # easy
            if reps == 0:
                interval = 1
            elif reps == 1:
                interval = 6
            else:
                interval = round(interval * ef)
            interval = round(interval * easy_bonus)
            ef += 0.15
            reps += 1
    card["ease_factor"] = ef
    card["interval"] = interval
    card["repetitions"] = reps
    card["card_date"] = (date.today() + timedelta(days=interval)).strftime("%d/%m/%Y")
    return card

def cards_due(cards:list) -> list:
    today = date.today()
    result = []
    for card in cards:
        try:
            card_date = datetime.strptime(card["card_date"], "%d/%m/%Y").date()
            if card_date <= today:
                result.append(card)
        except (ValueError, KeyError):
            result.append(card) # malformed dates are treated as due
    return result

def cards_due_count(cards:list) -> int:
    return len(cards_due(cards))
