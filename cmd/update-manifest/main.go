package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/gongahkia/solomon/internal/updatechannel"
)

func main() {
	var artifacts artifactFlags
	channel := flag.String("channel", "", "update channel")
	version := flag.String("version", "", "release version")
	commit := flag.String("commit", "", "release commit")
	output := flag.String("output", "", "manifest output path")
	flag.Var(&artifacts, "artifact", "release archive path; repeatable")
	flag.Parse()
	if flag.NArg() != 0 || *output == "" {
		fail(errors.New("invalid update manifest command input"))
	}
	input, err := manifestInput(*channel, *version, *commit, artifacts)
	if err != nil {
		fail(err)
	}
	manifest, err := updatechannel.Generate(input)
	if err != nil {
		fail(err)
	}
	data, err := json.Marshal(manifest)
	if err != nil {
		fail(err)
	}
	if err := os.MkdirAll(filepath.Dir(*output), 0o700); err != nil {
		fail(err)
	}
	if err := os.WriteFile(*output, append(data, '\n'), 0o600); err != nil {
		fail(err)
	}
}

type artifactFlags []string

func (artifacts *artifactFlags) String() string { return strings.Join(*artifacts, ",") }

func (artifacts *artifactFlags) Set(value string) error {
	*artifacts = append(*artifacts, value)
	return nil
}

func manifestInput(channel, version, commit string, paths []string) (updatechannel.Input, error) {
	input := updatechannel.Input{Channel: channel, Version: version, Commit: commit, Artifacts: make([]updatechannel.ArtifactInput, 0, len(paths))}
	for _, path := range paths {
		data, err := regularFile(path)
		if err != nil {
			return updatechannel.Input{}, err
		}
		signaturePath := path + ".sigstore.json"
		signature, err := regularFile(signaturePath)
		if err != nil {
			return updatechannel.Input{}, err
		}
		input.Artifacts = append(input.Artifacts, updatechannel.ArtifactInput{Name: filepath.Base(path), Data: data, SignatureName: filepath.Base(signaturePath), Signature: signature})
	}
	return input, nil
}

func regularFile(path string) ([]byte, error) {
	info, err := os.Lstat(path)
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() {
		return nil, errors.New("artifact is not a regular file")
	}
	// #nosec G304 -- The internal release tool deliberately reads explicit artifact paths.
	return os.ReadFile(path)
}

func fail(err error) {
	fmt.Fprintln(os.Stderr, err)
	os.Exit(2)
}
