// fua
	// work out why the drawtitlescren is not showing, perhaps need to read user input first
	// add final selection options here for type words or sentences
	// abstract highscore logic here? see if functions under event should return anything
		// highscore with past WPM and player name as needed
	// work on how to edit the sentence function to caluclate wpm by calculating length of each sentence
		// need to write an additional function that checks the unfinished sentence 

package main

import (
	"fmt"
	"github.com/gongahkia/monke/lib/graphics"
	"github.com/gongahkia/monke/lib/event"
)

func main() {

	var timeLimitSeconds int
	// var totalNumWords int
	var totalNumSentences int
	var overallWordWPM float64

	timeLimitSeconds = 40
	// totalNumWords = 100
	totalNumSentences = 2

	// graphics.DrawTitleScreen()
	// wordsE := event.MonkeTypeWords(timeLimitSeconds, totalNumWords)
	// overallWordWPM = (float64(wordsE)/float64(timeLimitSeconds)) * 60
	// fmt.Println("WPM:", overallWordWPM)

	graphics.DrawTitleScreen()
	sentencesE := event.MonkeTypeSentences(timeLimitSeconds, totalNumSentences)
	overallWordWPM = (float64(sentencesE)/float64(timeLimitSeconds)) * 60
	fmt.Println("WPM:", overallWordWPM)

}
