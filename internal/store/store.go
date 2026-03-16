package store

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"time"
)

type TestResult struct {
	ID          string  `json:"id"`
	Mode        string  `json:"mode"`
	Param       int     `json:"param"`
	WordList    string  `json:"word_list"`
	NetWPM      float64 `json:"net_wpm"`
	RawWPM      float64 `json:"raw_wpm"`
	Accuracy    float64 `json:"accuracy"`
	Correct     int     `json:"correct"`
	Incorrect   int     `json:"incorrect"`
	Extra       int     `json:"extra"`
	Missed      int     `json:"missed"`
	Consistency float64 `json:"consistency"`
	Timestamp   string  `json:"timestamp"`
}

type storeData struct {
	Results []TestResult       `json:"results"`
	PBs     map[string]float64 `json:"pbs"`
}

type Store struct {
	data     storeData
	filepath string
}

func dir() string {
	d, err := os.UserConfigDir()
	if err != nil {
		d = os.Getenv("HOME")
	}
	return filepath.Join(d, "monke")
}

func Open() (*Store, error) {
	d := dir()
	if err := os.MkdirAll(d, 0755); err != nil {
		return nil, err
	}
	fp := filepath.Join(d, "results.json")
	s := &Store{filepath: fp, data: storeData{PBs: make(map[string]float64)}}
	raw, err := os.ReadFile(fp)
	if err != nil {
		if os.IsNotExist(err) {
			return s, nil
		}
		return nil, err
	}
	if err := json.Unmarshal(raw, &s.data); err != nil {
		return s, nil // corrupted file, start fresh
	}
	if s.data.PBs == nil {
		s.data.PBs = make(map[string]float64)
	}
	return s, nil
}

func (s *Store) Save() error {
	raw, err := json.MarshalIndent(s.data, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(s.filepath, raw, 0644)
}

func (s *Store) AddResult(r TestResult) bool {
	s.data.Results = append(s.data.Results, r)
	key := fmt.Sprintf("%s_%d", r.Mode, r.Param)
	prev, ok := s.data.PBs[key]
	isPB := !ok || r.NetWPM > prev
	if isPB {
		s.data.PBs[key] = r.NetWPM
	}
	return isPB
}

func (s *Store) LastN(n int) []TestResult {
	if n >= len(s.data.Results) {
		return s.data.Results
	}
	return s.data.Results[len(s.data.Results)-n:]
}

func (s *Store) BestWPM(mode string, param int) float64 {
	key := fmt.Sprintf("%s_%d", mode, param)
	return s.data.PBs[key]
}

func (s *Store) AccuracyTrend(n int) []float64 {
	results := s.LastN(n)
	out := make([]float64, len(results))
	for i, r := range results {
		out[i] = r.Accuracy
	}
	return out
}

func (s *Store) ResultCount() int { return len(s.data.Results) }

func NewTestResult(mode string, param int, wordList string, netWPM, rawWPM, accuracy float64, correct, incorrect, extra, missed int, consistency float64) TestResult {
	return TestResult{
		ID:          fmt.Sprintf("%d", time.Now().UnixNano()),
		Mode:        mode,
		Param:       param,
		WordList:    wordList,
		NetWPM:      netWPM,
		RawWPM:      rawWPM,
		Accuracy:    accuracy,
		Correct:     correct,
		Incorrect:   incorrect,
		Extra:       extra,
		Missed:      missed,
		Consistency: consistency,
		Timestamp:   time.Now().Format(time.RFC3339),
	}
}
