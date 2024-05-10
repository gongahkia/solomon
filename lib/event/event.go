// fua
	// use the graphics functions later to display all items and sentences to the screen as opposed to fmt print
	// show CURRENT WPM as user typing and update when there's a change in wpm 
	// function should return an OVERALL WPM as an int also

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

func MonkeTypeWords(totalTimeLimit int, totalNumWords int){

	utils.ClearScreen()

	// --- variable initialization ---

	var userInputBuffer string
	var words []string
	var wordsError error
	var completedNumWords int

	// --- value assignment ---

	userInputBuffer = ""
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

				if completedNumWords == totalNumWords { // if user finishes typing all words
					fmt.Println("\n", completedNumWords, "/", totalNumWords, "words typed...")
					fmt.Println("\nYou have finished typing all the words!")
					fmt.Println("\nMonke exiting...")
					stopCh <- true // signal the main loop to stop
					return
				}

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
					fmt.Println("\n", completedNumWords, "/", totalNumWords, "words typed...")
					return
				}
				// fmt.Println("\nLoop is running for", numIteration, "seconds...")
				time.Sleep(1 * time.Second) // delay that effectively restricts the program to running every 2 seconds
				numIteration++ 
		}
	}

}

func MonkeTypeSentences(totalTimeLimit int, totalNumSentences int){

	utils.ClearScreen()

	// --- variable initialization ---

	var userInputBuffer string
	var sentences []string
	var sentencesError error
	var completedNumSentences int

	// --- value assignment ---

	userInputBuffer = ""
	completedNumSentences = 0

	// --- generating words ---

	sentences, sentencesError = generator.GenerateSentences(totalNumSentences)

    if sentencesError != nil {
        fmt.Println("Monke hit an error when generating sentences:", sentencesError)
    } else {
        fmt.Println(sentences) // arrays are printed without commas
    }

	// --- main code execution ---

	stopCh := make(chan bool) // creates a channel to communicate with the goroutine

	go func() { // begins the goroutine

		for {

			// --- variable initialization within loop ---

			var currentSentence string
			currentSentence = sentences[0]

			// --- user input validation ---

			char, key, err := keyboard.GetSingleKey()
			if err != nil { // error hit
				fmt.Println("Error reading input:", err)
				stopCh <- true // signal the main loop to stop
				return
			}

			// --- reading user input ---

			if key == keyboard.KeyEsc { // user presses escape to quit game
                fmt.Println("\n", completedNumSentences, "/", totalNumSentences, "sentences typed...")
				fmt.Println("\nMonke exiting...")
				stopCh <- true // signal the main loop to stop
				return
			} else if key == 127 { // 127 is the universal ansi key code for backspace
				if len(userInputBuffer) > 0 {
					userInputBuffer = userInputBuffer[:len(userInputBuffer)-1]
				}
				utils.ClearScreen()
				fmt.Print(userInputBuffer) 
				fmt.Print(currentSentence)
			} else if key == keyboard.KeySpace {
				userInputBuffer += " "
				utils.ClearScreen()
				fmt.Print(userInputBuffer) 
				fmt.Print(currentSentence)
			} else {
				userInputBuffer += string(char)
				utils.ClearScreen()
				fmt.Print(userInputBuffer) 
				fmt.Print(currentSentence)
			}

			// --- check userInputBuffer against sentence queue---

			if len(userInputBuffer) >= len(sentences[0]) && sentences[0] == userInputBuffer[:len(sentences[0])]{ // sentence is correctly typed
				userInputBuffer = userInputBuffer[len(sentences[0]):] // clears typed sentence from userInputBuffer
			 	sentences = sentences[1:] // remove word from word queue
			 	completedNumSentences++ // add to total score

				if completedNumSentences == totalNumSentences { // if user finishes typing all sentences
					fmt.Println("\n", completedNumSentences, "/", totalNumSentences, "sentences typed...")
					fmt.Println("\nYou have finished typing all the sentences!")
					fmt.Println("\nMonke exiting...")
					stopCh <- true // signal the main loop to stop
					return
				}

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
					fmt.Println("\n", completedNumSentences, "/", totalNumSentences, "sentences typed...")
					return
				}
				// fmt.Println("\nLoop is running for", numIteration, "seconds...")
				time.Sleep(1 * time.Second) // delay that effectively restricts the program to running every 2 seconds
				numIteration++ 
		}
	}

}