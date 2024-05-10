package utils

import (
    "fmt"
    "strings"
)

func ClearScreen(){
    fmt.Print("\033[H\033[2J") // ansi escape code to clear screen
}

func NumberCorrectWordsInIncompleteSentence(userInputBuffer string, sentences []string) int { // called after the sentences and user input buffer has been cleared of previous entry
    count := 0
    for index, word := range strings.Split(strings.Trim(userInputBuffer, " "), " ") {
        if word == strings.Split(sentences[0], " ")[index] {
            count++
        }
    }
    return count
}

func TotalNumWords(sentences []string) int {
    finCount := 0
    for _, sentence := range sentences {
        finCount += len(strings.Split(sentence, " "))
    }
    return finCount
}