REQUIRED_CARD_KEYS = ["card_name", "card_info", "card_add_info", "card_date", "ease_factor", "interval", "repetitions"]
CARD_DEFAULTS = {"ease_factor": 2.5, "interval": 0, "repetitions": 0}

def validate_card(card:dict) -> bool:
    return all(k in card for k in REQUIRED_CARD_KEYS)

def migrate_card(card:dict) -> dict:
    for k, v in CARD_DEFAULTS.items():
        if k not in card:
            card[k] = v
    return card

def migrate_file(sko_contents:dict) -> dict:
    for set_cards in sko_contents.values():
        for i, card in enumerate(set_cards):
            set_cards[i] = migrate_card(card)
    return sko_contents
