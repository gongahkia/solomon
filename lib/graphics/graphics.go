package graphics

import (
	// "fmt"
	"github.com/fatih/color"
)

func DrawTitleScreen(){
	Magenta := color.New(color.FgMagenta)
	Magenta.Print("M O N K E")
}

func DisplayWords(currentAndUpcomingNextWord []string){
	Green := color.New(color.FgGreen, color.Bold)
	White := color.New(color.FgWhite)
	Blue := color.New(color.FgBlue)
	Yellow := color.New(color.FgYellow)
	White.Print("[")
	Green.Print(currentAndUpcomingNextWord[0])
	White.Print("]")
	Blue.Print("\n", currentAndUpcomingNextWord[1], "\n")
	Yellow.Print("---\n")
	White.Print(">")
}

func DisplaySentences(currentAndUpcomingSentence []string){
	Green := color.New(color.FgGreen, color.Bold)
	White := color.New(color.FgWhite)
	Blue := color.New(color.FgBlue)
	Yellow := color.New(color.FgYellow)
	White.Print("[")
	Green.Print(currentAndUpcomingSentence[0])
	White.Print("]")
	Blue.Print("\n", currentAndUpcomingSentence[1], "\n")
	Yellow.Print("---\n")
	White.Print(">")
}

func DisplayWPM(wordWPM float64){
	Cyan := color.New(color.FgCyan, color.Bold)
	Magenta := color.New(color.FgMagenta)
	Cyan.Print("\n","Words Per Minute: ")
	Magenta.Print(wordWPM, "\n\n")
}