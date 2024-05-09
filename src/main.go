// FUA
	// mimick most to all monkeytype features
	// basic keyboard and punctuation and number inputs, escape escapes the game
	// use a stack for each of the letters, the stack is cleared when a word is correctly entered
	// use a queue for words that need to be cleared?
	// highscore with past WPM and player name as needed
	// see if i can still get an audio driver in?
	// have proper code seperation and ideally functional programming paradigms would be good
	// add crunchy typing audio like a typewriter perhaps?

package main

import (
    "fmt"
	"github.com/gongahkia/monke/lib/generator"
	// "os"
	// "log"
)

func main() {

	// --- variable initialization ---

	var words []string
	var wordsError error

	// --- main code execution ---

	fmt.Println("monke")

	/*
	--- testing out the api calls --- 
	fmt.Println(generator.GenerateWords(10))
	fmt.Println(generator.GenerateSentences(2))
	*/

	words, wordsError = generator.GenerateWords(10)
	fmt.Println(words) // arrays are printed without commas
	fmt.Println(wordsError)

}