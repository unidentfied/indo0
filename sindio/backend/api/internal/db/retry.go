package db

import (
	"context"
	"fmt"
	"log"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

const (
	defaultRetries     = 3
	defaultBackoffBase = 1 * time.Second
)

func isRetriablePG(err error) bool {
	if err == nil {
		return false
	}
	msg := err.Error()
	for _, pat := range []string{
		"connection refused",
		"connection reset",
		"connection closed",
		"i/o timeout",
		"EOF",
		"broken pipe",
		"no such host",
		"too many clients",
		"cannot assign requested address",
	} {
		if strings.Contains(msg, pat) {
			return true
		}
	}
	return false
}

// RetryRows executes a pgxpool query with up to 3 retries (1s, 2s, 4s
// back-off) on transient connection errors.  Returns the rows result or
// the last error — never panics.
func RetryRows(
	ctx context.Context,
	p *pgxpool.Pool,
	label string,
	query string,
	args ...any,
) (pgx.Rows, error) {
	var lastErr error
	for attempt := 1; attempt <= defaultRetries; attempt++ {
		rows, err := p.Query(ctx, query, args...)
		if err == nil {
			return rows, nil
		}
		lastErr = err
		if !isRetriablePG(err) {
			return nil, fmt.Errorf("%s: %w", label, err)
		}
		delay := defaultBackoffBase * (1 << (attempt - 1))
		log.Printf("[warn] %s — attempt %d/%d failed (%v). Retrying in %v…",
			label, attempt, defaultRetries, err, delay)
		select {
		case <-ctx.Done():
			return nil, fmt.Errorf("%s: context cancelled: %w", label, ctx.Err())
		case <-time.After(delay):
		}
	}
	log.Printf("[warn] %s — all %d retries exhausted (last: %v).", label, defaultRetries, lastErr)
	return nil, fmt.Errorf("%s: %w", label, lastErr)
}
