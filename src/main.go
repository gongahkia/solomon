// FUA
    // learn how ebiten api generally works with go
    // work out project structure
	// call some api to get a string of random words to type
	// mimick most to all monkeytype features
	// basic keyboard and punctuation and number inputs, escape escapes the game
	// highscore with past WPM and player name as needed
	// if possible, work out how to implement a serverless highscore system
	// add crunchy typing audio like a typewriter perhaps?

package main

import (
    "fmt"
	"os"
	"log"
	"github.com/hajimehoshi/ebiten/v2"
	"github.com/hajimehoshi/ebiten/v2/ebitenutil"
)

type Game struct{
	TextInput string
}

func (g *Game) Layout(outsideWidth, outsideHeight int) (screenWidth, screenHeight int) { // pointer receiver function
	return 320, 240
}

func (g *Game) KeyPressed(key ebiten.Key, mod ebiten.ModifierKey, text string) error { // pointer receiver function

	// --- user input ---

	if key == ebiten.KeyEscape {
		fmt.Println("quitting monke...")
		return fmt.Errorf("user quit monke")
	} else if key == ebiten.KeyBackspace && len(g.TextInput) > 0 {
		g.TextInput = g.TextInput[:len(g.TextInput)-1]
	} else if key == ebiten.KeyEnter {
		g.TextInput += "\n"
	} else if len(text) > 0 {
		g.TextInput += text
	} else {}

	return nil

}

func (g *Game) Update() error { // pointer receiver function

// --- update logical state ---

	return nil
}

func (g *Game) Draw(screen *ebiten.Image) { // pointer receiver function

// --- render graphics ---

	ebitenutil.DebugPrint(screen, "Welcome to MONKE")

}

func main() {


// --- window initialization ---

	ebiten.SetFullscreen(true)
	ebiten.SetWindowTitle("Monke")

// --- default presets ---

	game := &Game{}

	ebiten.SetKeyHandler(func(key ebiten.Key) {
		game.KeyPressed(key)
	})

	if err := ebiten.RunGame(game); err != nil {
		log.Fatal(err) // error logging
		os.Exit(1)
	}

}
