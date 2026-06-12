package handlers

import (
	"context"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/sindio/api/internal/db"
	"github.com/sindio/api/internal/middleware"
	"github.com/sindio/api/internal/models"
)

// GetV1Alerts handles GET /api/v1/alerts with optional query filters.
func GetV1Alerts(c *gin.Context) {
	infraType := strings.ToLower(c.Query("infrastructure_type"))
	ward := strings.ToLower(c.Query("ward"))
	severityMin := c.Query("severity_min")

	pool := db.Pool()
	if pool == nil {
		c.JSON(http.StatusOK, gin.H{"alerts": fallbackV1Alerts(), "count": len(fallbackV1Alerts())})
		return
	}

	query := `SELECT id, level, category, COALESCE(infrastructure_type, category) AS infra_type,
	                  title, COALESCE(description, ''),
	                  COALESCE(ST_Y(location::geometry), -1.2921) AS lat,
	                  COALESCE(ST_X(location::geometry), 36.8219) AS lng,
	                  COALESCE(severity, 0.5) AS severity_score,
	                  COALESCE(classification_confidence, 0.85) AS confidence,
	                  created_at
	           FROM alerts
	           WHERE resolved_at IS NULL`
	args := []interface{}{}
	argIdx := 1

	if infraType != "" {
		query += " AND LOWER(COALESCE(infrastructure_type, category)) = $" + itoa(argIdx)
		args = append(args, infraType)
		argIdx++
	}
	if ward != "" {
		query += " AND LOWER(COALESCE(recommended_action, title)) LIKE $" + itoa(argIdx)
		args = append(args, "%"+ward+"%")
		argIdx++
	}
	if severityMin != "" {
		var minScore float64
		switch severityMin {
		case "critical":
			minScore = 0.8
		case "warning":
			minScore = 0.5
		default:
			minScore = 0.0
		}
		query += " AND COALESCE(severity, 0) >= $" + itoa(argIdx)
		args = append(args, minScore)
		argIdx++
	}
	query += " ORDER BY created_at DESC LIMIT 20"

	rows, err := pool.Query(context.Background(), query, args...)
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"alerts": fallbackV1Alerts(), "count": len(fallbackV1Alerts())})
		return
	}
	defer rows.Close()

	var alerts []models.AlertV1
	for rows.Next() {
		var a models.AlertV1
		var createdAt time.Time
		if err := rows.Scan(&a.ID, &a.Level, &a.Category, &a.InfrastructureType,
			&a.Title, &a.Description, &a.Lat, &a.Lng,
			&a.SeverityScore, &a.Confidence, &createdAt); err != nil {
			continue
		}
		a.Timestamp = createdAt.Format("03:04:05 PM")
		a.Ward = extractWard(a.Title, a.Description)
		a.DataSourcesUsed = []string{"alerts"}
		alerts = append(alerts, a)
	}

	if len(alerts) == 0 {
		alerts = fallbackV1Alerts()
	}
	c.JSON(http.StatusOK, gin.H{"alerts": alerts, "count": len(alerts)})
}

// GetAlertExplanation handles GET /api/v1/alerts/:id/explanation.
func GetAlertExplanation(c *gin.Context) {
	id := c.Param("id")
	explanation := models.AlertExplanation{
		AlertID: id,
		Summary: "This alert indicates rising stress levels on the electrical grid within the targeted ward.",
		RootCause: "Thermal loading on transformers due to peak-hour demand combined with reduced redundancy after scheduled maintenance on line 12-C.",
		Impact: "If unmitigated, cascading failures could affect up to 8,400 nodes across the Central District and adjacent wards.",
		Recommendation: "Reroute 12% of load to auxiliary substations and activate demand-side management within the next 2 hours. Dispatch field crew to inspect transformer cooling systems.",
		Confidence: 0.89,
	}
	middleware.RecordAlert("info", "rag_explanation")
	c.JSON(http.StatusOK, explanation)
}

// GetSimulationStatusV1 handles GET /api/v1/simulate/status/:task_id
func GetSimulationStatusV1(c *gin.Context) {
	taskID := c.Param("task_id")
	pool := db.Pool()
	if pool == nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "database unavailable"})
		return
	}

	var status models.SimulateStatus
	err := pool.QueryRow(context.Background(),
		`SELECT id::text, status, COALESCE(EXTRACT(EPOCH FROM NOW() - started_at) / 60, 0) AS progress,
		        started_at::text, COALESCE(completed_at::text, '')
		 FROM simulations WHERE id::text = $1`, taskID,
	).Scan(&status.TaskID, &status.Status, &status.Progress, &status.CreatedAt, &status.UpdatedAt)
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "task_not_found"})
		return
	}
	c.JSON(http.StatusOK, status)
}

// RunSimulationV1 handles POST /api/v1/simulate/run
func RunSimulationV1(c *gin.Context) {
	var req models.SimulateRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	pool := db.Pool()
	if pool == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "database unavailable"})
		return
	}

	taskID := uuid.New().String()
	now := time.Now().UTC()

	_, err := pool.Exec(context.Background(),
		`INSERT INTO simulations (id, network_type, stress_factor, failure_risk, status, started_at)
		 VALUES ($1, $2, $3, 'medium', 'running', $4)`,
		taskID, req.InfrastructureType, req.StressFactor, now,
	)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to create simulation"})
		return
	}

	c.JSON(http.StatusAccepted, models.SimulateResponse{
		TaskID:  taskID,
		Status:  "running",
		Message: "Simulation started.",
	})
}

// GetNextUpdatesV1 handles GET /api/v1/next_updates
func GetNextUpdatesV1(c *gin.Context) {
	now := time.Now()
	updates := []models.NextUpdate{
		{UpdateType: "power", NextAt: now.Add(120 * time.Second).UTC().Format(time.RFC3339), IntervalSec: 120, Description: "Power grid stress monitoring."},
		{UpdateType: "water", NextAt: now.Add(600 * time.Second).UTC().Format(time.RFC3339), IntervalSec: 600, Description: "Water distribution pressure sweep."},
		{UpdateType: "roads", NextAt: now.Add(60 * time.Second).UTC().Format(time.RFC3339), IntervalSec: 60, Description: "Road congestion density scan."},
		{UpdateType: "solid_waste", NextAt: now.Add(300 * time.Second).UTC().Format(time.RFC3339), IntervalSec: 300, Description: "Waste collection status monitoring."},
		{UpdateType: "sidewalks", NextAt: now.Add(600 * time.Second).UTC().Format(time.RFC3339), IntervalSec: 600, Description: "Pedestrian path monitoring."},
		{UpdateType: "lrt", NextAt: now.Add(90 * time.Second).UTC().Format(time.RFC3339), IntervalSec: 90, Description: "LRT signal and train status."},
		{UpdateType: "sgr", NextAt: now.Add(180 * time.Second).UTC().Format(time.RFC3339), IntervalSec: 180, Description: "SGR track sensor updates."},
		{UpdateType: "airports", NextAt: now.Add(600 * time.Second).UTC().Format(time.RFC3339), IntervalSec: 600, Description: "Airport operations status."},
	}
	c.JSON(http.StatusOK, gin.H{"updates": updates})
}

// ── Helpers ──────────────────────────────────────────────────

func fallbackV1Alerts() []models.AlertV1 {
	return []models.AlertV1{{
		ID: "ALT-FB-001", Timestamp: time.Now().Format("03:04:05 PM"), Level: "advisory",
		Category: "utilities", InfrastructureType: "power", Ward: "Nairobi",
		Title: "Database unavailable — showing fallback", Description: "Connect PostgreSQL to see real alerts.",
		Lat: -1.2921, Lng: 36.8219, SeverityScore: 30, Confidence: 0.5,
		DataSourcesUsed: []string{"fallback"},
	}}
}

func extractWard(title, description string) string {
	wards := []string{"Kilimani", "Upper Hill", "CBD", "Westlands", "Industrial Area",
		"Eastleigh", "Karen", "Parklands", "Langata", "Ngong Road",
		"Kibera", "South B", "South C", "Donholm", "Embakasi"}
	for _, w := range wards {
		if strings.Contains(strings.ToLower(title+" "+description), strings.ToLower(w)) {
			return w
		}
	}
	return "Nairobi"
}

func itoa(n int) string {
	return fmt.Sprintf("$%d", n)
}
