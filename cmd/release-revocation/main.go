package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/gongahkia/close-enough/internal/releasepolicy"
)

func main() {
	revokedVersion := flag.String("revoked-version", "", "revoked release version")
	replacementVersion := flag.String("replacement-version", "", "replacement release version")
	reason := flag.String("reason", "", "public revocation reason")
	output := flag.String("output", "", "revocation notice path")
	flag.Parse()
	if flag.NArg() != 0 || *output == "" {
		fail(errors.New("invalid revocation command input"))
	}
	revocation, err := releasepolicy.NewRevocation(*revokedVersion, *replacementVersion, *reason, time.Now())
	if err != nil {
		fail(err)
	}
	data, err := json.Marshal(revocation)
	if err != nil {
		fail(err)
	}
	if err := os.MkdirAll(filepath.Dir(*output), 0o755); err != nil {
		fail(err)
	}
	if err := os.WriteFile(*output, append(data, '\n'), 0o644); err != nil {
		fail(err)
	}
}

func fail(err error) {
	fmt.Fprintln(os.Stderr, err)
	os.Exit(2)
}
