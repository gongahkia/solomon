package tui

import "github.com/charmbracelet/lipgloss"

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

var defaultTheme = theme{
	correct:   lipgloss.NewStyle().Foreground(lipgloss.Color("#a6e3a1")),
	incorrect: lipgloss.NewStyle().Foreground(lipgloss.Color("#f38ba8")).Strikethrough(true),
	extra:     lipgloss.NewStyle().Foreground(lipgloss.Color("#f38ba8")).Faint(true),
	upcoming:  lipgloss.NewStyle().Foreground(lipgloss.Color("#6c7086")),
	cursor:    lipgloss.NewStyle().Foreground(lipgloss.Color("#cdd6f4")).Underline(true),
	title:     lipgloss.NewStyle().Foreground(lipgloss.Color("#cba6f7")).Bold(true),
	subtitle:  lipgloss.NewStyle().Foreground(lipgloss.Color("#89b4fa")),
	accent:    lipgloss.NewStyle().Foreground(lipgloss.Color("#f9e2af")),
	dim:       lipgloss.NewStyle().Foreground(lipgloss.Color("#585b70")),
	bold:      lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("#cdd6f4")),
	hint:      lipgloss.NewStyle().Foreground(lipgloss.Color("#585b70")).Italic(true),
	wpm:       lipgloss.NewStyle().Foreground(lipgloss.Color("#f9e2af")).Bold(true),
	accuracy:  lipgloss.NewStyle().Foreground(lipgloss.Color("#a6e3a1")).Bold(true),
}

var th = defaultTheme
