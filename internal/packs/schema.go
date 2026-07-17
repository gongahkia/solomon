package packs

import "fmt"

const SchemaVersionV1 = 1

type Compatibility struct {
	SchemaVersion int
	Compatible    bool
}

func SchemaCompatibility(version int) Compatibility {
	return Compatibility{SchemaVersion: version, Compatible: version == SchemaVersionV1}
}

func ValidateSchemaCompatibility(version int) error {
	if SchemaCompatibility(version).Compatible {
		return nil
	}
	if version < SchemaVersionV1 {
		return fmt.Errorf("unsupported legacy schema version %d", version)
	}
	return fmt.Errorf("unsupported future schema version %d", version)
}
