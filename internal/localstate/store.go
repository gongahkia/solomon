package localstate

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"time"

	_ "modernc.org/sqlite"
)

const databaseName = "state.db"

type Store struct {
	database *sql.DB
}

type Observation struct {
	ID               int64
	Session          string
	FailedCommand    string
	CorrectedCommand string
	FailureOutput    string
	CreatedAt        time.Time
}

type Draft struct {
	ID                   int64
	NormalizedFailure    string
	NormalizedCorrection string
	EvidenceCount        int
	CreatedAt            time.Time
	UpdatedAt            time.Time
}

func Open(directory string) (*Store, error) {
	if directory == "" || !filepath.IsAbs(directory) {
		return nil, errors.New("local state directory must be absolute")
	}
	if err := os.MkdirAll(directory, 0o700); err != nil {
		return nil, err
	}
	info, err := os.Lstat(directory)
	if err != nil {
		return nil, err
	}
	if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return nil, errors.New("local state directory is not a real directory")
	}
	if err := os.Chmod(directory, 0o700); err != nil {
		return nil, err
	}
	path := filepath.Join(directory, databaseName)
	database, err := sql.Open("sqlite", "file:"+path+"?_pragma=busy_timeout(5000)&_pragma=foreign_keys(1)")
	if err != nil {
		return nil, err
	}
	database.SetMaxOpenConns(1)
	store := &Store{database: database}
	if err := store.migrate(context.Background()); err != nil {
		database.Close()
		return nil, err
	}
	if err := os.Chmod(path, 0o600); err != nil {
		database.Close()
		return nil, err
	}
	return store, nil
}

func (s *Store) Close() error {
	if s == nil || s.database == nil {
		return nil
	}
	return s.database.Close()
}

func (s *Store) RecordObservation(ctx context.Context, observation Observation) (Observation, error) {
	if s == nil || s.database == nil {
		return Observation{}, errors.New("local state store is closed")
	}
	if observation.Session == "" || observation.FailedCommand == "" || observation.CorrectedCommand == "" {
		return Observation{}, errors.New("learning observation requires session failed command and corrected command")
	}
	if observation.CreatedAt.IsZero() {
		observation.CreatedAt = time.Now().UTC()
	}
	result, err := s.database.ExecContext(ctx, `INSERT INTO observations(session, failed_command, corrected_command, failure_output, created_at) VALUES (?, ?, ?, ?, ?)`, observation.Session, observation.FailedCommand, observation.CorrectedCommand, observation.FailureOutput, observation.CreatedAt.Unix())
	if err != nil {
		return Observation{}, err
	}
	observation.ID, err = result.LastInsertId()
	if err != nil {
		return Observation{}, err
	}
	return observation, nil
}

func (s *Store) DeleteObservationsBefore(ctx context.Context, cutoff time.Time) (int64, error) {
	if s == nil || s.database == nil {
		return 0, errors.New("local state store is closed")
	}
	result, err := s.database.ExecContext(ctx, `DELETE FROM observations WHERE created_at < ?`, cutoff.UTC().Unix())
	if err != nil {
		return 0, err
	}
	return result.RowsAffected()
}

func (s *Store) RecordLearningPair(ctx context.Context, observation Observation) (Draft, error) {
	if _, err := s.RecordObservation(ctx, observation); err != nil {
		return Draft{}, err
	}
	now := observation.CreatedAt
	if now.IsZero() {
		now = time.Now().UTC()
	}
	transaction, err := s.database.BeginTx(ctx, nil)
	if err != nil {
		return Draft{}, err
	}
	defer transaction.Rollback()
	var draft Draft
	var createdAt int64
	err = transaction.QueryRowContext(ctx, `SELECT id, evidence_count, created_at FROM learned_rule_drafts WHERE normalized_failure = ? AND normalized_correction = ?`, observation.FailedCommand, observation.CorrectedCommand).Scan(&draft.ID, &draft.EvidenceCount, &createdAt)
	switch {
	case err == nil:
		draft.CreatedAt = time.Unix(createdAt, 0).UTC()
		draft.EvidenceCount++
		draft.UpdatedAt = now
		if _, err := transaction.ExecContext(ctx, `UPDATE learned_rule_drafts SET evidence_count = ?, updated_at = ? WHERE id = ?`, draft.EvidenceCount, now.Unix(), draft.ID); err != nil {
			return Draft{}, err
		}
	case errors.Is(err, sql.ErrNoRows):
		result, err := transaction.ExecContext(ctx, `INSERT INTO learned_rule_drafts(normalized_failure, normalized_correction, evidence_count, created_at, updated_at) VALUES (?, ?, 1, ?, ?)`, observation.FailedCommand, observation.CorrectedCommand, now.Unix(), now.Unix())
		if err != nil {
			return Draft{}, err
		}
		draft.ID, err = result.LastInsertId()
		if err != nil {
			return Draft{}, err
		}
		draft.EvidenceCount = 1
		draft.CreatedAt = now
		draft.UpdatedAt = now
	default:
		return Draft{}, err
	}
	draft.NormalizedFailure = observation.FailedCommand
	draft.NormalizedCorrection = observation.CorrectedCommand
	if draft.UpdatedAt.IsZero() {
		draft.UpdatedAt = now
	}
	if err := transaction.Commit(); err != nil {
		return Draft{}, err
	}
	return draft, nil
}

func (s *Store) DraftFor(ctx context.Context, failure, correction string) (Draft, error) {
	if s == nil || s.database == nil {
		return Draft{}, errors.New("local state store is closed")
	}
	var draft Draft
	var createdAt, updatedAt int64
	err := s.database.QueryRowContext(ctx, `SELECT id, evidence_count, created_at, updated_at FROM learned_rule_drafts WHERE normalized_failure = ? AND normalized_correction = ?`, failure, correction).Scan(&draft.ID, &draft.EvidenceCount, &createdAt, &updatedAt)
	if err != nil {
		return Draft{}, err
	}
	draft.NormalizedFailure = failure
	draft.NormalizedCorrection = correction
	draft.CreatedAt = time.Unix(createdAt, 0).UTC()
	draft.UpdatedAt = time.Unix(updatedAt, 0).UTC()
	return draft, nil
}

func (s *Store) migrate(ctx context.Context) error {
	var version int
	if err := s.database.QueryRowContext(ctx, `PRAGMA user_version`).Scan(&version); err != nil {
		return err
	}
	if version > 1 {
		return fmt.Errorf("unsupported local state schema version %d", version)
	}
	if version == 1 {
		return nil
	}
	transaction, err := s.database.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer transaction.Rollback()
	for _, statement := range []string{
		`CREATE TABLE observations (id INTEGER PRIMARY KEY, session TEXT NOT NULL, failed_command TEXT NOT NULL, corrected_command TEXT NOT NULL, failure_output TEXT NOT NULL, created_at INTEGER NOT NULL)`,
		`CREATE INDEX observations_session_created_at ON observations(session, created_at)`,
		`CREATE TABLE learned_rule_drafts (id INTEGER PRIMARY KEY, normalized_failure TEXT NOT NULL, normalized_correction TEXT NOT NULL, evidence_count INTEGER NOT NULL, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, UNIQUE(normalized_failure, normalized_correction))`,
		`CREATE TABLE learned_rules (id INTEGER PRIMARY KEY, draft_id INTEGER NOT NULL UNIQUE REFERENCES learned_rule_drafts(id), action TEXT NOT NULL, enabled INTEGER NOT NULL, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL)`,
		`PRAGMA user_version = 1`,
	} {
		if _, err := transaction.ExecContext(ctx, statement); err != nil {
			return err
		}
	}
	return transaction.Commit()
}
