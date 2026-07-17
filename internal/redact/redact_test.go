package redact

import "testing"

func TestTextRedactsCommonSecretPatterns(t *testing.T) {
	tests := []struct {
		input string
		want  string
	}{
		{input: "GITHUB_TOKEN=super-secret", want: "GITHUB_TOKEN=[REDACTED]"},
		{input: "https://user:password@example.test/?token=abc", want: "https://[REDACTED]@example.test/?token=[REDACTED]"},
		{input: "Authorization: Bearer abc.def.ghi", want: "Authorization: Bearer [REDACTED]"},
	}
	for _, test := range tests {
		t.Run(test.input, func(t *testing.T) {
			got, changed := Text(test.input)
			if !changed || got != test.want {
				t.Fatalf("Text(%q) = %q, %t; want %q, true", test.input, got, changed, test.want)
			}
		})
	}
}

func TestCommandRedactsAssignmentAndSeparateValue(t *testing.T) {
	got, changed := Command([]string{"curl", "--api-key", "top-secret", "TOKEN=also-secret"})
	if !changed || got != "curl --api-key [REDACTED] TOKEN=[REDACTED]" {
		t.Fatalf("unexpected command redaction: %q, %t", got, changed)
	}
}

func TestTextLeavesNonSecretValuesUnchanged(t *testing.T) {
	input := "git status --short"
	if got, changed := Text(input); changed || got != input {
		t.Fatalf("unexpected redaction: %q, %t", got, changed)
	}
}

func TestContainsSecretUsesCommandTokenDetection(t *testing.T) {
	if !ContainsSecret([]string{"curl", "--token", "top-secret"}) {
		t.Fatal("secret-bearing arguments were not detected")
	}
	if ContainsSecret([]string{"git", "status", "--short"}) {
		t.Fatal("non-secret arguments were detected as secrets")
	}
}
