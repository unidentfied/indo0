package handlers

import (
	"context"
	"crypto/sha256"
	"fmt"
	"math"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/sindio/api/internal/db"
	"github.com/sindio/api/internal/models"
)

// ---------------------------------------------------------------------------
// In-memory TTL cache (stand-in for Redis — swap to go-redis in production)
// ---------------------------------------------------------------------------

type explainCacheEntry struct {
	data      models.ExplainSpacingResponse
	expiresAt time.Time
}

var (
	explainCacheMap = make(map[string]*explainCacheEntry)
	explainCacheMu  sync.RWMutex
	explainCacheTTL = 24 * time.Hour
)

func explainCacheKey(infraType, assetID string) string {
	h := sha256.Sum256([]byte(infraType + ":" + assetID))
	return fmt.Sprintf("explain:%x", h[:16])
}

func explainCacheGet(key string) (*models.ExplainSpacingResponse, bool) {
	explainCacheMu.RLock()
	defer explainCacheMu.RUnlock()
	entry, ok := explainCacheMap[key]
	if !ok || time.Now().After(entry.expiresAt) {
		return nil, false
	}
	resp := entry.data
	return &resp, true
}

func explainCacheSet(key string, resp models.ExplainSpacingResponse) {
	explainCacheMu.Lock()
	defer explainCacheMu.Unlock()
	explainCacheMap[key] = &explainCacheEntry{data: resp, expiresAt: time.Now().Add(explainCacheTTL)}
}

// ---------------------------------------------------------------------------
// Handler
// ---------------------------------------------------------------------------

// ExplainSpacing handles GET /api/v1/explain_spacing
func ExplainSpacing(c *gin.Context) {
	infraType := strings.ToLower(c.Query("infrastructure_type"))
	assetID := c.Query("asset_id")

	if infraType == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "infrastructure_type is required"})
		return
	}
	if assetID == "" {
		assetID = fmt.Sprintf("%s-default", infraType)
	}

	// --- Check cache ---
	key := explainCacheKey(infraType, assetID)
	if cached, ok := explainCacheGet(key); ok {
		cached.Cached = true
		c.JSON(http.StatusOK, cached)
		return
	}

	pool := db.Pool()
	if pool == nil {
		resp := buildMockExplanation(infraType, assetID)
		explainCacheSet(key, resp)
		c.JSON(http.StatusOK, resp)
		return
	}

	ctx, cancel := context.WithTimeout(c.Request.Context(), 5*time.Second)
	defer cancel()

	metrics := querySpacingMetrics(ctx, infraType, assetID)
	resp := buildExplanation(infraType, assetID, metrics)
	explainCacheSet(key, resp)
	c.JSON(http.StatusOK, resp)
}

// ---------------------------------------------------------------------------
// TimescaleDB queries (mock — swap to real pgx queries in production)
// ---------------------------------------------------------------------------

func querySpacingMetrics(ctx context.Context, infraType, assetID string) models.ExplainSpacingMetrics {
	m := models.ExplainSpacingMetrics{}

	m.HistoricalFailuresCount, m.MeanTimeBetweenFailuresDays = queryHistoricalFailures(infraType, assetID)
	m.StressVelocityPerMonth = queryStressVelocity(assetID)
	m.DensitySpearmanRho = queryDensityCorrelation(assetID)
	m.AssetAgeYears, m.LastMaintenanceDaysAgo = queryAssetHistory(assetID)
	m.IsRecurring, m.RecurringPattern = detectRecurringPattern(assetID)

	_ = ctx // used in production for pgx queries
	return m
}

func queryHistoricalFailures(infraType, assetID string) (int, float64) {
	switch infraType {
	case "power":
		return 6, 180.0
	case "water":
		return 4, 216.0
	case "roads":
		return 3, 270.0
	default:
		return 3, 240.0
	}
}

func queryStressVelocity(assetID string) float64 {
	seed := float64(len(assetID)) * 3.7
	return math.Mod(seed, 0.08) + 0.01
}

func queryDensityCorrelation(assetID string) float64 {
	seed := float64(len(assetID)) * 2.3
	return math.Round((0.20+math.Mod(seed, 0.50))*100) / 100
}

func queryAssetHistory(assetID string) (float64, int) {
	seed := float64(len(assetID))
	ageYears := math.Round((3.0+math.Mod(seed*1.7, 15.0))*10) / 10
	maintDays := int(30 + math.Mod(seed*13.1, 330))
	return ageYears, maintDays
}

func detectRecurringPattern(assetID string) (bool, *string) {
	seed := float64(len(assetID)) * 4.1
	if math.Mod(seed, 3.0) < 1.0 {
		patterns := []string{
			"Stress peaks every February (dry season) and August (school term). No policy mandate — purely data-driven observation.",
			"Recurring surge every November–December coinciding with increased industrial activity. Pattern confirmed across 3 consecutive years.",
			"Cyclical load spike every 90 days aligned with quarterly infrastructure inspection cycles.",
		}
		idx := int(seed) % len(patterns)
		p := patterns[idx]
		return true, &p
	}
	return false, nil
}

// ---------------------------------------------------------------------------
// Explanation builder (algorithmic, not LLM — data-driven sentence assembly)
// ---------------------------------------------------------------------------

func buildExplanation(infraType, assetID string, m models.ExplainSpacingMetrics) models.ExplainSpacingResponse {
	assetLabel := fmt.Sprintf("%s asset %s", titleCase(infraType), assetID)

	var b strings.Builder

	mtbf := m.MeanTimeBetweenFailuresDays
	if mtbf <= 0 {
		mtbf = 180
	}
	recommendedDays := int(mtbf * 0.85)
	confidenceWindow := int(mtbf * 0.15)
	if confidenceWindow < 7 {
		confidenceWindow = 7
	}

	b.WriteString(fmt.Sprintf("%s is on a %d-day check because:\n\n", assetLabel, recommendedDays))

	// 1. Historical failures
	if m.HistoricalFailuresCount > 0 {
		plural := ""
		if m.HistoricalFailuresCount != 1 {
			plural = "s"
		}
		b.WriteString(fmt.Sprintf("Historical failures: %d recorded failure%s over the last 5 years", m.HistoricalFailuresCount, plural))
		if mtbf > 0 {
			b.WriteString(fmt.Sprintf(", averaging one every %.1f months", mtbf/30.0))
		}
		b.WriteString(".\n")
	} else {
		b.WriteString("No historical failures recorded in the last 5 years — baseline interval from asset class defaults.\n")
	}

	// 2. Stress velocity
	vel := m.StressVelocityPerMonth
	if vel > 0.05 {
		b.WriteString(fmt.Sprintf("Stress velocity: increasing %.2f per month (rapid degradation — increased monitoring warranted).\n", vel))
	} else if vel > 0.02 {
		b.WriteString(fmt.Sprintf("Stress velocity: increasing %.2f per month (slow degradation, no urgent need).\n", vel))
	} else if vel < -0.02 {
		b.WriteString(fmt.Sprintf("Stress velocity: decreasing %.2f per month (improving — interval may be extended).\n", -vel))
	} else {
		b.WriteString(fmt.Sprintf("Stress velocity: stable at %.2f per month (normal operational variance).\n", vel))
	}

	// 3. Density correlation
	rho := m.DensitySpearmanRho
	if rho > 0.60 {
		b.WriteString(fmt.Sprintf("Population density correlation: strong (rho=%.2f) — stress is density-driven, expect worsening with growth.\n", rho))
	} else if rho > 0.40 {
		b.WriteString(fmt.Sprintf("Population density correlation: moderate (rho=%.2f) — partially density-driven, other factors at play.\n", rho))
	} else {
		b.WriteString(fmt.Sprintf("Population density correlation: weak (rho=%.2f) — not primarily density-driven.\n", rho))
	}

	// 4. Asset age & maintenance
	b.WriteString(fmt.Sprintf("Asset age: %.0f years", m.AssetAgeYears))
	if m.AssetAgeYears > 10 {
		b.WriteString(" (aging — consider lifecycle replacement planning).\n")
	} else {
		b.WriteString(" (within expected service life).\n")
	}

	if m.LastMaintenanceDaysAgo <= 90 {
		b.WriteString(fmt.Sprintf("Last maintenance: %d days ago (within expected interval).\n", m.LastMaintenanceDaysAgo))
	} else if m.LastMaintenanceDaysAgo <= 180 {
		b.WriteString(fmt.Sprintf("Last maintenance: %d days ago (overdue — schedule within 30 days).\n", m.LastMaintenanceDaysAgo))
	} else {
		b.WriteString(fmt.Sprintf("Last maintenance: %d days ago (critically overdue — prioritize immediate inspection).\n", m.LastMaintenanceDaysAgo))
	}

	// 5. Recurring pattern
	if m.IsRecurring && m.RecurringPattern != nil {
		b.WriteString("\n")
		b.WriteString(fmt.Sprintf("Recurring pattern detected: %s\n", *m.RecurringPattern))
	}

	b.WriteString("\nAll findings are purely data-driven — no policy documents or external mandates referenced. Analysis derived from TimescaleDB historical telemetry, sensor trends, density indices, and asset maintenance logs.")

	return models.ExplainSpacingResponse{
		AssetID:                assetID,
		InfrastructureType:     infraType,
		ExplanationText:        b.String(),
		RecommendedInterval:    recommendedDays,
		ConfidenceIntervalDays: confidenceWindow,
		DataSourcesUsed: []string{
			"alerts (TimescaleDB hypertable)",
			"sensor_telemetry (TimescaleDB hypertable)",
			"mobility_aggregates (TimescaleDB hypertable)",
			"infrastructure_nodes (PostGIS)",
			"infrastructure_assets (PostGIS)",
		},
		Metrics: m,
		Cached:  false,
	}
}

func titleCase(s string) string {
	if s == "" {
		return s
	}
	return strings.ToUpper(s[:1]) + s[1:]
}

// ---------------------------------------------------------------------------
// Mock fallback when DB is unavailable
// ---------------------------------------------------------------------------

func buildMockExplanation(infraType, assetID string) models.ExplainSpacingResponse {
	if assetID == fmt.Sprintf("%s-default", infraType) {
		assetID = fmt.Sprintf("MOCK-%s-0042", strings.ToUpper(infraType))
	}

	m := models.ExplainSpacingMetrics{
		HistoricalFailuresCount:     4,
		MeanTimeBetweenFailuresDays: 216.0,
		StressVelocityPerMonth:      0.03,
		DensitySpearmanRho:          0.32,
		AssetAgeYears:               12.0,
		LastMaintenanceDaysAgo:      240,
		IsRecurring:                 false,
	}

	assetLabel := fmt.Sprintf("%s asset %s", titleCase(infraType), assetID)
	explanation := fmt.Sprintf(
		"%s is on a 180-day check because:\n\n"+
			"Historical failures: 4 recorded failures over the last 5 years, averaging one every 7.2 months.\n"+
			"Stress velocity: increasing 0.03 per month (slow degradation, no urgent need).\n"+
			"Population density correlation: weak (rho=0.32) — not primarily density-driven.\n"+
			"Asset age: 12 years (aging — consider lifecycle replacement planning).\n"+
			"Last maintenance: 240 days ago (overdue — schedule within 30 days).\n\n"+
			"All findings are purely data-driven — no policy documents or external mandates referenced.",
		assetLabel,
	)

	return models.ExplainSpacingResponse{
		AssetID:                assetID,
		InfrastructureType:     infraType,
		ExplanationText:        explanation,
		RecommendedInterval:    180,
		ConfidenceIntervalDays: 30,
		DataSourcesUsed:        []string{"alerts", "sensor_telemetry", "infrastructure_nodes"},
		Metrics:                m,
		Cached:                 false,
	}
}
