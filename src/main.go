// FUA
	// mimick most to all monkeytype features
		// track and calculate wpm (update wpm when there's a change)
		// check correct words
	// basic keyboard and punctuation and number inputs, escape escapes the game
	// use a stack for each of the letters, the stack is cleared when a word is correctly entered
	// use a queue for words that need to be cleared?
	// highscore with past WPM and player name as needed
	// see if i can still get an audio driver in?
	// have proper code seperation and ideally functional programming paradigms would be good
	// add crunchy typing audio like a typewriter perhaps?
	// generalise current game loop to apply for sentences also

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

	fmt.Println("monke")

	// --- variable initialization ---

	var userInputBuffer string
	var words []string
	var wordsError error
	var timeLimit int

	// --- value assignment ---

	userInputBuffer = ""
	timeLimit = 10

	/*
	--- testing out the api calls --- 
	fmt.Println(generator.GenerateWords(10))
	fmt.Println(generator.GenerateSentences(2))
	*/

	// --- generating words / sentences ---

	words, wordsError = generator.GenerateWords(10)
	fmt.Println(words) // arrays are printed without commas
	fmt.Println(wordsError)

	// --- main code execution ---

	stopCh := make(chan bool) // creates a channel to communicate with the goroutine

	go func() { // begins the goroutine

		for {

			// --- user input validation ---

			char, key, err := keyboard.GetSingleKey()
			if err != nil { // error hit
				fmt.Println("Error reading input:", err)
				stopCh <- true // signal the main loop to stop
				return
			}

			// --- reading user input ---

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
				fmt.Print(words)
			} else if key == keyboard.KeySpace {
				userInputBuffer += " "
				fmt.Print("\033[H\033[2J") // ansi escape code to clear screen
				fmt.Print(userInputBuffer) 
				fmt.Print(words)
			} else {
				userInputBuffer += string(char)
				fmt.Print("\033[H\033[2J") // ansi escape code to clear screen
				fmt.Print(userInputBuffer) 
				fmt.Print(words)
			}

			// --- check userInputBuffer against words queue---

			if len(userInputBuffer) >= len(words[0]) && words[0] == userInputBuffer[:len(words[0])]{ // word is correctly typed
				userInputBuffer = userInputBuffer[len(words[0]):] // clears word from userInputBuffer
			 	words = words[1:] // remove word from word queue
			}

		}

	}()

	// --- update loop that runs every 2 seconds ---

	numIteration := 0

	for {
		select {
			case <-stopCh:
				keyboard.Close() // close the keyboard input and restore terminal to normal mode
				return // exit the program when goroutine terminated
			default:
				if numIteration == timeLimit { // exit the program when time limit reached
					keyboard.Close() // close the keyboard input and restore terminal to normal mode
					fmt.Println("\ntime limit of", timeLimit, "seconds reached, exiting...")
					return
				}
				// fmt.Println("\nLoop is running for", numIteration, "seconds...")
				time.Sleep(1 * time.Second) // delay that effectively restricts the program to running every 2 seconds
				numIteration++ 
		}
	}

}