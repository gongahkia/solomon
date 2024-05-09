// FUA
    // work out project structure from scratch in the cli without using ebiten
	// call an api that provides random words to be typed out
	// mimick most to all monkeytype features
	// basic keyboard and punctuation and number inputs, escape escapes the game
	// use a stack for each of the letters, the stack is cleared when a word is correctly entered
	// use a queue for words that need to be cleared?
	// highscore with past WPM and player name as needed
	// see if i can still get an audio driver in?
	// add crunchy typing audio like a typewriter perhaps?
	// have proper code seperation

package main

import (
    "fmt"
	"github.com/gongahkia/monke/lib/generator"
	// "os"
	// "log"
)

func main() {

	// --- main code execution ---

	fmt.Println("monke")
	generator.generateSentences(4)

}