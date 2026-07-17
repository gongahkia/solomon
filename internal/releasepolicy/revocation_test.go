package releasepolicy

import (
	"testing"
	"time"
)

func TestNewRevocation(t *testing.T) {
	at := time.Date(2026, time.July, 17, 0, 0, 0, 0, time.UTC)
	revocation, err := NewRevocation("v1.2.3", "v1.2.2", "critical regression", at)
	if err != nil {
		t.Fatal(err)
	}
	if revocation.SchemaVersion != RevocationSchemaVersion || revocation.RevokedAt != "2026-07-17T00:00:00Z" {
		t.Fatalf("revocation = %#v", revocation)
	}
}

func TestNewRevocationRejectsInvalidInput(t *testing.T) {
	if _, err := NewRevocation("v1.2.3", "v1.2.3", "reason", time.Now()); err == nil {
		t.Fatal("accepted identical release versions")
	}
	if _, err := NewRevocation("v1.2.3/escape", "v1.2.2", "reason", time.Now()); err == nil {
		t.Fatal("accepted unsafe release version")
	}
	if _, err := NewRevocation("v1.2.3", "v1.2.2", " ", time.Now()); err == nil {
		t.Fatal("accepted blank reason")
	}
}
