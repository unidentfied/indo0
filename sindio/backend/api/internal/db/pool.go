package db

import (
	"context"
	"fmt"
	"log"
	"os"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

var pool *pgxpool.Pool

// InitPool creates the pgx connection pool from environment variables.
// Expected env: DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD.
// Falls back to defaults matching the docker-compose services.
func InitPool(ctx context.Context) (*pgxpool.Pool, error) {
	host := envOrDefault("DB_HOST", "localhost")
	port := envOrDefault("DB_PORT", "5432")
	name := envOrDefault("DB_NAME", "sindio")
	user := envOrDefault("DB_USER", "sindio_user")
	pass := envOrDefault("DB_PASSWORD", "")
	poolMin := envOrDefault("DB_POOL_MIN", "2")
	poolMax := envOrDefault("DB_POOL_MAX", "10")

	dsn := fmt.Sprintf(
		"postgres://%s:%s@%s:%s/%s?sslmode=disable&pool_min_conns=%s&pool_max_conns=%s",
		user, pass, host, port, name, poolMin, poolMax,
	)

	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		return nil, fmt.Errorf("pgxpool parse: %w", err)
	}
	cfg.MaxConnLifetime = 30 * time.Minute
	cfg.HealthCheckPeriod = 30 * time.Second

	pool, err = pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return nil, fmt.Errorf("pgxpool create: %w", err)
	}

	if err := pool.Ping(ctx); err != nil {
		pool.Close()
		return nil, fmt.Errorf("pgxpool ping: %w", err)
	}

	log.Printf("pgx pool connected to %s:%s/%s (min=%s max=%s)", host, port, name, poolMin, poolMax)
	return pool, nil
}

// Pool returns the global connection pool. Returns nil if not initialized.
func Pool() *pgxpool.Pool {
	return pool
}

// ClosePool shuts down the connection pool.
func ClosePool() {
	if pool != nil {
		pool.Close()
	}
}

func envOrDefault(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}
