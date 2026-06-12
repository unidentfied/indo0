package middleware

import (
	"net/http"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
)

type rateBucket struct {
	count   int
	resetAt time.Time
}

// RateLimiter is a sliding-window counter per key.
type RateLimiter struct {
	mu      sync.Mutex
	buckets map[string]*rateBucket
	limit   int
	window  time.Duration
}

func newRateLimiter(limit int, window time.Duration) *RateLimiter {
	rl := &RateLimiter{
		buckets: make(map[string]*rateBucket),
		limit:   limit,
		window:  window,
	}
	go rl.reapLoop()
	return rl
}

func (rl *RateLimiter) reapLoop() {
	ticker := time.NewTicker(rl.window)
	defer ticker.Stop()
	for range ticker.C {
		rl.mu.Lock()
		now := time.Now()
		for k, b := range rl.buckets {
			if now.After(b.resetAt) {
				delete(rl.buckets, k)
			}
		}
		rl.mu.Unlock()
	}
}

func (rl *RateLimiter) allow(key string) bool {
	rl.mu.Lock()
	defer rl.mu.Unlock()

	now := time.Now()
	b, ok := rl.buckets[key]
	if !ok || now.After(b.resetAt) {
		rl.buckets[key] = &rateBucket{count: 1, resetAt: now.Add(rl.window)}
		return true
	}
	if b.count >= rl.limit {
		return false
	}
	b.count++
	return true
}

// IPRateLimit returns gin middleware that enforces per-IP request limits.
// 100 req/min per IP by default. Callers pass their own limit/window.
func IPRateLimit(reqPerWindow int, window time.Duration) gin.HandlerFunc {
	rl := newRateLimiter(reqPerWindow, window)
	return func(c *gin.Context) {
		key := "ip:" + c.ClientIP()
		if !rl.allow(key) {
			c.AbortWithStatusJSON(http.StatusTooManyRequests, gin.H{
				"error":       "rate_limit_exceeded",
				"retry_after": int(window.Seconds()),
			})
			return
		}
		c.Next()
	}
}

// InternalRateLimit returns gin middleware for internal-service callers
// identified by the X-Internal-Token header.  Non-internal requests pass
// through without rate limiting from this middleware.
func InternalRateLimit(reqPerWindow int, window time.Duration) gin.HandlerFunc {
	rl := newRateLimiter(reqPerWindow, window)
	return func(c *gin.Context) {
		token := c.GetHeader("X-Internal-Token")
		if token == "" {
			c.Next()
			return
		}
		key := "internal:" + token
		if !rl.allow(key) {
			c.AbortWithStatusJSON(http.StatusTooManyRequests, gin.H{
				"error": "internal_rate_limit_exceeded",
			})
			return
		}
		c.Next()
	}
}
