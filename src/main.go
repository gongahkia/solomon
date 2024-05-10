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

	graphics.DrawTitleScreen()
	event.MonkeTypeWords()

}
