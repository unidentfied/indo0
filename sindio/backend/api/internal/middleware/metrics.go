package middleware

import (
	"strconv"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

var (
	RequestDuration = promauto.NewHistogramVec(prometheus.HistogramOpts{
		Name:    "request_duration_seconds",
		Help:    "Histogram of HTTP request durations in seconds.",
		Buckets: prometheus.DefBuckets,
	}, []string{"method", "path", "status"})

	AlertsGeneratedTotal = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "alerts_generated_total",
		Help: "Total number of alerts generated, labelled by severity and category.",
	}, []string{"level", "category"})

	// Data quality gauges — updated by handlers when they fetch data
	DataQualityRealRatio = promauto.NewGaugeVec(prometheus.GaugeOpts{
		Name: "data_quality_real_data_ratio",
		Help: "Fraction of assets served from fresh real data (0–1).",
	}, []string{"infrastructure_type"})

	DataQualityMockRatio = promauto.NewGaugeVec(prometheus.GaugeOpts{
		Name: "data_quality_mock_fallback_ratio",
		Help: "Fraction of requests served from mock/fallback data (0–1).",
	}, []string{"infrastructure_type"})

	DataQualityModelConfidence = promauto.NewGaugeVec(prometheus.GaugeOpts{
		Name: "data_quality_model_confidence",
		Help: "Average model confidence score for the last inference batch (0–1).",
	}, []string{"infrastructure_type"})

	DataQualityFallbackTotal = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "data_quality_fallback_total",
		Help: "Total number of fallback/mock data events.",
	}, []string{"infrastructure_type", "source"})

	DataQualityRealFetchTotal = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "data_quality_real_fetch_total",
		Help: "Total number of successful real data fetches from external sources.",
	}, []string{"infrastructure_type", "source"})
)

// RecordAlert increments the alerts_generated_total counter.
func RecordAlert(level, category string) {
	AlertsGeneratedTotal.WithLabelValues(level, category).Inc()
}

// RecordRealFetch records a successful real data fetch.
func RecordRealFetch(infraType, source string) {
	DataQualityRealFetchTotal.WithLabelValues(infraType, source).Inc()
}

// RecordFallback records a fallback/mock data event.
func RecordFallback(infraType, source string) {
	DataQualityFallbackTotal.WithLabelValues(infraType, source).Inc()
}

// SetDataQualityRatio sets the real/mock ratio gauges for an infrastructure type.
func SetDataQualityRatio(infraType string, realRatio float64) {
	DataQualityRealRatio.WithLabelValues(infraType).Set(realRatio)
	DataQualityMockRatio.WithLabelValues(infraType).Set(1.0 - realRatio)
}

// SetModelConfidence sets the model confidence gauge for an infrastructure type.
func SetModelConfidence(infraType string, confidence float64) {
	DataQualityModelConfidence.WithLabelValues(infraType).Set(confidence)
}

// PrometheusMiddleware records request_duration_seconds for every request.
func PrometheusMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()
		c.Next()
		duration := time.Since(start).Seconds()
		status := strconv.Itoa(c.Writer.Status())
		path := c.FullPath()
		if path == "" {
			path = c.Request.URL.Path
		}
		RequestDuration.WithLabelValues(c.Request.Method, path, status).Observe(duration)
	}
}

// MetricsHandler returns an http.Handler that serves /metrics.
func MetricsHandler() gin.HandlerFunc {
	h := promhttp.Handler()
	return func(c *gin.Context) {
		h.ServeHTTP(c.Writer, c.Request)
	}
}
