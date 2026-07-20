package localstate

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"time"
)

const DraftEvidenceThreshold = 3

type LearnedRule struct {
	ID         int64
	DraftID    int64
	Failure    string
	Correction string
	Action     string
	Enabled    bool
	CreatedAt  time.Time
	UpdatedAt  time.Time
}

func (s *Store) ListReviewableDrafts(ctx context.Context) ([]Draft, error) {
	if s == nil || s.database == nil {
		return nil, errors.New("local state store is closed")
	}
	rows, err := s.database.QueryContext(ctx, `SELECT id, normalized_failure, normalized_correction, evidence_count, created_at, updated_at FROM learned_rule_drafts WHERE evidence_count >= ? ORDER BY updated_at, id`, DraftEvidenceThreshold)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var drafts []Draft
	for rows.Next() {
		var draft Draft
		var createdAt, updatedAt int64
		if err := rows.Scan(&draft.ID, &draft.NormalizedFailure, &draft.NormalizedCorrection, &draft.EvidenceCount, &createdAt, &updatedAt); err != nil {
			return nil, err
		}
		draft.CreatedAt = time.Unix(createdAt, 0).UTC()
		draft.UpdatedAt = time.Unix(updatedAt, 0).UTC()
		drafts = append(drafts, draft)
	}
	return drafts, rows.Err()
}

func (s *Store) ActivateDraft(ctx context.Context, draftID int64, action string) (LearnedRule, error) {
	if !validAction(action) {
		return LearnedRule{}, errors.New("learned rule action must be off, hint, or rewrite")
	}
	if draftID < 1 {
		return LearnedRule{}, errors.New("learned rule draft id is invalid")
	}
	transaction, err := s.database.BeginTx(ctx, nil)
	if err != nil {
		return LearnedRule{}, err
	}
	defer transaction.Rollback()
	var evidenceCount int
	var rule LearnedRule
	if err := transaction.QueryRowContext(ctx, `SELECT normalized_failure, normalized_correction, evidence_count FROM learned_rule_drafts WHERE id = ?`, draftID).Scan(&rule.Failure, &rule.Correction, &evidenceCount); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return LearnedRule{}, fmt.Errorf("learned rule draft %d does not exist", draftID)
		}
		return LearnedRule{}, err
	}
	if evidenceCount < DraftEvidenceThreshold {
		return LearnedRule{}, fmt.Errorf("learned rule draft %d has insufficient evidence", draftID)
	}
	now := time.Now().UTC()
	result, err := transaction.ExecContext(ctx, `INSERT INTO learned_rules(draft_id, action, enabled, created_at, updated_at) VALUES (?, ?, 1, ?, ?) ON CONFLICT(draft_id) DO UPDATE SET action = excluded.action, enabled = 1, updated_at = excluded.updated_at`, draftID, action, now.Unix(), now.Unix())
	if err != nil {
		return LearnedRule{}, err
	}
	rule.ID, err = result.LastInsertId()
	if err != nil {
		return LearnedRule{}, err
	}
	if rule.ID == 0 {
		if err := transaction.QueryRowContext(ctx, `SELECT id FROM learned_rules WHERE draft_id = ?`, draftID).Scan(&rule.ID); err != nil {
			return LearnedRule{}, err
		}
	}
	rule.DraftID = draftID
	rule.Action = action
	rule.Enabled = true
	rule.CreatedAt = now
	rule.UpdatedAt = now
	if err := transaction.Commit(); err != nil {
		return LearnedRule{}, err
	}
	return rule, nil
}

func (s *Store) ListActiveRules(ctx context.Context) ([]LearnedRule, error) {
	if s == nil || s.database == nil {
		return nil, errors.New("local state store is closed")
	}
	rows, err := s.database.QueryContext(ctx, `SELECT rules.id, rules.draft_id, drafts.normalized_failure, drafts.normalized_correction, rules.action, rules.enabled, rules.created_at, rules.updated_at FROM learned_rules AS rules JOIN learned_rule_drafts AS drafts ON drafts.id = rules.draft_id WHERE rules.enabled = 1 ORDER BY rules.id`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var rules []LearnedRule
	for rows.Next() {
		var rule LearnedRule
		var enabled int
		var createdAt, updatedAt int64
		if err := rows.Scan(&rule.ID, &rule.DraftID, &rule.Failure, &rule.Correction, &rule.Action, &enabled, &createdAt, &updatedAt); err != nil {
			return nil, err
		}
		rule.Enabled = enabled == 1
		rule.CreatedAt = time.Unix(createdAt, 0).UTC()
		rule.UpdatedAt = time.Unix(updatedAt, 0).UTC()
		rules = append(rules, rule)
	}
	return rules, rows.Err()
}

func (s *Store) UpdateDraft(ctx context.Context, draftID int64, failure, correction string) (Draft, error) {
	if draftID < 1 || failure == "" || correction == "" {
		return Draft{}, errors.New("learned rule draft id failure and correction are required")
	}
	now := time.Now().UTC()
	result, err := s.database.ExecContext(ctx, `UPDATE learned_rule_drafts SET normalized_failure = ?, normalized_correction = ?, updated_at = ? WHERE id = ?`, failure, correction, now.Unix(), draftID)
	if err != nil {
		return Draft{}, err
	}
	changed, err := result.RowsAffected()
	if err != nil {
		return Draft{}, err
	}
	if changed != 1 {
		return Draft{}, fmt.Errorf("learned rule draft %d does not exist", draftID)
	}
	return s.DraftFor(ctx, failure, correction)
}

func (s *Store) SetRuleAction(ctx context.Context, ruleID int64, action string) error {
	if ruleID < 1 || !validAction(action) {
		return errors.New("learned rule id and action are invalid")
	}
	result, err := s.database.ExecContext(ctx, `UPDATE learned_rules SET action = ?, updated_at = ? WHERE id = ?`, action, time.Now().UTC().Unix(), ruleID)
	if err != nil {
		return err
	}
	changed, err := result.RowsAffected()
	if err != nil {
		return err
	}
	if changed != 1 {
		return fmt.Errorf("learned rule %d does not exist", ruleID)
	}
	return nil
}

func (s *Store) SetRuleEnabled(ctx context.Context, ruleID int64, enabled bool) error {
	if ruleID < 1 {
		return errors.New("learned rule id is invalid")
	}
	value := 0
	if enabled {
		value = 1
	}
	result, err := s.database.ExecContext(ctx, `UPDATE learned_rules SET enabled = ?, updated_at = ? WHERE id = ?`, value, time.Now().UTC().Unix(), ruleID)
	if err != nil {
		return err
	}
	changed, err := result.RowsAffected()
	if err != nil {
		return err
	}
	if changed != 1 {
		return fmt.Errorf("learned rule %d does not exist", ruleID)
	}
	return nil
}

func (s *Store) DeleteRule(ctx context.Context, ruleID int64) error {
	if ruleID < 1 {
		return errors.New("learned rule id is invalid")
	}
	result, err := s.database.ExecContext(ctx, `DELETE FROM learned_rules WHERE id = ?`, ruleID)
	if err != nil {
		return err
	}
	changed, err := result.RowsAffected()
	if err != nil {
		return err
	}
	if changed != 1 {
		return fmt.Errorf("learned rule %d does not exist", ruleID)
	}
	return nil
}

func (s *Store) PurgeLearning(ctx context.Context) error {
	transaction, err := s.database.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer transaction.Rollback()
	for _, query := range []string{`DELETE FROM learned_rules`, `DELETE FROM learned_rule_drafts`, `DELETE FROM observations`} {
		if _, err := transaction.ExecContext(ctx, query); err != nil {
			return err
		}
	}
	return transaction.Commit()
}

func validAction(action string) bool {
	return action == "off" || action == "hint" || action == "rewrite"
}
