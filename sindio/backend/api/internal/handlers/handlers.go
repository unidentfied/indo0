package handlers

import (
	"context"
	"fmt"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/sindio/api/internal/db"
	"github.com/sindio/api/internal/models"
)

func HealthCheck(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{
		"status":  "ok",
		"service": "sindio-api-go",
		"time":    time.Now().UTC().Format(time.RFC3339),
	})
}

func HealthReady(c *gin.Context) {
	pool := db.Pool()
	if pool == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{
			"status": "not ready",
			"reason": "database pool not initialized",
		})
		return
	}
	if err := pool.Ping(context.Background()); err != nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{
			"status": "not ready",
			"reason": "database unreachable: " + err.Error(),
		})
		return
	}
	c.JSON(http.StatusOK, gin.H{
		"status": "ready",
		"dependencies": gin.H{"postgres": "ok"},
	})
}

func RunSimulation(c *gin.Context) {
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
	_, err := pool.Exec(context.Background(),
		`INSERT INTO simulations (id, network_type, stress_factor, failure_risk, status, started_at)
		 VALUES ($1, $2, $3, 'medium', 'running', $4)`,
		taskID, req.InfrastructureType, req.StressFactor, time.Now().UTC(),
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

func GetSimulationStatus(c *gin.Context) {
	taskID := c.Param("task_id")
	pool := db.Pool()
	if pool == nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "database unavailable"})
		return
	}
	var status models.SimulateStatus
	err := pool.QueryRow(context.Background(),
		`SELECT id::text, status, 1.0 AS progress,
		        started_at::text, COALESCE(completed_at::text, '')
		 FROM simulations WHERE id::text = $1`, taskID,
	).Scan(&status.TaskID, &status.Status, &status.Progress, &status.CreatedAt, &status.UpdatedAt)
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "task_not_found"})
		return
	}
	c.JSON(http.StatusOK, status)
}

func GetMetrics(c *gin.Context) {
	pool := db.Pool()
	if pool == nil {
		c.JSON(http.StatusOK, fallbackMetrics())
		return
	}

	rows, err := pool.Query(context.Background(),
		`SELECT system_type, COUNT(*) AS total,
		        COUNT(*) FILTER (WHERE status = 'active') AS active,
		        COUNT(*) FILTER (WHERE status = 'degraded') AS degraded
		 FROM infrastructure_nodes
		 GROUP BY system_type
		 ORDER BY total DESC`)
	if err != nil {
		c.JSON(http.StatusOK, fallbackMetrics())
		return
	}
	defer rows.Close()

	var metrics []models.Metric
	for rows.Next() {
		var sysType string
		var total, active, degraded int
		if err := rows.Scan(&sysType, &total, &active, &degraded); err != nil {
			continue
		}
		stability := float64(active) / float64(total) * 100
		status := "good"
		if stability < 85 {
			status = "warning"
		}
		if stability < 70 {
			status = "critical"
		}
		metrics = append(metrics, models.Metric{
			Label:  displayName(sysType),
			Value:  fmt.Sprintf("%d/%d nodes active", active, total),
			Status: status,
		})
	}

	if len(metrics) == 0 {
		metrics = fallbackMetrics()
	}
	c.JSON(http.StatusOK, metrics)
}

func GetAlerts(c *gin.Context) {
	pool := db.Pool()
	if pool == nil {
		c.JSON(http.StatusOK, fallbackAlerts())
		return
	}

	rows, err := pool.Query(context.Background(),
		`SELECT id, level, category, title, COALESCE(description, ''),
		        COALESCE(ST_Y(location::geometry), 0) AS lat,
		        COALESCE(ST_X(location::geometry), 0) AS lng,
		        created_at
		 FROM alerts
		 WHERE resolved_at IS NULL
		 ORDER BY created_at DESC
		 LIMIT 20`)
	if err != nil {
		c.JSON(http.StatusOK, fallbackAlerts())
		return
	}
	defer rows.Close()

	var alerts []models.Alert
	for rows.Next() {
		var a models.Alert
		var lat, lng float64
		var createdAt time.Time
		if err := rows.Scan(&a.ID, &a.Level, &a.Category, &a.Title, &a.Description,
			&lat, &lng, &createdAt); err != nil {
			continue
		}
		a.Timestamp = createdAt.Format("03:04:05 PM")
		a.Location = fmt.Sprintf("%.4f, %.4f", lat, lng)
		a.Confidence = 0.85
		a.DataSourcesUsed = []string{"infrastructure_nodes", "alerts"}
		alerts = append(alerts, a)
	}

	if len(alerts) == 0 {
		alerts = fallbackAlerts()
	}
	c.JSON(http.StatusOK, alerts)
}

func GetInfrastructure(c *gin.Context) {
	system := c.Param("system")
	pool := db.Pool()

	if pool == nil {
		c.JSON(http.StatusOK, fallbackInfra(system))
		return
	}

	var status models.InfrastructureStatus
	err := pool.QueryRow(context.Background(),
		`SELECT
		    COUNT(*) AS active_nodes,
		    COALESCE(SUM(capacity), 0) AS total_capacity,
		    COALESCE(SUM(current_load), 0) AS total_load,
		    COUNT(*) FILTER (WHERE status = 'active')::FLOAT / GREATEST(COUNT(*), 1) * 100 AS stability,
		    COUNT(*) FILTER (WHERE status = 'degraded') AS degraded_count
		 FROM infrastructure_nodes
		 WHERE system_type = $1`, system).
		Scan(&status.ActiveNodes, &status.Capacity, &status.CurrentLoadRaw,
			&status.GridStability, &status.DegradedNodes)

	if err != nil {
		c.JSON(http.StatusOK, fallbackInfra(system))
		return
	}

	status.CurrentLoad = formatLoad(system, status.CurrentLoadRaw, status.Capacity)
	status.GridStability = float64(int(status.GridStability*10)) / 10
	status.RedundancyActive = status.DegradedNodes == 0
	if status.Capacity > 0 {
		status.CapacityPercent = float64(int(status.CurrentLoadRaw/status.Capacity*1000)) / 10
	}

	c.JSON(http.StatusOK, status)
}

// ── Helpers ──────────────────────────────────────────────────

func displayName(sysType string) string {
	names := map[string]string{
		"power": "Power Grid", "water": "Water Network", "roads": "Road Network",
		"solid_waste": "Solid Waste", "sidewalks": "Sidewalks",
		"lrt": "Light Rail", "sgr": "SGR Railway", "airports": "Airports",
	}
	if n, ok := names[sysType]; ok {
		return n
	}
	return sysType
}

func formatLoad(sysType string, load, capacity float64) string {
	pct := load / max(capacity, 1) * 100
	switch sysType {
	case "power":
		return fmt.Sprintf("%.1f GW (%.0f%%)", load/1000, pct)
	case "water":
		return fmt.Sprintf("%.0f m³/day (%.0f%%)", load, pct)
	case "roads":
		return fmt.Sprintf("%.0f veh/hr (%.0f%%)", load, pct)
	default:
		return fmt.Sprintf("%.0f (%.0f%%)", load, pct)
	}
}

// ── Fallbacks when DB is unreachable ──────────────────────────

func fallbackMetrics() []models.Metric {
	return []models.Metric{
		{Label: "Power Grid", Value: "50 nodes", Status: "good"},
		{Label: "Water Network", Value: "50 nodes", Status: "good"},
		{Label: "Road Network", Value: "50 nodes", Status: "good"},
		{Label: "Solid Waste", Value: "50 nodes", Status: "good"},
	}
}

func fallbackAlerts() []models.Alert {
	return []models.Alert{{
		ID: "ALT-FB-001", Timestamp: time.Now().Format("03:04:05 PM"),
		Level: "advisory", Category: "utilities",
		Title: "Database unavailable — showing fallback data",
		Description: "Connect PostgreSQL to see real alerts.",
		Location: "Nairobi", Confidence: 0.5,
		DataSourcesUsed: []string{"fallback"},
	}}
}

func fallbackInfra(system string) models.InfrastructureStatus {
	return models.InfrastructureStatus{
		GridStability: 95, ActiveNodes: 50,
		CurrentLoad: "unknown", RedundancyActive: true,
	}
}
