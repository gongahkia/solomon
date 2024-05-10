// fua
	// add event loop for sentences
	// use the graphics functions later to display to the screen as opposed to fmt print
	// mimick most to all monkeytype features
		// track and calculate wpm (update wpm when there's a change)
		// check correct words

package event

import (
    "fmt"
	"time"
	"github.com/gongahkia/monke/lib/generator"
	"github.com/gongahkia/monke/lib/utils"
	"github.com/eiannone/keyboard"
	// "os"
	// "log"
)

func MonkeTypeWords(){

	utils.ClearScreen()

	// --- variable initialization ---

	var userInputBuffer string
	var words []string
	var wordsError error
	var totalTimeLimit int
	var totalNumWords int
	var completedNumWords int

	// --- value assignment ---

	userInputBuffer = ""
	totalTimeLimit = 60
	totalNumWords = 50
	completedNumWords = 0

	// --- generating words ---

	words, wordsError = generator.GenerateWords(totalNumWords)

    if wordsError != nil {
        fmt.Println("Monke hit an error when generating words:", wordsError)
    } else {
        fmt.Println(words) // arrays are printed without commas
    }

	// --- main code execution ---

	stopCh := make(chan bool) // creates a channel to communicate with the goroutine

	go func() { // begins the goroutine

		for {

			// --- variable initialization within loop ---

			var currentAndUpcomingNextWord []string
			currentAndUpcomingNextWord = words[:2]

			// --- user input validation ---

			char, key, err := keyboard.GetSingleKey()
			if err != nil { // error hit
				fmt.Println("Error reading input:", err)
				stopCh <- true // signal the main loop to stop
				return
			}

			// --- reading user input ---

			if key == keyboard.KeyEsc { // user presses escape to quit game
                fmt.Println("\n", completedNumWords, "/", totalNumWords, "words typed...")
				fmt.Println("\nMonke exiting...")
				stopCh <- true // signal the main loop to stop
				return
			} else if key == 127 { // 127 is the universal ansi key code for backspace
				if len(userInputBuffer) > 0 {
					userInputBuffer = userInputBuffer[:len(userInputBuffer)-1]
				}
				utils.ClearScreen()
				fmt.Print(userInputBuffer) 
				fmt.Print(currentAndUpcomingNextWord)
			} else if key == keyboard.KeySpace {
				userInputBuffer += " "
				utils.ClearScreen()
				fmt.Print(userInputBuffer) 
				fmt.Print(currentAndUpcomingNextWord)
			} else {
				userInputBuffer += string(char)
				utils.ClearScreen()
				fmt.Print(userInputBuffer) 
				fmt.Print(currentAndUpcomingNextWord)
			}

			// --- check userInputBuffer against words queue---

			if len(userInputBuffer) >= len(words[0]) && words[0] == userInputBuffer[:len(words[0])]{ // word is correctly typed
				userInputBuffer = userInputBuffer[len(words[0]):] // clears word from userInputBuffer
			 	words = words[1:] // remove word from word queue
			 	completedNumWords++ // add to total score
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
				if numIteration == totalTimeLimit { // exit the program when time limit reached
					keyboard.Close() // close the keyboard input and restore terminal to normal mode
					fmt.Println("\ntime limit of", totalTimeLimit, "seconds reached, exiting...")
					fmt.Println("\n", completedNumWords, "words typed...")
					return
				}
				// fmt.Println("\nLoop is running for", numIteration, "seconds...")
				time.Sleep(1 * time.Second) // delay that effectively restricts the program to running every 2 seconds
				numIteration++ 
		}
	}

}

func MonkeTypeSentences(){
	// fua add code here
}