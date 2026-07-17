package redact

import (
	"encoding/json"
	"os"
	"strings"
	"testing"
)

type secretRedactionFixture struct {
	Name     string   `json:"name"`
	Kind     string   `json:"kind"`
	Input    string   `json:"input"`
	Words    []string `json:"words"`
	Want     string   `json:"want"`
	Secret   string   `json:"secret"`
	Redacted bool     `json:"redacted"`
}

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

func TestSecretRedactionRegressionCorpus(t *testing.T) {
	data, err := os.ReadFile("testdata/secret_redaction.json")
	if err != nil {
		t.Fatal(err)
	}
	var fixtures []secretRedactionFixture
	if err := json.Unmarshal(data, &fixtures); err != nil {
		t.Fatal(err)
	}
	if len(fixtures) == 0 {
		t.Fatal("secret redaction corpus is empty")
	}
	for _, fixture := range fixtures {
		t.Run(fixture.Name, func(t *testing.T) {
			if fixture.Name == "" || fixture.Want == "" {
				t.Fatalf("invalid secret redaction fixture: %#v", fixture)
			}
			var got string
			var changed bool
			switch fixture.Kind {
			case "text":
				if fixture.Input == "" {
					t.Fatalf("text fixture has no input: %#v", fixture)
				}
				got, changed = Text(fixture.Input)
			case "command":
				if len(fixture.Words) == 0 {
					t.Fatalf("command fixture has no words: %#v", fixture)
				}
				got, changed = Command(fixture.Words)
			default:
				t.Fatalf("unknown fixture kind %q", fixture.Kind)
			}
			if got != fixture.Want || changed != fixture.Redacted {
				t.Fatalf("redaction = %q, %t; want %q, %t", got, changed, fixture.Want, fixture.Redacted)
			}
			if fixture.Secret != "" && strings.Contains(got, fixture.Secret) {
				t.Fatalf("redaction leaked secret %q in %q", fixture.Secret, got)
			}
		})
	}
}
