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
	"time"
	"github.com/gongahkia/monke/lib/generator"
	"github.com/eiannone/keyboard"
	// "os"
	// "log"
)

func main() {

	// --- variable initialization ---

	var userInputBuffer string
	var words []string
	var wordsError error

	// --- value assignment ---

	userInputBuffer = ""

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

	stopCh := make(chan bool) // creates a channel to communicate with the goroutine

	go func() { // begins the user input goroutine
		for {
			char, key, err := keyboard.GetSingleKey()
			if err != nil { // error hit
				fmt.Println("Error reading input:", err)
				stopCh <- true // signal the main loop to stop
				return
			}
			if key == keyboard.KeyEsc { // user presses escape to quit game
				fmt.Println("\nMonke exiting...")
				stopCh <- true // signal the main loop to stop
				return
			} else if key == 127 { // 127 is the universal ansi key code for backspace
				if len(userInputBuffer) > 0 {
					userInputBuffer = userInputBuffer[:len(userInputBuffer)-1]
				}
				fmt.Print("\033[H\033[2J") // ansi escape code to clear screen
				fmt.Print(userInputBuffer) 
			} else if key == keyboard.KeySpace {
				userInputBuffer += " "
				fmt.Print("\033[H\033[2J") // ansi escape code to clear screen
				fmt.Print(userInputBuffer) 
			} else {
				userInputBuffer += string(char)
				fmt.Print("\033[H\033[2J") // ansi escape code to clear screen
				fmt.Print(userInputBuffer) 
			}
		}
	}()

	// --- update loop that runs every 2 seconds ---

	// numIteration := 0

	for {
		select {
		case <-stopCh:
			return // exit the program
		default:
			// numIteration++ 
			// fmt.Println("\nLoop is running for", numIteration, "seconds...")
			time.Sleep(1 * time.Second) // delay that effectively restricts the program to running every 2 seconds
		}
	}

}