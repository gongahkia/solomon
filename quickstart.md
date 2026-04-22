# `閃光` is flash in japanese

`Senko` is a flashcard program for the CLI. It relies on a [spaced repetition system](https://e-student.org/spaced-repetition/) to make concepts stick, similar to [anki](https://ankiweb.net/about). 

## Schema

`Senko` config files are stored in versioned `.sko` files that use JSON under the hood.

`Senko` files follow the below structure. 

* One senko file can contain multiple flashcard sets. 
* Each set contains one or more flashcards.
* Each flashcard has the fields `id`, `card_name`, `card_info`, `card_add_info`, `card_date`, `ease_factor`, `interval`, `repetitions`, `suspended`, `tags`, `created_at`, `updated_at`, `state`, `step_index`, `lapses`, `again_count`, `hard_count`, `good_count` and `easy_count`
* Legacy decks are migrated automatically when Senko loads them
* `card_name`: str; editable by user at sko file instantiation and through editing cards
* `card_info`: str; editable by user at sko file instantiation and through editing cards
* `card_add_info`: str; editable by user at sko file instantiation and through editing cards
* `card_date`: str; represents the next date for the card to be reviewed
* `suspended`: bool; when true the card is hidden from normal due review
* `tags`: list[str]; optional metadata for filtering and export
* Senko files with invalid structure are surfaced in the file picker with an error message

```txt
{
    "_schema_version": 3,
    "sets": {
        "set_1": [
            {
                "id": "",
                "card_name": "",
                "card_info": "",
                "card_add_info": "",
                "card_date": "",
                "ease_factor": 2.5,
                "interval": 0,
                "repetitions": 0,
                "suspended": false,
                "tags": [],
                "created_at": "",
                "updated_at": "",
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
```

## Example `.sko` file

```json
{
    "_schema_version": 3,
    "sets": {
        "russian_core_2k": [
            {
                "id": "1",
                "card_name": "становиться",
                "card_info": "stanovit'sya",
                "card_add_info": "become",
                "card_date": "20/01/2023",
                "ease_factor": 2.5,
                "interval": 0,
                "repetitions": 0,
                "suspended": false,
                "tags": [
                    "verb"
                ],
                "created_at": "2026-03-14T09:00:00",
                "updated_at": "2026-03-14T09:00:00",
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
```

## Example `Senko` CLI commands

```console
$ senko validate
$ senko create-deck japanese
$ senko create-set japanese core_2k
$ senko add-card japanese core_2k --name "ありがとう" --info "thank you" --tags greeting
$ senko edit-card japanese core_2k "ありがとう" --notes "formal enough for most situations"
$ senko duplicate-card japanese core_2k "ありがとう"
$ senko reorder-card japanese core_2k "ありがとう (copy)" up
$ senko move-card japanese core_2k review "ありがとう"
$ senko review japanese --set review --record-progress
$ senko suspend-card japanese review "ありがとう"
$ senko reset-card japanese review "ありがとう"
$ senko export-history ~/Desktop/japanese-history.json --deck japanese --format json
$ senko archive-history ~/Desktop/japanese-history.jsonl --deck japanese
$ senko stats --deck japanese
$ senko export japanese --format csv --output ~/Desktop/japanese.csv
$ senko review japanese --due-only --record-progress
$ senko review ~/Desktop/external_cards.csv --due-only
```
