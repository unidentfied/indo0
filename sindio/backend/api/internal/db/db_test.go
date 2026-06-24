package db

import (
	"context"
	"testing"
)

func TestInitPool_NoDB(t *testing.T) {
	t.Setenv("DB_HOST", "nonexistent-host")
	t.Setenv("DB_PORT", "5432")
	t.Setenv("DB_NAME", "test")
	t.Setenv("DB_USER", "test")
	t.Setenv("DB_PASSWORD", "test")

	ctx := context.Background()
	_, err := InitPool(ctx)
	if err == nil {
		t.Error("expected error connecting to nonexistent host")
	}
}
