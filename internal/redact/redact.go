package redact

import (
	"regexp"
	"strings"
)

const Replacement = "[REDACTED]"

var secretAssignment = regexp.MustCompile(`(?i)((?:^|[[:space:]?&;]|--)(?:[a-z0-9_-]*_)?(?:token|secret|password|passwd|api[-_]?key|access[-_]?key|private[-_]?key|credential|authorization|cookie)=)[^[:space:]&;]+`)
var URLUserInfo = regexp.MustCompile(`([a-zA-Z][a-zA-Z0-9+.-]*://)[^/@[:space:]]+@`)
var bearerCredential = regexp.MustCompile(`(?i)(bearer[[:space:]]+)[^[:space:]]+`)
var authorizationCredential = regexp.MustCompile(`(?i)((?:proxy-)?authorization:[[:space:]]+(?:basic|bearer|token)[[:space:]]+)[^[:space:]]+`)
var cookieCredential = regexp.MustCompile(`(?i)((?:set-)?cookie:[[:space:]]*)[^[:space:]]+`)

func Text(value string) (string, bool) {
	redacted := secretAssignment.ReplaceAllString(value, "${1}"+Replacement)
	redacted = URLUserInfo.ReplaceAllString(redacted, "${1}"+Replacement+"@")
	redacted = bearerCredential.ReplaceAllString(redacted, "${1}"+Replacement)
	redacted = authorizationCredential.ReplaceAllString(redacted, "${1}"+Replacement)
	redacted = cookieCredential.ReplaceAllString(redacted, "${1}"+Replacement)
	return redacted, redacted != value
}

func Command(words []string) (string, bool) {
	redacted := make([]string, len(words))
	changed := false
	for index, word := range words {
		value, valueChanged := Text(word)
		if key, _, found := strings.Cut(word, "="); found && secretName(key) {
			value = key + "=" + Replacement
			valueChanged = true
		}
		if secretFlag(word) && index+1 < len(words) {
			redacted[index+1] = Replacement
			changed = true
		}
		if redacted[index] == "" {
			redacted[index] = value
		}
		changed = changed || valueChanged
	}
	return strings.Join(redacted, " "), changed
}

func ContainsSecret(words []string) bool {
	_, changed := Command(words)
	return changed
}

func secretFlag(value string) bool {
	return strings.HasPrefix(value, "--") && !strings.Contains(value, "=") && secretName(value)
}

func secretName(value string) bool {
	value = strings.TrimLeft(value, "-")
	value = strings.ToUpper(strings.NewReplacer("-", "_", ".", "_").Replace(value))
	for _, suffix := range []string{"TOKEN", "SECRET", "PASSWORD", "PASSWD", "API_KEY", "APIKEY", "ACCESS_KEY", "PRIVATE_KEY", "CREDENTIAL", "AUTHORIZATION", "COOKIE"} {
		if value == suffix || strings.HasSuffix(value, "_"+suffix) {
			return true
		}
	}
	return false
}
