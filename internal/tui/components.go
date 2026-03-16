package tui

import (
	"fmt"
	"strings"

	"github.com/charmbracelet/lipgloss"
)

func progressBar(current, total, width int) string {
	if total <= 0 || width <= 2 {
		return ""
	}
	filled := width * current / total
	if filled > width {
		filled = width
	}
	bar := strings.Repeat("━", filled) + strings.Repeat("─", width-filled)
	return th.accent.Render(bar)
}

func statLine(wpm float64, accuracy float64, extra string) string {
	parts := []string{
		th.wpm.Render(fmt.Sprintf("%.0f wpm", wpm)),
		th.accuracy.Render(fmt.Sprintf("%.0f%% acc", accuracy)),
	}
	if extra != "" {
		parts = append(parts, th.dim.Render(extra))
	}
	return lipgloss.JoinHorizontal(lipgloss.Top, strings.Join(parts, th.dim.Render("  │  ")))
}
