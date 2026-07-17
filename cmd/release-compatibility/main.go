package main

import (
	"fmt"
	"os"
	"os/exec"

	"github.com/gongahkia/close-enough/internal/releasecompat"
)

func main() {
	data, err := exec.Command("go", "tool", "dist", "list").Output()
	if err != nil {
		fail(err)
	}
	if err := releasecompat.Validate(releasecompat.ParsePlatforms(string(data))); err != nil {
		fail(err)
	}
	matrix, err := releasecompat.JSON()
	if err != nil {
		fail(err)
	}
	fmt.Println(string(matrix))
}

func fail(err error) {
	fmt.Fprintln(os.Stderr, err)
	os.Exit(2)
}
