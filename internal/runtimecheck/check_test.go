package runtimecheck

import (
	"errors"
	"os"
	"testing"
)

func TestCheckAcceptsSafeRuntime(t *testing.T) {
	report := Check(Options{Path: "/usr/bin:/bin", EffectiveUserID: 501, WorkingDirectory: 0o755})
	if !report.Safe || report.Error() != nil {
		t.Fatalf("unexpected report: %#v", report)
	}
}

func TestCheckRejectsUnsafeRuntimeConditions(t *testing.T) {
	report := Check(Options{Path: "/usr/bin::relative", EffectiveUserID: 0, WorkingDirectory: 0o777})
	if report.Safe || len(report.Findings) != 3 {
		t.Fatalf("unexpected report: %#v", report)
	}
	if got := report.Error(); got == nil || got.Error() != "unsafe local runtime: privileged-user,unsafe-path,writable-working-directory" {
		t.Fatalf("unexpected error: %v", got)
	}
	report = Check(Options{Path: "/usr/bin", EffectiveUserID: 501, WorkingDirError: errors.New("unavailable")})
	if report.Safe || len(report.Findings) != 1 || report.Findings[0].Code != "working-directory-unavailable" {
		t.Fatalf("unexpected unavailable report: %#v", report)
	}
}

func TestCheckDoesNotTreatOwnerWriteAsUnsafe(t *testing.T) {
	report := Check(Options{Path: "/usr/bin", EffectiveUserID: 501, WorkingDirectory: os.FileMode(0o700)})
	if !report.Safe {
		t.Fatalf("unexpected report: %#v", report)
	}
}
