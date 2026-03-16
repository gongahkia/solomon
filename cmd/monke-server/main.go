package main

import (
	"embed"
	"flag"
	"log"

	"github.com/gongahkia/monke/internal/multiplayer"
	"github.com/gongahkia/monke/internal/wordlist"
)

//go:embed assets/words/*
var assetsFS embed.FS

func main() {
	addr := flag.String("addr", ":8080", "listen address")
	flag.Parse()
	wordlist.Init(assetsFS)
	wl, err := wordlist.Load("english_1k")
	if err != nil {
		log.Fatalf("load words: %v", err)
	}
	srv := multiplayer.NewServer(wl.Words)
	if err := srv.Run(*addr); err != nil {
		log.Fatal(err)
	}
}
