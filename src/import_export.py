import json
from datetime import date
from schema import CARD_DEFAULTS, migrate_card

def import_from_txt(filepath:str) -> dict:
    with open(filepath, "r") as f:
        content = f.read()
    blocks = content.split("---")
    result = {}
    for block in blocks:
        lines = [l.strip() for l in block.strip().splitlines() if l.strip()]
        if not lines:
            continue
        if not lines[0].startswith("TOPIC: "):
            continue
        set_name = lines[0][len("TOPIC: "):]
        if len(lines) < 2:
            continue
        card_name = lines[1]
        card_info = "\n".join(lines[2:]) if len(lines) > 2 else ""
        card = {"card_name": card_name, "card_info": card_info, "card_add_info": "", "card_date": date.today().strftime("%d/%m/%Y")}
        card.update(CARD_DEFAULTS.copy())
        result.setdefault(set_name, []).append(card)
    return result

def import_from_json(filepath:str) -> dict:
    with open(filepath, "r") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("JSON must be a dict of {set_name: [cards]}")
    for k, v in data.items():
        if not isinstance(v, list):
            raise ValueError(f"Set '{k}' must be a list of card dicts")
        for i, card in enumerate(v):
            if not isinstance(card, dict):
                raise ValueError(f"Card {i} in set '{k}' must be a dict")
            v[i] = migrate_card(card)
    return data

def export_to_json(sko_contents:dict, filepath:str) -> None:
    with open(filepath, "w") as f:
        json.dump(sko_contents, f, indent=2)

def export_to_txt(sko_contents:dict, filepath:str) -> None:
    with open(filepath, "w") as f:
        for set_name, cards in sko_contents.items():
            for card in cards:
                f.write("---\n")
                f.write(f"TOPIC: {set_name}\n")
                f.write(f"{card.get('card_name', '')}\n")
                info = card.get("card_info", "")
                if info:
                    f.write(f"{info}\n")
                add_info = card.get("card_add_info", "")
                if add_info:
                    f.write(f"{add_info}\n")
        f.write("---\n")
