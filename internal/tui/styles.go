package tui

import (
	"github.com/charmbracelet/lipgloss"
	"github.com/gongahkia/monke/internal/config"
)

type theme struct {
	correct   lipgloss.Style
	incorrect lipgloss.Style
	extra     lipgloss.Style
	upcoming  lipgloss.Style
	cursor    lipgloss.Style
	title     lipgloss.Style
	subtitle  lipgloss.Style
	accent    lipgloss.Style
	dim       lipgloss.Style
	bold      lipgloss.Style
	hint      lipgloss.Style
	wpm       lipgloss.Style
	accuracy  lipgloss.Style
}

var th theme

func init() { applyTheme("catppuccin") }

func applyTheme(name string) {
	tc, ok := config.Themes[name]
	if !ok {
		tc = config.Themes["catppuccin"]
	}
	th = theme{
		correct:   lipgloss.NewStyle().Foreground(lipgloss.Color(tc.Correct)),
		incorrect: lipgloss.NewStyle().Foreground(lipgloss.Color(tc.Incorrect)).Strikethrough(true),
		extra:     lipgloss.NewStyle().Foreground(lipgloss.Color(tc.Extra)).Faint(true),
		upcoming:  lipgloss.NewStyle().Foreground(lipgloss.Color(tc.Upcoming)),
		cursor:    lipgloss.NewStyle().Foreground(lipgloss.Color(tc.Cursor)).Underline(true),
		title:     lipgloss.NewStyle().Foreground(lipgloss.Color(tc.Title)).Bold(true),
		subtitle:  lipgloss.NewStyle().Foreground(lipgloss.Color(tc.Subtitle)),
		accent:    lipgloss.NewStyle().Foreground(lipgloss.Color(tc.Accent)),
		dim:       lipgloss.NewStyle().Foreground(lipgloss.Color(tc.Dim)),
		bold:      lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color(tc.Text)),
		hint:      lipgloss.NewStyle().Foreground(lipgloss.Color(tc.Dim)).Italic(true),
		wpm:       lipgloss.NewStyle().Foreground(lipgloss.Color(tc.Accent)).Bold(true),
		accuracy:  lipgloss.NewStyle().Foreground(lipgloss.Color(tc.Correct)).Bold(true),
	}
}
