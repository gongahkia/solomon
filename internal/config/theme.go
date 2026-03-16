package config

type ThemeColors struct {
	Name      string
	Correct   string
	Incorrect string
	Extra     string
	Upcoming  string
	Cursor    string
	Title     string
	Subtitle  string
	Accent    string
	Dim       string
	Text      string
}

var Themes = map[string]ThemeColors{
	"catppuccin": {
		Name: "catppuccin", Correct: "#a6e3a1", Incorrect: "#f38ba8", Extra: "#f38ba8",
		Upcoming: "#6c7086", Cursor: "#cdd6f4", Title: "#cba6f7", Subtitle: "#89b4fa",
		Accent: "#f9e2af", Dim: "#585b70", Text: "#cdd6f4",
	},
	"dracula": {
		Name: "dracula", Correct: "#50fa7b", Incorrect: "#ff5555", Extra: "#ff5555",
		Upcoming: "#6272a4", Cursor: "#f8f8f2", Title: "#bd93f9", Subtitle: "#8be9fd",
		Accent: "#f1fa8c", Dim: "#44475a", Text: "#f8f8f2",
	},
	"nord": {
		Name: "nord", Correct: "#a3be8c", Incorrect: "#bf616a", Extra: "#bf616a",
		Upcoming: "#4c566a", Cursor: "#eceff4", Title: "#b48ead", Subtitle: "#88c0d0",
		Accent: "#ebcb8b", Dim: "#3b4252", Text: "#eceff4",
	},
	"gruvbox": {
		Name: "gruvbox", Correct: "#b8bb26", Incorrect: "#fb4934", Extra: "#fb4934",
		Upcoming: "#665c54", Cursor: "#ebdbb2", Title: "#d3869b", Subtitle: "#83a598",
		Accent: "#fabd2f", Dim: "#504945", Text: "#ebdbb2",
	},
	"monokai": {
		Name: "monokai", Correct: "#a6e22e", Incorrect: "#f92672", Extra: "#f92672",
		Upcoming: "#75715e", Cursor: "#f8f8f2", Title: "#ae81ff", Subtitle: "#66d9ef",
		Accent: "#e6db74", Dim: "#49483e", Text: "#f8f8f2",
	},
	"tokyonight": {
		Name: "tokyonight", Correct: "#9ece6a", Incorrect: "#f7768e", Extra: "#f7768e",
		Upcoming: "#565f89", Cursor: "#c0caf5", Title: "#bb9af7", Subtitle: "#7aa2f7",
		Accent: "#e0af68", Dim: "#3b4261", Text: "#c0caf5",
	},
}

func ThemeNames() []string {
	return []string{"catppuccin", "dracula", "nord", "gruvbox", "monokai", "tokyonight"}
}
