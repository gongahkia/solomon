package main

import (
	"crypto/ed25519"
	"encoding/base64"
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/gongahkia/close-enough/internal/tufpublish"
)

func main() {
	var targets targetFlags
	output := flag.String("output", "", "metadata output directory")
	version := flag.String("version", "", "metadata version")
	targetsExpires := flag.String("targets-expires", "", "targets expiration in RFC3339")
	snapshotExpires := flag.String("snapshot-expires", "", "snapshot expiration in RFC3339")
	timestampExpires := flag.String("timestamp-expires", "", "timestamp expiration in RFC3339")
	flag.Var(&targets, "target", "published target file; repeatable")
	flag.Parse()
	if flag.NArg() != 0 {
		fail(errors.New("unexpected positional arguments"))
	}
	parsedVersion, err := strconv.Atoi(*version)
	if err != nil {
		fail(fmt.Errorf("parse version: %w", err))
	}
	targetExpiration, err := time.Parse(time.RFC3339, *targetsExpires)
	if err != nil {
		fail(fmt.Errorf("parse targets expiration: %w", err))
	}
	snapshotExpiration, err := time.Parse(time.RFC3339, *snapshotExpires)
	if err != nil {
		fail(fmt.Errorf("parse snapshot expiration: %w", err))
	}
	timestampExpiration, err := time.Parse(time.RFC3339, *timestampExpires)
	if err != nil {
		fail(fmt.Errorf("parse timestamp expiration: %w", err))
	}
	input, err := publicationInput(targets, parsedVersion, targetExpiration, snapshotExpiration, timestampExpiration)
	if err != nil {
		fail(err)
	}
	if *output == "" {
		fail(errors.New("missing output directory"))
	}
	metadata, err := tufpublish.Generate(input)
	if err != nil {
		fail(err)
	}
	if err := os.MkdirAll(*output, 0o755); err != nil {
		fail(err)
	}
	for name, data := range map[string][]byte{"root.json": metadata.Root, "targets.json": metadata.Targets, "snapshot.json": metadata.Snapshot, "timestamp.json": metadata.Timestamp} {
		if err := os.WriteFile(filepath.Join(*output, name), data, 0o644); err != nil {
			fail(err)
		}
	}
}

type targetFlags []string

func (targets *targetFlags) String() string { return strings.Join(*targets, ",") }

func (targets *targetFlags) Set(value string) error {
	*targets = append(*targets, value)
	return nil
}

func publicationInput(paths []string, version int, targetsExpires, snapshotExpires, timestampExpires time.Time) (tufpublish.Input, error) {
	if len(paths) == 0 {
		return tufpublish.Input{}, errors.New("missing target")
	}
	targets := make([]tufpublish.Target, 0, len(paths))
	for _, name := range paths {
		data, err := os.ReadFile(name)
		if err != nil {
			return tufpublish.Input{}, err
		}
		targets = append(targets, tufpublish.Target{Name: filepath.Base(name), Data: data})
	}
	keys, err := tufKeys()
	if err != nil {
		return tufpublish.Input{}, err
	}
	return tufpublish.Input{Keys: keys, Targets: targets, Version: version, TargetsExpires: targetsExpires, SnapshotExpires: snapshotExpires, TimestampExpires: timestampExpires}, nil
}

func tufKeys() (tufpublish.Keys, error) {
	root, err := decodeKey("TUF_ROOT_PRIVATE_KEY")
	if err != nil {
		return tufpublish.Keys{}, err
	}
	targets, err := decodeKey("TUF_TARGETS_PRIVATE_KEY")
	if err != nil {
		return tufpublish.Keys{}, err
	}
	snapshot, err := decodeKey("TUF_SNAPSHOT_PRIVATE_KEY")
	if err != nil {
		return tufpublish.Keys{}, err
	}
	timestamp, err := decodeKey("TUF_TIMESTAMP_PRIVATE_KEY")
	if err != nil {
		return tufpublish.Keys{}, err
	}
	return tufpublish.Keys{Root: root, Targets: targets, Snapshot: snapshot, Timestamp: timestamp}, nil
}

func decodeKey(name string) (ed25519.PrivateKey, error) {
	value := os.Getenv(name)
	if value == "" {
		return nil, fmt.Errorf("missing %s", name)
	}
	decoded, err := base64.StdEncoding.DecodeString(value)
	if err != nil {
		decoded, err = base64.RawStdEncoding.DecodeString(value)
	}
	if err != nil || len(decoded) != ed25519.PrivateKeySize {
		return nil, fmt.Errorf("invalid %s", name)
	}
	return ed25519.PrivateKey(decoded), nil
}

func fail(err error) {
	fmt.Fprintln(os.Stderr, err)
	os.Exit(2)
}
