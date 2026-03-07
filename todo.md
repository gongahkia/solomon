# Senko Evolution — todo.md

> Generated from full codebase audit. Tasks ordered by dependency.
> Priority: `(A)` unblocks other tasks or fixes active defects, `(B)` audit-suggested improvement, `(C)` low-risk polish.

---

## Integration

### Task 30 (B) +feature | Philosophical Alignment

**PURPOSE** — After selecting a file, users need a unified deck management screen to review, add, edit, and delete cards without returning to the main menu each time. This is the central workflow hub.

**WHAT TO DO**
1. In `src/main.py`, add `deck_screen(stdscr, filename: str, config: dict)` that:
   - Calls `read_sko(filename)`, applies `migrate_file()` from `src/schema.py`.
   - Opens `set_browser(stdscr, filename, sko_contents)` (Task 18) to select a set.
   - If set selected, shows a set action menu via `select_from_list()` with items: `["Review", "Add cards", "Edit cards", "Delete cards", "Back to sets"]`.
   - Dispatches to `review_session()`, `add_card_screen()`, `edit_card_screen()`, `delete_card_screen()` respectively, passing `config` where needed.
   - After each action, updates `sko_contents` with the returned cards list via `update_sko_allsets()`, writes via `write_sko(filename, sko_contents)`, returns to the set action menu.
   - "Back to sets" returns to `set_browser()`. `None` from set browser returns to caller.
2. Wire into main menu (Task 16): "Browse decks" -> `file_browser()` -> if file selected -> `deck_screen()`.
3. Wire "Review cards" in main menu as a shortcut: `file_browser()` -> select file -> `set_browser()` -> select set -> go directly to `review_session()`.

**DONE WHEN**
- [ ] Selecting a file, then a set, then an action works end-to-end without crashes.
- [ ] Changes from review/add/edit/delete are persisted to the `.sko` file before returning to the set action menu.
- [ ] "Back to sets" returns to set browser without re-reading the file from disk.
- [ ] Schema migration runs automatically when a file is opened.
- [ ] Quitting from set browser returns to the main menu.

---

### Task 31 (C) +infra | Stability/Scaling

**PURPOSE** — `src/eg.sko` must demonstrate the correct schema including SM-2 fields. With validation (Task 10) active, the current file with `{}` in set_4 and missing SM-2 fields would be rejected.

**WHAT TO DO**
1. In `src/eg.sko`, replace set_4 contents from `[{}]` to `[]`.
2. Add `"ease_factor": 2.5, "interval": 0, "repetitions": 0` to every card in set_1 (3 cards), `you_can_call_a_set_whatever_you_want` (2 cards), and set_3 (1 card).
3. For the card with `"card_add_info": null` in `you_can_call_a_set_whatever_you_want`, change `null` to `""` (empty string) to match expected schema type.

**DONE WHEN**
- [ ] `json.loads(open("src/eg.sko").read())` produces no errors.
- [ ] Every card dict has exactly 7 keys: `card_name`, `card_info`, `card_add_info`, `card_date`, `ease_factor`, `interval`, `repetitions`.
- [ ] No card dict is empty.
- [ ] No field values are `null`/`None`.
