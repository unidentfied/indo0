package main

import (
	"context"
	"log"
	"os"
	"time"

	"github.com/gin-contrib/cors"
	"github.com/gin-gonic/gin"
	"github.com/sindio/api/internal/db"
	"github.com/sindio/api/internal/handlers"
	"github.com/sindio/api/internal/middleware"
)

func main() {
	port := os.Getenv("API_PORT")
	if port == "" {
		port = "8080"
	}

	// --- database ---
	ctx := context.Background()
	pool, err := db.InitPool(ctx)
	if err != nil {
		log.Printf("WARNING: database not available — spatial endpoints will return 503: %v", err)
	} else {
		defer pool.Close()
	}

	gin.SetMode(gin.ReleaseMode)
	r := gin.New()

	// --- global middleware ---
	r.Use(gin.Recovery())
	r.Use(middleware.PrometheusMiddleware())

	corsConfig := cors.DefaultConfig()
	corsConfig.AllowOrigins = []string{"http://localhost:3000"}
	corsConfig.AllowMethods = []string{"GET", "POST", "PUT", "DELETE", "OPTIONS"}
	corsConfig.AllowHeaders = []string{"Origin", "Content-Type", "Accept", "Authorization", "X-Internal-Token"}
	r.Use(cors.New(corsConfig))

	// --- v0 legacy routes (unauthenticated, available to frontend proxy) ---
	v0 := r.Group("/api")
	{
		v0.GET("/health", handlers.HealthCheck)
		v0.GET("/health/ready", handlers.HealthReady)
		v0.GET("/dashboard/metrics", handlers.GetMetrics)
		v0.GET("/dashboard/alerts", handlers.GetAlerts)
		v0.GET("/infrastructure/:system", handlers.GetInfrastructure)
		v0.POST("/simulations/run", handlers.RunSimulation)
		v0.GET("/simulations/status", handlers.GetSimulationStatus)
	}

	// --- v1 API gateway routes (authenticated + rate limited) ---
	v1 := r.Group("/api/v1")
	v1.Use(middleware.JWTAuth())
	v1.Use(middleware.IPRateLimit(100, 1*time.Minute))
	v1.Use(middleware.InternalRateLimit(1000, 1*time.Minute))
	{
		v1.GET("/alerts", handlers.GetV1Alerts)
		v1.GET("/alerts/:id/explanation", handlers.GetAlertExplanation)
		v1.POST("/simulate/run", handlers.RunSimulationV1)
		v1.GET("/simulate/status/:task_id", handlers.GetSimulationStatusV1)
		v1.GET("/next_updates", handlers.GetNextUpdatesV1)
		v1.GET("/live", handlers.LiveAlertsWS(nil))
		v1.GET("/explain_spacing", handlers.ExplainSpacing)

		// --- spatial / map endpoints (pgx + PostGIS) ---
		spatial := v1.Group("/spatial")
		{
			spatial.POST("/alerts-in-polygon", handlers.GetAlertsInPolygonHandler)
			spatial.GET("/stress-heatmap", handlers.GetStressHeatmapHandler)
			spatial.GET("/nearest-asset", handlers.FindNearestAssetHandler)
		}
	}

	// --- Prometheus metrics endpoint (unauthenticated, internal) ---
	r.GET("/metrics", middleware.MetricsHandler())

	log.Printf("Sindio API gateway (Go) listening on :%s", port)
	log.Printf("  v0 (legacy): /api/*")
	log.Printf("  v1 (gateway): /api/v1/*  [JWT + rate-limited]")
	log.Printf("  spatial:      /api/v1/spatial/*  [PostGIS queries]")
	log.Printf("  metrics:      /metrics")
	if err := r.Run(":" + port); err != nil {
		log.Fatalf("Failed to start server: %v", err)
	}
}
