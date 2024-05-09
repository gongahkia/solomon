// FUA
    // learn how ebiten api generally works with go
    // work out project structure
	// call some api to get a string of random words to type
	// mimick most to all monkeytype features
	// basic keyboard and punctuation and number inputs, escape escapes the game
	// highscore with past WPM and player name as needed
	// if possible, work out how to implement a serverless highscore system

package main

import (
    "fmt"
	"log"
	"github.com/hajimehoshi/ebiten/v2"
	"github.com/hajimehoshi/ebiten/v2/ebitenutil"
)

type Game struct{}

func (g *Game) Update() error { // pointer receiver function
	return nil
}

func (g *Game) Draw(screen *ebiten.Image) { // pointer receiver function
	ebitenutil.DebugPrint(screen, "Hello, World!")
}

func (g *Game) Layout(outsideWidth, outsideHeight int) (screenWidth, screenHeight int) { // pointer receiver function
	return 320, 240
}

func main() {

    // --- window initialization ---

	ebiten.SetWindowSize(640, 480)
	ebiten.SetWindowTitle("Hello, World!")

	if err := ebiten.RunGame(&Game{}); err != nil {
		log.Fatal(err) // error logging
	}

	// --- main code execution ---

	fmt.Println("monke")

}
