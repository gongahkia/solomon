from __future__ import annotations

import os

import cards as cards_app
from cli_support import deck_name, find_card, load_managed_deck, require_set, save_managed_deck
from deck_ops import duplicate_card, move_card, parse_tags, reorder_card, toggle_suspend
from schema import new_card, reset_card_progress, touch_card
from storage import ensure_config_dir, sko_path, write_sko


def cmd_create_deck(args, config: dict) -> int:
    ensure_config_dir()
    managed_name = deck_name(args.deck)
    if os.path.exists(sko_path(managed_name)) and not args.force:
        raise ValueError(f"Deck already exists: {managed_name}")
    write_sko(managed_name, {}, config)
    print(f"Created deck {managed_name}")
    return 0


def cmd_delete_deck(args, config: dict) -> int:
    managed_name = deck_name(args.deck)
    path = sko_path(managed_name)
    if not os.path.exists(path):
        raise ValueError(f"Deck not found: {managed_name}")
    if not args.force:
        raise ValueError("Use --force to delete a deck from disk.")
    os.remove(path)
    print(f"Deleted deck {managed_name}")
    return 0


def cmd_create_set(args, config: dict) -> int:
    managed_name, sets = load_managed_deck(args.deck, config)
    if args.set_name in sets and not args.force:
        raise ValueError(f"Set already exists: {args.set_name}")
    sets.setdefault(args.set_name, [])
    save_managed_deck(managed_name, sets, config)
    print(f"Created set {args.set_name} in {managed_name}")
    return 0


def cmd_rename_set(args, config: dict) -> int:
    managed_name, sets = load_managed_deck(args.deck, config)
    cards = require_set(sets, args.set_name)
    if args.new_name in sets:
        raise ValueError(f"Set already exists: {args.new_name}")
    sets[args.new_name] = cards
    del sets[args.set_name]
    save_managed_deck(managed_name, sets, config)
    print(f"Renamed {args.set_name} to {args.new_name}")
    return 0


def cmd_delete_set(args, config: dict) -> int:
    managed_name, sets = load_managed_deck(args.deck, config)
    cards = require_set(sets, args.set_name)
    if cards and not args.force:
        raise ValueError("Set is not empty; use --force to delete it.")
    del sets[args.set_name]
    save_managed_deck(managed_name, sets, config)
    print(f"Deleted set {args.set_name} from {managed_name}")
    return 0


def cmd_add_card(args, config: dict) -> int:
    managed_name, sets = load_managed_deck(args.deck, config)
    sets.setdefault(args.set_name, [])
    card = new_card(
        card_name=args.name,
        card_info=args.info or "",
        card_add_info=args.notes or "",
        tags=parse_tags(args.tags or ""),
        config=config,
    )
    sets[args.set_name].append(card)
    save_managed_deck(managed_name, sets, config)
    print(f"Added card {card['id']} to {managed_name}:{args.set_name}")
    return 0


def cmd_edit_card(args, config: dict) -> int:
    managed_name, sets = load_managed_deck(args.deck, config)
    cards = require_set(sets, args.set_name)
    _, card = find_card(cards, args.card)
    changed = False
    if args.name is not None:
        if not args.name.strip():
            raise ValueError("Card name cannot be empty.")
        card["card_name"] = args.name
        changed = True
    if args.info is not None or args.clear_info:
        card["card_info"] = "" if args.clear_info else args.info
        changed = True
    if args.notes is not None or args.clear_notes:
        card["card_add_info"] = "" if args.clear_notes else args.notes
        changed = True
    if args.tags is not None or args.clear_tags:
        card["tags"] = [] if args.clear_tags else parse_tags(args.tags)
        changed = True
    if not changed:
        raise ValueError("No card updates were provided.")
    touch_card(card)
    save_managed_deck(managed_name, sets, config)
    print(f"Updated {card.get('card_name')}")
    return 0


def cmd_duplicate_card(args, config: dict) -> int:
    managed_name, sets = load_managed_deck(args.deck, config)
    cards = require_set(sets, args.set_name)
    index, card = find_card(cards, args.card)
    target_set = args.target_set or args.set_name
    sets.setdefault(target_set, [])
    cloned = duplicate_card(card, config)
    if target_set == args.set_name:
        cards.insert(index + 1, cloned)
    else:
        sets[target_set].append(cloned)
    save_managed_deck(managed_name, sets, config)
    print(f"Duplicated {card.get('card_name')} into {target_set}")
    return 0


def cmd_delete_card(args, config: dict) -> int:
    managed_name, sets = load_managed_deck(args.deck, config)
    cards = require_set(sets, args.set_name)
    index, card = find_card(cards, args.card)
    del cards[index]
    save_managed_deck(managed_name, sets, config)
    print(f"Deleted {card.get('card_name')}")
    return 0


def cmd_move_card(args, config: dict) -> int:
    managed_name, sets = load_managed_deck(args.deck, config)
    cards = require_set(sets, args.source_set)
    sets.setdefault(args.target_set, [])
    index, card = find_card(cards, args.card)
    move_card(sets, args.source_set, index, args.target_set)
    save_managed_deck(managed_name, sets, config)
    print(f"Moved {card.get('card_name')} to {args.target_set}")
    return 0


def cmd_reorder_card(args, config: dict) -> int:
    managed_name, sets = load_managed_deck(args.deck, config)
    cards = require_set(sets, args.set_name)
    index, card = find_card(cards, args.card)
    direction = -1 if args.direction == "up" else 1
    for _ in range(max(1, args.steps)):
        next_index = reorder_card(cards, index, direction)
        if next_index == index:
            break
        index = next_index
    save_managed_deck(managed_name, sets, config)
    print(f"Moved {card.get('card_name')} to position {index + 1} in {args.set_name}")
    return 0


def cmd_suspend_card(args, config: dict) -> int:
    managed_name, sets = load_managed_deck(args.deck, config)
    cards = require_set(sets, args.set_name)
    _, card = find_card(cards, args.card)
    desired = not args.resume
    if card.get("suspended") != desired:
        toggle_suspend(card)
    save_managed_deck(managed_name, sets, config)
    state = "resumed" if args.resume else "suspended"
    print(f"{state.capitalize()} {card.get('card_name')}")
    return 0


def cmd_reset_card(args, config: dict) -> int:
    managed_name, sets = load_managed_deck(args.deck, config)
    cards = require_set(sets, args.set_name)
    _, card = find_card(cards, args.card)
    reset_card_progress(card, config)
    save_managed_deck(managed_name, sets, config)
    print(f"Reset progress for {card.get('card_name')}")
    return 0


def cmd_review(args, config: dict) -> int:
    review_argv = [args.deck]
    if args.set_name:
        review_argv.extend(["--set", args.set_name])
    if args.due_only:
        review_argv.append("--due-only")
    if args.record_progress:
        review_argv.append("--record-progress")
    return cards_app.main(review_argv)
