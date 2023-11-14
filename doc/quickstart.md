# 閃光 is flash in japanese

Senko is a flashcard program for the CLI. It relies on a [spaced repition system](https://e-student.org/spaced-repetition/) to make concepts stick, similar to [anki](https://ankiweb.net/about). 

## usage

* run through flashcards
* add flashcards
* edit existing cards

Senko config files are stored in `.sko` files, which leached on `.json` for utility.

Senko files follow the below structure. 

* One senko file can contain multiple flashcard sets. 
* Each set contains one or more flashcards.
* Each flashcard has the fields `card_name`, `card_info`, `card_add_info` and `card_challenge`.
    * `card_name`: string; editable by user at sko file instantiation and through editing cards
    * `card_info`: string; editable by user at sko file instantiation and through editing cards
    * `card_add_info`: string; editable by user at sko file instantiation and through editing cards
    * `card_challenge`: int; editable by user at sko file instntiation and not editable after; represents the number of days between card recurring in user's pool

```txt
{
    "set_1": [
        {
            "card_name": "",
            "card_info": "",
            "card_add_info": "",
            "card_challenge": 0
        },
        {
            etc...
        }
    ],

    "set_2": [
        etc...
    ]
}
```

An example Senko file.

```json
{   
    "russian_core_2k": [
        {
            "card_name": "становиться",
            "card_info": "stanovit'sya",
            "card_add_info": "become",
            "card_challenge": 1
        },
        {
            "card_name": "Спасибо",
            "card_info": "Spasibo",
            "card_add_info": "thank you",
            "card_challenge": 0
        }
    ],

    "japanese_core_2k": [
        {
            "card_name": "なる",
            "card_info": "na ru",
            "card_add_info": "become",
            "card_challenge": 5
        },
        {
            "card_name": "ありがとう",
            "card_info": "a ri ga tou",
            "card_add_info": "thank you",
            "card_challenge": 2
        }
    ]
}
```

