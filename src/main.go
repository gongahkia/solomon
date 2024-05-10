// fua
	// work out why the drawtitlescren is not showing, perhaps need to read user input first
	// add final selection options here for type words or sentences
	// abstract highscore logic here? see if functions under event should return anything
		// highscore with past WPM and player name as needed

package main

import (
	"github.com/gongahkia/monke/lib/graphics"
	"github.com/gongahkia/monke/lib/event"
)

func main() {

	var timeLimit int
	// var totalNumWords int
	var totalNumSentences int

	timeLimit = 40
	// totalNumWords = 10
	totalNumSentences = 2

	graphics.DrawTitleScreen()
	// event.MonkeTypeWords(timeLimit, totalNumWords)
	event.MonkeTypeSentences(timeLimit, totalNumSentences)

}
