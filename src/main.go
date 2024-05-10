// fua
	// work out why the drawtitlescren is not showing, perhaps need to read user input first
	// add final selection options here for type words or sentences

package main

import (
	"fmt"
	"strings"
	"github.com/gongahkia/monke/lib/graphics"
	"github.com/gongahkia/monke/lib/event"
	"github.com/gongahkia/monke/lib/utils"
)

func main() {

	utils.ClearScreen()
	graphics.DrawTitleScreen()

	var userInput string

	fmt.Print("\n\n[W]ords\n")
	fmt.Print("[S]entences\n")
	fmt.Print("[ESC]ape to leave\n\n")
    fmt.Scanln(&userInput)
	if strings.Trim(userInput, " ") == "w" {

		var totalNumWords int
		var timeLimitSeconds int
		var overallWordWPM float64
		timeLimitSeconds = 40
		totalNumWords = 100

		wordsE := event.MonkeTypeWords(timeLimitSeconds, totalNumWords)
		overallWordWPM = (float64(wordsE)/float64(timeLimitSeconds)) * 60
		graphics.DisplayWPM(overallWordWPM)

	} else if strings.Trim(userInput, " ") == "s" {

		var totalNumSentences int
		var timeLimitSeconds int
		var overallWordWPM float64
		timeLimitSeconds = 40
		totalNumSentences = 100

		sentencesE := event.MonkeTypeSentences(timeLimitSeconds, totalNumSentences)
		overallWordWPM = (float64(sentencesE)/float64(timeLimitSeconds)) * 60
		graphics.DisplayWPM(overallWordWPM)

	} else {

		utils.ClearScreen()
		fmt.Println("Unrecognised input.")

	}

}
