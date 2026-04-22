# Card Generation Prompt

Senko has no built-in card generator. Paste one of the prompts below into any LLM (Claude, GPT, Gemini, etc.) to produce a file that imports cleanly via `senko import` / `senko review` or the TUI file picker.

Senko now supports two formats: `.sko` (native JSON schema v3) and `.csv`. TXT is no longer supported.

- **`.sko`** — recommended. Carries full SRS metadata, tags as a real array, and passes `senko validate` directly.
- **`.csv`** — convenient for hand-editing in spreadsheets; mapped through `infer_csv_mapping` on import.

## Rich Content Support (TUI + CLI Review)

Senko supports rich card content in `card_name`, `card_info`, and `card_add_info`.

- **Code blocks / syntax highlighting**
  - Use fenced code blocks: ```` ```java ... ``` ```` for Java (or plain fences for generic code).
  - Unfenced Java-like snippets are also auto-detected, but fenced blocks are preferred for consistency.
- **LaTeX-style math formatting**
  - Inline math: `$...$` or `\(...\)`.
  - Block math: `$$...$$`.
  - Rendering is terminal-friendly text formatting (not full TeX layout).
- **Image URLs**
  - Use Markdown image syntax: `![Alt text](https://.../image.png)` or a direct image URL on its own line.
  - Auto-size uses user config (`tui.image_width`, `tui.image_height`).
  - In supported terminals (Ghostty/kitty protocol), Senko renders native inline images; otherwise it falls back to ASCII preview.
  - Non-fatal image warnings are hidden by default (`tui.show_image_warnings=false`).

## Instructions

1. Pick the format you want (`.sko` or `.csv`).
2. Replace `<TOPIC>`, `<NUM_CARDS>`, `<DECK_NAME>`, `<SET_NAME>`, and `<DOMAIN_NOTES>` inline.
3. Save the LLM output verbatim with the matching extension.
4. Import:
   - TUI: launch `senko`, choose the file in the picker.
   - CLI: `senko import <DECK_NAME> path/to/file.{sko,csv}`.

## Prompt A — `.sko` (JSON schema v3)

````text
You are generating flashcards for Senko, a CLI spaced-repetition app. Produce ONLY the file contents as valid JSON matching Senko schema version 3. No prose, no markdown fences, no commentary before or after. The file must parse with `json.load` and pass `senko validate`.

INPUTS
- Topic: <TOPIC>
- Number of cards: <NUM_CARDS>
- Deck name (informational only): <DECK_NAME>
- Set name (MUST match exactly in the `sets` key): <SET_NAME>
- Domain notes: <DOMAIN_NOTES>

GLOBAL RULES
- Every card is atomic: ONE fact, term, or concept per card. Split compound facts.
- `card_name` = prompt/front (term, question, or cue). Keep it short.
- `card_info` = answer/back (definition, translation, explanation). One-liner preferred.
- `card_add_info` = optional hint/mnemonic/example/source. May be "".
- Rich formatting is allowed inside `card_name`, `card_info`, and `card_add_info`:
  - Java/code: fenced blocks with language labels when possible.
  - Math: inline `$...$` or block `$$...$$`.
  - Images: `![Alt](https://...)` or direct image URL line.
- `tags` = JSON array of 0–5 lowercase strings, hyphen-or-underscore-joined.
- No duplicate `card_name` values within the set.
- `id` is a unique string per card: "1", "2", ... through "<NUM_CARDS>".
- UTF-8. No smart quotes unless semantically required.
- Leave all SRS fields at the defaults shown in the skeleton. Do NOT invent review history.
- `card_date` = "" for new cards.
- `created_at` and `updated_at` = ISO 8601 seconds precision, identical per card, today's UTC date acceptable.

SCHEMA SKELETON (emit this shape exactly, populated with <NUM_CARDS> card objects)

{
  "_schema_version": 3,
  "sets": {
    "<SET_NAME>": [
      {
        "id": "1",
        "card_name": "",
        "card_info": "",
        "card_add_info": "",
        "card_date": "",
        "ease_factor": 2.5,
        "interval": 0,
        "repetitions": 0,
        "suspended": false,
        "tags": [],
        "created_at": "2026-04-15T00:00:00",
        "updated_at": "2026-04-15T00:00:00",
        "state": "new",
        "step_index": 0,
        "lapses": 0,
        "again_count": 0,
        "hard_count": 0,
        "good_count": 0,
        "easy_count": 0
      }
    ]
  }
}

QUALITY BAR
- Prefer minimal-pair / cloze-style phrasing where useful (e.g. "__ is the capital of France" -> "Paris").
- Language decks: `card_name` = target-language term; `card_info` = translation; `card_add_info` = transliteration or example sentence.
- Concept decks: `card_name` = question; `card_info` = concise answer; `card_add_info` = rationale or formula.
- Avoid cards whose answer appears inside the prompt.
- Avoid yes/no cards unless the discrimination is the point.

OUTPUT
Return ONLY the JSON object. Nothing else.
````

## Prompt B — `.csv`

````text
You are generating flashcards for Senko, a CLI spaced-repetition app. Produce ONLY valid CSV content. No prose, no markdown fences, no commentary before or after. The file must parse with Python's `csv.DictReader` and pass Senko's `import_from_csv`.

INPUTS
- Topic: <TOPIC>
- Number of cards: <NUM_CARDS>
- Deck name (informational only): <DECK_NAME>
- Set name (MUST appear verbatim in the `set_name` column of every row): <SET_NAME>
- Domain notes: <DOMAIN_NOTES>

HEADER ROW (emit exactly this, in this order)
set_name,card_name,card_info,card_add_info,card_date,tags,suspended,ease_factor,interval,repetitions

ROW RULES
- Emit <NUM_CARDS> data rows.
- `set_name` = <SET_NAME> on every row.
- `card_name` = prompt/front. Required, non-empty, unique within the set.
- `card_info` = answer/back. Required.
- `card_add_info` = optional hint/mnemonic/example. May be empty.
- Rich formatting is allowed in `card_name`, `card_info`, and `card_add_info`:
  - code fences (for example ` ```java ... ``` `),
  - inline math `$...$` / `\(...\)`,
  - block math `$$...$$`,
  - image URLs via `![Alt](https://...)` or direct image URL line.
- If a field contains newlines (for code fences or block math), wrap it in CSV quotes and preserve the newlines.
- `card_date` = leave empty (Senko treats blank as "new, due now").
- `tags` = 0–5 lowercase labels separated by semicolons (`verb;common`). Do NOT use commas inside tags — they will break CSV parsing. Leave empty if none.
- `suspended` = `false` for every generated card.
- `ease_factor`, `interval`, `repetitions` = leave empty to accept Senko defaults (2.5, 0, 0). Do NOT invent review history.
- Quote any field that contains a comma, double-quote, or newline using RFC 4180 double quoting (`"he said ""hi"""`).
- UTF-8 encoding. One row per line, Unix line endings.

CONTENT QUALITY BAR
- Every card is atomic: ONE fact, term, or concept per card.
- Prefer minimal-pair / cloze-style phrasing where useful.
- Language decks: `card_name` = target-language term; `card_info` = translation; `card_add_info` = transliteration or example.
- Concept decks: `card_name` = question; `card_info` = concise answer; `card_add_info` = rationale or formula.
- Avoid cards whose answer appears inside the prompt.
- Avoid yes/no cards unless the discrimination is the point.
- When generating programming/math decks, prefer rich formatting that matches the content:
  - code questions include executable snippets or short blocks
  - formula cards use inline or block math tokens
  - diagram cards include a stable image URL in `card_add_info`

OUTPUT
Return ONLY the CSV text (header row plus <NUM_CARDS> data rows). Nothing else.
````

## Verify before import

```console
$ senko validate
$ senko import <DECK_NAME> file.sko
$ senko import <DECK_NAME> file.csv
```

Invalid files surface with an error in the TUI file picker; fix and retry.
