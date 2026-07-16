package diagnose

import (
	"encoding/base64"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/gongahkia/close-enough/internal/config"
)

type Risk string

const (
	RiskSafe    Risk = "safe"
	RiskUnknown Risk = "unknown"
	RiskHigh    Risk = "high"
)

type Decision struct {
	Action      string   `json:"action"`
	Cause       string   `json:"cause,omitempty"`
	Consequence string   `json:"consequence,omitempty"`
	Suggestion  string   `json:"suggestion,omitempty"`
	Confidence  float64  `json:"confidence"`
	Risk        Risk     `json:"risk"`
	Trace       []string `json:"trace,omitempty"`
}

func (d Decision) Record() string {
	fields := []string{d.Action, string(d.Risk), fmt.Sprintf("%.2f", d.Confidence), base64.RawStdEncoding.EncodeToString([]byte(d.Cause)), base64.RawStdEncoding.EncodeToString([]byte(d.Consequence)), base64.RawStdEncoding.EncodeToString([]byte(d.Suggestion))}
	return strings.Join(fields, "\t") + "\n"
}

type Options struct {
	Config config.Config
	Path   string
	CWD    string
}

type Engine struct{ options Options }

func New(options Options) Engine { return Engine{options: options} }

func (e Engine) Check(line, stage string) (Decision, error) {
	words, err := tokenize(line)
	if err != nil || len(words) == 0 || e.options.Config.Mode == "off" {
		return Decision{Action: "none", Risk: RiskSafe}, err
	}
	if decision := e.commandDecision(words); decision.Suggestion != "" {
		return e.applyMode(decision), nil
	}
	if decision := semanticDecision(words); decision.Suggestion != "" {
		return e.applyMode(decision), nil
	}
	if decision := e.pathDecision(words); decision.Suggestion != "" {
		return e.applyMode(decision), nil
	}
	return Decision{Action: "none", Risk: RiskSafe}, nil
}

func (e Engine) applyMode(decision Decision) Decision {
	if e.options.Config.Mode == "rewrite" && decision.Risk == RiskSafe && decision.Confidence >= 0.80 {
		decision.Action = "rewrite"
		return decision
	}
	if e.options.Config.Mode == "interrupt" && decision.Confidence >= 0.90 {
		decision.Action = "interrupt"
		return decision
	}
	decision.Action = "hint"
	return decision
}

func (e Engine) commandDecision(words []string) Decision {
	if strings.Contains(words[0], "/") || isShellKeyword(words[0]) || commandExists(words[0], e.options.Path) {
		return Decision{}
	}
	candidates := executableNames(e.options.Path)
	best, distance := nearest(words[0], candidates)
	if best == "" || distance > maxDistance(words[0]) {
		return Decision{}
	}
	replaced := append([]string{best}, words[1:]...)
	return Decision{Cause: "command not found locally", Consequence: "the shell would reject this command", Suggestion: strings.Join(replaced, " "), Confidence: confidence(words[0], best), Risk: classify(replaced), Trace: []string{"resolver:path", "distance:" + fmt.Sprint(distance)}}
}

func semanticDecision(words []string) Decision {
	if words[0] != "git" || len(words) < 2 {
		return Decision{}
	}
	known := []string{"add", "branch", "checkout", "clone", "commit", "diff", "fetch", "init", "log", "merge", "pull", "push", "rebase", "restore", "status", "switch"}
	best, distance := nearest(words[1], known)
	if best == "" || distance > maxDistance(words[1]) {
		return Decision{}
	}
	replaced := append([]string{"git", best}, words[2:]...)
	return Decision{Cause: "unknown Git subcommand", Consequence: "Git will exit before performing work", Suggestion: strings.Join(replaced, " "), Confidence: confidence(words[1], best), Risk: classify(replaced), Trace: []string{"pack:core-git", "distance:" + fmt.Sprint(distance)}}
}

func (e Engine) pathDecision(words []string) Decision {
	for i := 1; i < len(words); i++ {
		word := words[i]
		if strings.HasPrefix(word, "-") || !strings.Contains(word, "/") && !strings.HasPrefix(word, ".") {
			continue
		}
		if _, err := os.Stat(filepath.Join(e.options.CWD, word)); err == nil {
			continue
		}
		dir, base := filepath.Split(word)
		entries, err := os.ReadDir(filepath.Join(e.options.CWD, dir))
		if err != nil {
			continue
		}
		names := make([]string, 0, len(entries))
		for _, entry := range entries {
			names = append(names, entry.Name())
		}
		best, distance := nearest(base, names)
		if best == "" || distance > maxDistance(base) {
			continue
		}
		replaced := append([]string{}, words...)
		replaced[i] = filepath.Join(dir, best)
		return Decision{Cause: "path does not exist", Consequence: "the command may fail or target the wrong file", Suggestion: strings.Join(replaced, " "), Confidence: confidence(base, best), Risk: classify(replaced), Trace: []string{"resolver:filesystem", "distance:" + fmt.Sprint(distance)}}
	}
	return Decision{}
}

func tokenize(line string) ([]string, error) {
	var result []string
	var current strings.Builder
	var quote rune
	escaped := false
	flush := func() {
		if current.Len() > 0 {
			result = append(result, current.String())
			current.Reset()
		}
	}
	for _, r := range line {
		if escaped {
			current.WriteRune(r)
			escaped = false
			continue
		}
		if r == '\\' && quote != '\'' {
			escaped = true
			continue
		}
		if quote != 0 {
			if r == quote {
				quote = 0
			} else {
				current.WriteRune(r)
			}
			continue
		}
		if r == '\'' || r == '"' {
			quote = r
			continue
		}
		if r == ' ' || r == '\t' {
			flush()
			continue
		}
		current.WriteRune(r)
	}
	if escaped || quote != 0 {
		return nil, fmt.Errorf("incomplete shell input")
	}
	flush()
	return result, nil
}

func executableNames(pathValue string) []string {
	seen := map[string]struct{}{}
	for _, dir := range filepath.SplitList(pathValue) {
		entries, err := os.ReadDir(dir)
		if err != nil {
			continue
		}
		for _, entry := range entries {
			if entry.IsDir() {
				continue
			}
			info, err := entry.Info()
			if err == nil && info.Mode()&0o111 != 0 {
				seen[entry.Name()] = struct{}{}
			}
		}
	}
	result := make([]string, 0, len(seen))
	for name := range seen {
		result = append(result, name)
	}
	sort.Strings(result)
	return result
}

func commandExists(name, pathValue string) bool {
	for _, dir := range filepath.SplitList(pathValue) {
		info, err := os.Stat(filepath.Join(dir, name))
		if err == nil && !info.IsDir() && info.Mode()&0o111 != 0 {
			return true
		}
	}
	return false
}

func nearest(value string, candidates []string) (string, int) {
	best, bestDistance := "", 1<<30
	for _, candidate := range candidates {
		distance := damerauLevenshtein(value, candidate)
		if distance < bestDistance || distance == bestDistance && candidate < best {
			best, bestDistance = candidate, distance
		}
	}
	if best == "" {
		return "", 0
	}
	return best, bestDistance
}

func levenshtein(a, b string) int {
	previous := make([]int, len(b)+1)
	for j := range previous {
		previous[j] = j
	}
	for i, ra := range a {
		current := make([]int, len(b)+1)
		current[0] = i + 1
		for j, rb := range b {
			cost := 0
			if ra != rb {
				cost = 1
			}
			current[j+1] = min(current[j]+1, previous[j+1]+1, previous[j]+cost)
		}
		previous = current
	}
	return previous[len(b)]
}

func damerauLevenshtein(a, b string) int {
	previousPrevious := make([]int, len(b)+1)
	previous := make([]int, len(b)+1)
	for j := range previous {
		previous[j] = j
	}
	for i, ra := range a {
		current := make([]int, len(b)+1)
		current[0] = i + 1
		for j, rb := range b {
			cost := 0
			if ra != rb {
				cost = 1
			}
			current[j+1] = min(current[j]+1, previous[j+1]+1, previous[j]+cost)
			if i > 0 && j > 0 && ra == rune(b[j-1]) && rune(a[i-1]) == rb {
				current[j+1] = min(current[j+1], previousPrevious[j-1]+1)
			}
		}
		previousPrevious, previous = previous, current
	}
	return previous[len(b)]
}

func min(values ...int) int {
	result := values[0]
	for _, value := range values[1:] {
		if value < result {
			result = value
		}
	}
	return result
}
func maxDistance(value string) int {
	if len(value) <= 4 {
		return 1
	}
	if len(value) <= 8 {
		return 2
	}
	return 3
}
func confidence(a, b string) float64 {
	return 1 - float64(damerauLevenshtein(a, b))/float64(max(len(a), len(b)))
}
func isShellKeyword(value string) bool {
	_, ok := map[string]struct{}{"if": {}, "then": {}, "else": {}, "fi": {}, "for": {}, "while": {}, "do": {}, "done": {}, "case": {}, "esac": {}, "function": {}, "time": {}, "command": {}, "builtin": {}, "exec": {}, "sudo": {}}[value]
	return ok
}
func classify(words []string) Risk {
	for _, word := range words {
		if word == "sudo" || word == "rm" || word == "dd" || word == "mkfs" || word == "curl" || word == "wget" || word == "ssh" {
			return RiskHigh
		}
	}
	return RiskSafe
}
