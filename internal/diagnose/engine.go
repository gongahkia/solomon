package diagnose

import (
	"encoding/base64"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"sync"
	"unicode"

	"github.com/gongahkia/close-enough/internal/config"
	"github.com/gongahkia/close-enough/internal/redact"
)

type Risk string
type RepairClass string

type Evidence struct {
	Kind  string `json:"kind"`
	Value string `json:"value"`
}

const AdapterProtocolVersion = 1

const (
	RiskSafe    Risk = "safe"
	RiskUnknown Risk = "unknown"
	RiskHigh    Risk = "high"

	RepairClassCommand  RepairClass = "command"
	RepairClassSemantic RepairClass = "semantic"
	RepairClassPath     RepairClass = "path"
)

type Decision struct {
	Version     int         `json:"version"`
	Action      string      `json:"action"`
	Cause       string      `json:"cause,omitempty"`
	Consequence string      `json:"consequence,omitempty"`
	Suggestion  string      `json:"suggestion,omitempty"`
	Class       RepairClass `json:"class,omitempty"`
	Evidence    []Evidence  `json:"evidence,omitempty"`
	Confidence  float64     `json:"confidence"`
	Risk        Risk        `json:"risk"`
	Incomplete  bool        `json:"incomplete,omitempty"`
	Trace       []string    `json:"trace,omitempty"`
}

type Event struct {
	Version     int         `json:"version"`
	Stage       string      `json:"stage"`
	Action      string      `json:"action"`
	Cause       string      `json:"cause,omitempty"`
	Consequence string      `json:"consequence,omitempty"`
	Suggestion  string      `json:"suggestion,omitempty"`
	Class       RepairClass `json:"class,omitempty"`
	Evidence    []Evidence  `json:"evidence,omitempty"`
	Confidence  float64     `json:"confidence"`
	Risk        Risk        `json:"risk"`
	Incomplete  bool        `json:"incomplete,omitempty"`
	Trace       []string    `json:"trace,omitempty"`
}

func (d Decision) Event(stage string) Event {
	return Event{Version: d.Version, Stage: stage, Action: d.Action, Cause: d.Cause, Consequence: d.Consequence, Suggestion: d.Suggestion, Class: d.Class, Evidence: append([]Evidence(nil), d.Evidence...), Confidence: d.Confidence, Risk: d.Risk, Incomplete: d.Incomplete, Trace: append([]string(nil), d.Trace...)}
}

func (d Decision) Record() string {
	fields := []string{strconv.Itoa(d.Version), d.Action, string(d.Risk), fmt.Sprintf("%.2f", d.Confidence), base64.RawStdEncoding.EncodeToString([]byte(d.Cause)), base64.RawStdEncoding.EncodeToString([]byte(d.Consequence)), base64.RawStdEncoding.EncodeToString([]byte(d.Suggestion))}
	return strings.Join(fields, "\t") + "\n"
}

type Options struct {
	Config config.Config
	Path   string
	CWD    string
}

type Engine struct{ options Options }

type executableCacheEntry struct {
	signature string
	names     []string
}

var executableCache = struct {
	sync.RWMutex
	entries map[string]executableCacheEntry
}{entries: map[string]executableCacheEntry{}}

func New(options Options) Engine { return Engine{options: options} }

func (e Engine) Check(line, stage string) (Decision, error) {
	words, err := tokenize(line)
	if err != nil {
		decision := noDecision()
		decision.Incomplete = true
		return decision, nil
	}
	if len(words) == 0 || e.options.Config.Mode == "off" {
		return noDecision(), nil
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
	return noDecision(), nil
}

func noDecision() Decision {
	return Decision{Version: AdapterProtocolVersion, Action: "none", Risk: RiskSafe}
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
	candidates := executableNames(e.options.Path)
	for _, position := range commandPositions(words) {
		word := words[position]
		if isPathQualified(word, runtime.GOOS) || commandExists(word, e.options.Path) {
			continue
		}
		best, distance := nearest(word, candidates)
		if best == "" || distance > maxDistance(word) {
			continue
		}
		confidence := confidence(word, best)
		if !meetsConfidenceThreshold(RepairClassCommand, confidence) {
			continue
		}
		replaced := append([]string{}, words...)
		replaced[position] = best
		suggestion, containsSecret := redact.Command(replaced)
		return Decision{Version: AdapterProtocolVersion, Cause: "command not found locally", Consequence: "the shell would reject this command", Suggestion: suggestion, Class: RepairClassCommand, Evidence: collectEvidence(RepairClassCommand, "path", distance, confidence), Confidence: confidence, Risk: classify(replaced, containsSecret), Trace: []string{"resolver:path", "distance:" + fmt.Sprint(distance)}}
	}
	return Decision{}
}

func semanticDecision(words []string) Decision {
	known := []string{"add", "branch", "checkout", "clone", "commit", "diff", "fetch", "init", "log", "merge", "pull", "push", "rebase", "restore", "status", "switch"}
	for _, position := range commandPositions(words) {
		if words[position] != "git" || position+1 >= len(words) || isCompoundOperator(words[position+1]) {
			continue
		}
		best, distance := nearest(words[position+1], known)
		if best == "" || distance > maxDistance(words[position+1]) {
			continue
		}
		confidence := confidence(words[position+1], best)
		if !meetsConfidenceThreshold(RepairClassSemantic, confidence) {
			continue
		}
		replaced := append([]string{}, words...)
		replaced[position+1] = best
		suggestion, containsSecret := redact.Command(replaced)
		return Decision{Version: AdapterProtocolVersion, Cause: "unknown Git subcommand", Consequence: "Git will exit before performing work", Suggestion: suggestion, Class: RepairClassSemantic, Evidence: collectEvidence(RepairClassSemantic, "core-git", distance, confidence), Confidence: confidence, Risk: classify(replaced, containsSecret), Trace: []string{"pack:core-git", "distance:" + fmt.Sprint(distance)}}
	}
	return Decision{}
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
		confidence := confidence(base, best)
		if !meetsConfidenceThreshold(RepairClassPath, confidence) {
			continue
		}
		replaced := append([]string{}, words...)
		replaced[i] = filepath.Join(dir, best)
		suggestion, containsSecret := redact.Command(replaced)
		return Decision{Version: AdapterProtocolVersion, Cause: "path does not exist", Consequence: "the command may fail or target the wrong file", Suggestion: suggestion, Class: RepairClassPath, Evidence: collectEvidence(RepairClassPath, "filesystem", distance, confidence), Confidence: confidence, Risk: classify(replaced, containsSecret), Trace: []string{"resolver:filesystem", "distance:" + fmt.Sprint(distance)}}
	}
	return Decision{}
}

func tokenize(line string) ([]string, error) {
	var result []string
	var current strings.Builder
	var quote rune
	escaped := false
	wordStarted := false
	flush := func() {
		if wordStarted {
			result = append(result, current.String())
			current.Reset()
			wordStarted = false
		}
	}
	runes := []rune(line)
	for index := 0; index < len(runes); index++ {
		r := runes[index]
		if escaped {
			current.WriteRune(r)
			escaped = false
			wordStarted = true
			continue
		}
		if r == '\\' && quote != '\'' {
			escaped = true
			wordStarted = true
			continue
		}
		if quote != 0 {
			if r == quote {
				quote = 0
			} else {
				current.WriteRune(r)
			}
			wordStarted = true
			continue
		}
		if r == '\'' || r == '"' {
			quote = r
			wordStarted = true
			continue
		}
		if operator, width := compoundOperator(runes[index:]); width > 0 {
			flush()
			result = append(result, operator)
			index += width - 1
			continue
		}
		if r == ' ' || r == '\t' {
			flush()
			continue
		}
		current.WriteRune(r)
		wordStarted = true
	}
	if escaped || quote != 0 {
		return nil, fmt.Errorf("incomplete shell input")
	}
	flush()
	return result, nil
}

func compoundOperator(runes []rune) (string, int) {
	if len(runes) == 0 {
		return "", 0
	}
	switch runes[0] {
	case ';', '(', ')':
		return string(runes[0]), 1
	case '&':
		if len(runes) > 1 && runes[1] == '&' {
			return "&&", 2
		}
		return "&", 1
	case '|':
		if len(runes) > 1 && (runes[1] == '|' || runes[1] == '&') {
			return string(runes[:2]), 2
		}
		return "|", 1
	case '\n':
		return ";", 1
	default:
		return "", 0
	}
}

func commandPositions(words []string) []int {
	positions := []int{}
	expectCommand := true
	for index, word := range words {
		if isCompoundOperator(word) {
			expectCommand = word != ")"
			continue
		}
		if !expectCommand {
			continue
		}
		if isShellKeyword(word) || assignmentWord(word) {
			continue
		}
		positions = append(positions, index)
		expectCommand = false
	}
	return positions
}

func isCompoundOperator(value string) bool {
	return value == ";" || value == "&" || value == "&&" || value == "|" || value == "|&" || value == "||" || value == "(" || value == ")"
}

func assignmentWord(value string) bool {
	name, _, found := strings.Cut(value, "=")
	if !found || name == "" {
		return false
	}
	for index, character := range name {
		if character == '_' || character >= 'a' && character <= 'z' || character >= 'A' && character <= 'Z' || index > 0 && character >= '0' && character <= '9' {
			continue
		}
		return false
	}
	return true
}

func executableNames(pathValue string) []string {
	return executableNamesFor(pathValue, runtime.GOOS, os.Getenv("PATHEXT"))
}

func executableNamesFor(pathValue, platform, pathExt string) []string {
	cacheKey := platform + "\x00" + pathExt + "\x00" + pathValue
	signature := pathSignature(pathValue)
	executableCache.RLock()
	entry, ok := executableCache.entries[cacheKey]
	executableCache.RUnlock()
	if ok && entry.signature == signature {
		return append([]string(nil), entry.names...)
	}
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
			if err == nil && isExecutableCandidate(entry.Name(), info.Mode(), platform, pathExt) {
				seen[normalizeExecutableName(entry.Name(), platform, pathExt)] = struct{}{}
			}
		}
	}
	result := make([]string, 0, len(seen))
	for name := range seen {
		result = append(result, name)
	}
	sort.Strings(result)
	executableCache.Lock()
	executableCache.entries[cacheKey] = executableCacheEntry{signature: signature, names: append([]string(nil), result...)}
	executableCache.Unlock()
	return result
}

func commandExists(name, pathValue string) bool {
	return commandExistsFor(name, pathValue, runtime.GOOS, os.Getenv("PATHEXT"))
}

func commandExistsFor(name, pathValue, platform, pathExt string) bool {
	names := executableNamesFor(pathValue, platform, pathExt)
	name = normalizeExecutableName(name, platform, pathExt)
	index := sort.SearchStrings(names, name)
	return index < len(names) && names[index] == name
}

func InvalidateExecutableIndex() {
	executableCache.Lock()
	executableCache.entries = map[string]executableCacheEntry{}
	executableCache.Unlock()
}

func pathSignature(pathValue string) string {
	var signature strings.Builder
	for _, dir := range filepath.SplitList(pathValue) {
		info, err := os.Stat(dir)
		if err != nil {
			signature.WriteString(dir)
			signature.WriteString(":missing\x00")
			continue
		}
		signature.WriteString(dir)
		signature.WriteByte(':')
		signature.WriteString(strconv.FormatInt(info.ModTime().UnixNano(), 10))
		signature.WriteByte(':')
		signature.WriteString(strconv.FormatInt(info.Size(), 10))
		signature.WriteByte('\x00')
	}
	return signature.String()
}

func isExecutableCandidate(name string, mode os.FileMode, platform, pathExt string) bool {
	if platform != "windows" {
		return mode&0o111 != 0
	}
	_, ok := executableExtension(name, pathExt)
	return ok
}

func normalizeExecutableName(name, platform, pathExt string) string {
	if platform != "windows" {
		return name
	}
	if extension, ok := executableExtension(name, pathExt); ok {
		name = name[:len(name)-len(extension)]
	}
	return strings.ToLower(name)
}

func executableExtension(name, pathExt string) (string, bool) {
	lowerName := strings.ToLower(name)
	for _, extension := range executableExtensions(pathExt) {
		if strings.HasSuffix(lowerName, extension) {
			return extension, true
		}
	}
	return "", false
}

func executableExtensions(pathExt string) []string {
	if pathExt == "" {
		pathExt = ".COM;.EXE;.BAT;.CMD"
	}
	extensions := []string{}
	for _, extension := range strings.Split(pathExt, ";") {
		extension = strings.TrimSpace(extension)
		if extension == "" {
			continue
		}
		if !strings.HasPrefix(extension, ".") {
			extension = "." + extension
		}
		extensions = append(extensions, strings.ToLower(extension))
	}
	return extensions
}

func isPathQualified(value, platform string) bool {
	if platform == "windows" {
		return strings.ContainsAny(value, "/\\")
	}
	return strings.Contains(value, "/")
}

func nearest(value string, candidates []string) (string, int) {
	ranked := rankCandidates(value, candidates)
	if len(ranked) == 0 {
		return "", 0
	}
	return ranked[0].value, ranked[0].editDistance
}

type rankedCandidate struct {
	value            string
	editDistance     int
	keyboardDistance int
}

func rankCandidates(value string, candidates []string) []rankedCandidate {
	seen := map[string]struct{}{}
	ranked := make([]rankedCandidate, 0, len(candidates))
	for _, candidate := range candidates {
		if _, exists := seen[candidate]; exists {
			continue
		}
		seen[candidate] = struct{}{}
		ranked = append(ranked, rankedCandidate{value: candidate, editDistance: damerauLevenshtein(value, candidate), keyboardDistance: keyboardAdjacencyDistance(value, candidate)})
	}
	sort.Slice(ranked, func(left, right int) bool {
		if ranked[left].editDistance != ranked[right].editDistance {
			return ranked[left].editDistance < ranked[right].editDistance
		}
		if ranked[left].keyboardDistance != ranked[right].keyboardDistance {
			return ranked[left].keyboardDistance < ranked[right].keyboardDistance
		}
		return ranked[left].value < ranked[right].value
	})
	return ranked
}

var keyboardRows = [][]rune{
	[]rune("1234567890-="),
	[]rune("qwertyuiop[]\\"),
	[]rune("asdfghjkl;'"),
	[]rune("zxcvbnm,./"),
}

func keyboardAdjacencyDistance(a, b string) int {
	aRunes, bRunes := []rune(strings.ToLower(a)), []rune(strings.ToLower(b))
	previous := make([]int, len(bRunes)+1)
	for index := range previous {
		previous[index] = index * 2
	}
	for row, left := range aRunes {
		current := make([]int, len(bRunes)+1)
		current[0] = (row + 1) * 2
		for column, right := range bRunes {
			substitution := 2
			if left == right {
				substitution = 0
			} else if keyboardAdjacent(left, right) {
				substitution = 1
			}
			current[column+1] = min(current[column]+2, previous[column+1]+2, previous[column]+substitution)
		}
		previous = current
	}
	return previous[len(bRunes)]
}

func keyboardAdjacent(left, right rune) bool {
	left, right = unicode.ToLower(left), unicode.ToLower(right)
	for leftRow, keys := range keyboardRows {
		for leftColumn, key := range keys {
			if key != left {
				continue
			}
			for rightRow, rightKeys := range keyboardRows {
				for rightColumn, rightKey := range rightKeys {
					if rightKey == right && abs(leftRow-rightRow) <= 1 && abs(leftColumn-rightColumn) <= 1 {
						return true
					}
				}
			}
		}
	}
	return false
}

func abs(value int) int {
	if value < 0 {
		return -value
	}
	return value
}

func levenshtein(a, b string) int {
	aRunes, bRunes := []rune(a), []rune(b)
	previous := make([]int, len(bRunes)+1)
	for j := range previous {
		previous[j] = j
	}
	for i, ra := range aRunes {
		current := make([]int, len(bRunes)+1)
		current[0] = i + 1
		for j, rb := range bRunes {
			cost := 0
			if ra != rb {
				cost = 1
			}
			current[j+1] = min(current[j]+1, previous[j+1]+1, previous[j]+cost)
		}
		previous = current
	}
	return previous[len(bRunes)]
}

func damerauLevenshtein(a, b string) int {
	aRunes, bRunes := []rune(a), []rune(b)
	previousPrevious := make([]int, len(bRunes)+1)
	previous := make([]int, len(bRunes)+1)
	for j := range previous {
		previous[j] = j
	}
	for i, ra := range aRunes {
		current := make([]int, len(bRunes)+1)
		current[0] = i + 1
		for j, rb := range bRunes {
			cost := 0
			if ra != rb {
				cost = 1
			}
			current[j+1] = min(current[j]+1, previous[j+1]+1, previous[j]+cost)
			if i > 0 && j > 0 && ra == bRunes[j-1] && aRunes[i-1] == rb {
				current[j+1] = min(current[j+1], previousPrevious[j-1]+1)
			}
		}
		previousPrevious, previous = previous, current
	}
	return previous[len(bRunes)]
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
	length := len([]rune(value))
	if length <= 4 {
		return 1
	}
	if length <= 8 {
		return 2
	}
	return 3
}
func confidence(a, b string) float64 {
	return 1 - float64(damerauLevenshtein(a, b))/float64(max(len([]rune(a)), len([]rune(b))))
}
func meetsConfidenceThreshold(class RepairClass, value float64) bool {
	return isKnownRepairClass(class) && value >= confidenceThreshold(class)
}
func isKnownRepairClass(class RepairClass) bool {
	switch class {
	case RepairClassCommand, RepairClassSemantic, RepairClassPath:
		return true
	default:
		return false
	}
}
func confidenceThreshold(class RepairClass) float64 {
	switch class {
	case RepairClassCommand:
		return 0.60
	case RepairClassSemantic:
		return 0.75
	case RepairClassPath:
		return 0.90
	default:
		return 1
	}
}
func collectEvidence(class RepairClass, resolver string, distance int, value float64) []Evidence {
	if resolver == "" || distance < 0 || !meetsConfidenceThreshold(class, value) {
		return nil
	}
	return []Evidence{
		{Kind: "resolver", Value: resolver},
		{Kind: "edit_distance", Value: strconv.Itoa(distance)},
		{Kind: "confidence_threshold", Value: fmt.Sprintf("%.2f", confidenceThreshold(class))},
	}
}
func isShellKeyword(value string) bool {
	_, ok := map[string]struct{}{"if": {}, "then": {}, "else": {}, "fi": {}, "for": {}, "while": {}, "do": {}, "done": {}, "case": {}, "esac": {}, "function": {}, "time": {}, "command": {}, "builtin": {}, "exec": {}, "sudo": {}}[value]
	return ok
}
func classify(words []string, containsSecret bool) Risk {
	if containsSecret {
		return RiskHigh
	}
	if escalatesPrivileges(words) {
		return RiskHigh
	}
	if hasNetworkEffect(words) {
		return RiskHigh
	}
	if mutatesFilesystem(words) {
		return RiskHigh
	}
	return RiskSafe
}

var privilegeEscalationCommands = map[string]struct{}{
	"doas": {}, "pkexec": {}, "runas": {}, "su": {}, "sudo": {}, "sudoedit": {},
}

func escalatesPrivileges(words []string) bool {
	for position, word := range words {
		if !commandStartAt(words, position) {
			continue
		}
		if _, ok := privilegeEscalationCommands[commandName(word)]; ok {
			return true
		}
	}
	return false
}

func commandStartAt(words []string, target int) bool {
	expectCommand := true
	for position, word := range words {
		if isCompoundOperator(word) {
			expectCommand = word != ")"
			continue
		}
		if !expectCommand {
			continue
		}
		if position == target {
			return true
		}
		if isShellKeyword(word) || assignmentWord(word) {
			continue
		}
		expectCommand = false
	}
	return false
}

var networkEffectCommands = map[string]struct{}{
	"curl": {}, "ftp": {}, "nc": {}, "ncat": {}, "netcat": {}, "scp": {}, "sftp": {}, "ssh": {}, "telnet": {}, "tftp": {}, "wget": {},
}

func hasNetworkEffect(words []string) bool {
	for position, word := range words {
		if !commandStartAt(words, position) {
			continue
		}
		command := commandName(word)
		if _, ok := networkEffectCommands[command]; ok {
			return true
		}
		if command == "git" && hasNetworkGitSubcommand(words[position+1:]) {
			return true
		}
	}
	return false
}

func hasNetworkGitSubcommand(words []string) bool {
	for _, word := range words {
		if isCompoundOperator(word) {
			return false
		}
		switch word {
		case "clone", "fetch", "ls-remote", "pull", "push":
			return true
		}
		if !strings.HasPrefix(word, "-") {
			return false
		}
	}
	return false
}

var filesystemMutationCommands = map[string]struct{}{
	"chgrp": {}, "chmod": {}, "chown": {}, "cp": {}, "dd": {}, "install": {}, "ln": {}, "mkdir": {}, "mkfifo": {}, "mknod": {}, "mkfs": {}, "mv": {}, "patch": {}, "rm": {}, "rmdir": {}, "rsync": {}, "shred": {}, "tee": {}, "touch": {}, "truncate": {}, "unlink": {}, "wipefs": {},
}

func mutatesFilesystem(words []string) bool {
	for _, position := range commandPositions(words) {
		command := commandName(words[position])
		if _, ok := filesystemMutationCommands[command]; ok {
			return true
		}
		switch command {
		case "find":
			if hasArgument(words[position+1:], "-delete") {
				return true
			}
		case "sed", "perl":
			if hasArgument(words[position+1:], "-i") || hasArgument(words[position+1:], "--in-place") {
				return true
			}
		}
	}
	return false
}

func commandName(value string) string {
	if index := strings.LastIndexAny(value, "/\\"); index >= 0 {
		value = value[index+1:]
	}
	return strings.ToLower(value)
}

func hasArgument(words []string, value string) bool {
	for _, word := range words {
		if isCompoundOperator(word) {
			return false
		}
		if word == value {
			return true
		}
	}
	return false
}
