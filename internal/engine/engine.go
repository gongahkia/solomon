package engine

import (
	"math"
	"time"
)

type CharStatus int

const (
	Upcoming CharStatus = iota
	Correct
	Incorrect
	Extra
	Missed
)

type TrackedChar struct {
	Expected rune
	Typed    rune
	Status   CharStatus
}

type Word struct {
	Chars []TrackedChar
	Extra []TrackedChar
	Done  bool
}

type Result struct {
	NetWPM      float64
	RawWPM      float64
	Accuracy    float64
	Correct     int
	Incorrect   int
	ExtraCount  int
	Missed      int
	Consistency float64
	Mode        string
	Duration    time.Duration
	WordCount   int
	Timestamp   time.Time
}

type snapshot struct {
	chars int
	ts    time.Time
}

type Engine struct {
	Words       []Word
	WordIdx     int
	CharIdx     int
	startTime   time.Time
	endTime     time.Time
	started     bool
	Finished    bool
	mode        string
	targetWords int
	snapshots   []snapshot
}

func New(words []string, mode string, targetWords int) *Engine {
	e := &Engine{mode: mode, targetWords: targetWords}
	for _, w := range words {
		word := Word{}
		for _, c := range w {
			word.Chars = append(word.Chars, TrackedChar{Expected: c, Status: Upcoming})
		}
		e.Words = append(e.Words, word)
	}
	return e
}

func (e *Engine) start() {
	if !e.started {
		e.started = true
		e.startTime = time.Now()
	}
}

func (e *Engine) TypeChar(c rune) {
	if e.Finished || e.WordIdx >= len(e.Words) {
		return
	}
	e.start()
	w := &e.Words[e.WordIdx]
	if e.CharIdx < len(w.Chars) {
		tc := &w.Chars[e.CharIdx]
		tc.Typed = c
		if c == tc.Expected {
			tc.Status = Correct
		} else {
			tc.Status = Incorrect
		}
		e.CharIdx++
	} else { // extra chars beyond word length
		w.Extra = append(w.Extra, TrackedChar{Typed: c, Status: Extra})
		e.CharIdx++
	}
}

func (e *Engine) Backspace() {
	if e.Finished || e.WordIdx >= len(e.Words) {
		return
	}
	w := &e.Words[e.WordIdx]
	if e.CharIdx <= 0 {
		return
	}
	e.CharIdx--
	if e.CharIdx < len(w.Chars) { // backspace into normal chars
		tc := &w.Chars[e.CharIdx]
		tc.Typed = 0
		tc.Status = Upcoming
	} else { // backspace into extra chars
		if len(w.Extra) > 0 {
			w.Extra = w.Extra[:len(w.Extra)-1]
		}
	}
}

func (e *Engine) BackspaceWord() {
	if e.Finished || e.WordIdx >= len(e.Words) {
		return
	}
	w := &e.Words[e.WordIdx]
	w.Extra = nil
	for i := range w.Chars {
		w.Chars[i].Typed = 0
		w.Chars[i].Status = Upcoming
	}
	e.CharIdx = 0
}

func (e *Engine) NextWord() {
	if e.Finished || e.WordIdx >= len(e.Words) {
		return
	}
	e.start()
	w := &e.Words[e.WordIdx]
	for i := e.CharIdx; i < len(w.Chars); i++ {
		if w.Chars[i].Status == Upcoming {
			w.Chars[i].Status = Missed
		}
	}
	w.Done = true
	e.WordIdx++
	e.CharIdx = 0
	if e.mode == "words" && e.WordIdx >= e.targetWords {
		e.Finish()
	}
}

func (e *Engine) Elapsed() time.Duration {
	if !e.started {
		return 0
	}
	if e.Finished {
		return e.endTime.Sub(e.startTime)
	}
	return time.Since(e.startTime)
}

func (e *Engine) Started() bool { return e.started }

func (e *Engine) charCounts() (correct, incorrect, extra, missed int) {
	for i := 0; i <= e.WordIdx && i < len(e.Words); i++ {
		w := &e.Words[i]
		for _, c := range w.Chars {
			switch c.Status {
			case Correct:
				correct++
			case Incorrect:
				incorrect++
			case Missed:
				missed++
			}
		}
		extra += len(w.Extra)
	}
	return
}

func (e *Engine) CurrentWPM() float64 {
	elapsed := e.Elapsed().Minutes()
	if elapsed <= 0 {
		return 0
	}
	correct, incorrect, extra, _ := e.charCounts()
	raw := float64(correct+incorrect+extra) / 5.0 / elapsed
	uncorrected := float64(incorrect+extra) / elapsed
	net := raw - uncorrected
	if net < 0 {
		return 0
	}
	return net
}

func (e *Engine) CurrentRawWPM() float64 {
	elapsed := e.Elapsed().Minutes()
	if elapsed <= 0 {
		return 0
	}
	correct, incorrect, extra, _ := e.charCounts()
	return float64(correct+incorrect+extra) / 5.0 / elapsed
}

func (e *Engine) CurrentAccuracy() float64 {
	correct, incorrect, extra, missed := e.charCounts()
	total := correct + incorrect + extra + missed
	if total == 0 {
		return 100.0
	}
	return float64(correct) / float64(total) * 100.0
}

func (e *Engine) RecordSnapshot() {
	if !e.started || e.Finished {
		return
	}
	correct, _, _, _ := e.charCounts()
	e.snapshots = append(e.snapshots, snapshot{chars: correct, ts: time.Now()})
}

func (e *Engine) consistency() float64 {
	if len(e.snapshots) < 2 {
		return 100.0
	}
	var wpms []float64
	for i := 1; i < len(e.snapshots); i++ {
		dt := e.snapshots[i].ts.Sub(e.snapshots[i-1].ts).Minutes()
		if dt <= 0 {
			continue
		}
		dc := float64(e.snapshots[i].chars - e.snapshots[i-1].chars)
		wpms = append(wpms, dc/5.0/dt)
	}
	if len(wpms) < 2 {
		return 100.0
	}
	var sum float64
	for _, w := range wpms {
		sum += w
	}
	mean := sum / float64(len(wpms))
	var variance float64
	for _, w := range wpms {
		d := w - mean
		variance += d * d
	}
	variance /= float64(len(wpms))
	sd := math.Sqrt(variance)
	if mean <= 0 {
		return 100.0
	}
	cv := sd / mean * 100.0 // coefficient of variation
	cons := 100.0 - cv
	if cons < 0 {
		cons = 0
	}
	return cons
}

func (e *Engine) Finish() Result {
	if !e.started {
		e.startTime = time.Now()
	}
	e.Finished = true
	e.endTime = time.Now()
	// mark remaining chars in current word as missed
	if e.WordIdx < len(e.Words) {
		w := &e.Words[e.WordIdx]
		for i := e.CharIdx; i < len(w.Chars); i++ {
			if w.Chars[i].Status == Upcoming {
				w.Chars[i].Status = Missed
			}
		}
	}
	correct, incorrect, extra, missed := e.charCounts()
	elapsed := e.endTime.Sub(e.startTime)
	mins := elapsed.Minutes()
	var rawWPM, netWPM float64
	if mins > 0 {
		rawWPM = float64(correct+incorrect+extra) / 5.0 / mins
		uncorrected := float64(incorrect+extra) / mins
		netWPM = rawWPM - uncorrected
		if netWPM < 0 {
			netWPM = 0
		}
	}
	acc := 100.0
	total := correct + incorrect + extra + missed
	if total > 0 {
		acc = float64(correct) / float64(total) * 100.0
	}
	return Result{
		NetWPM:      math.Round(netWPM*100) / 100,
		RawWPM:      math.Round(rawWPM*100) / 100,
		Accuracy:    math.Round(acc*100) / 100,
		Correct:     correct,
		Incorrect:   incorrect,
		ExtraCount:  extra,
		Missed:      missed,
		Consistency: math.Round(e.consistency()*100) / 100,
		Mode:        e.mode,
		Duration:    elapsed,
		WordCount:   e.WordIdx,
		Timestamp:   time.Now(),
	}
}

func (e *Engine) CharsTyped() int {
	correct, incorrect, extra, _ := e.charCounts()
	return correct + incorrect + extra
}

func (e *Engine) TotalChars() int {
	total := 0
	for _, w := range e.Words {
		total += len(w.Chars)
	}
	return total
}
