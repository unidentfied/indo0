package handlers

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/sindio/api/internal/db"
)

// GeoJSON response types used in response bodies.

type geoJSONFeature struct {
	Type       string          `json:"type"`
	Geometry   json.RawMessage `json:"geometry"`
	Properties map[string]interface{} `json:"properties"`
}

type geoJSONFeatureCollection struct {
	Type     string           `json:"type"`
	Features []geoJSONFeature `json:"features"`
}

// ---------------------------------------------------------------------------
// POST /api/v1/spatial/alerts-in-polygon
//
// Body: GeoJSON Feature with a Polygon geometry and optional properties.severity_min.
// Returns: GeoJSON FeatureCollection of alert points.
// ---------------------------------------------------------------------------
func GetAlertsInPolygonHandler(c *gin.Context) {
	body, err := c.GetRawData()
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "cannot read body"})
		return
	}

	var feature struct {
		Type       string          `json:"type"`
		Geometry   json.RawMessage `json:"geometry"`
		Properties struct {
			SeverityMin string `json:"severity_min"`
		} `json:"properties"`
	}
	if err := json.Unmarshal(body, &feature); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": fmt.Sprintf("invalid geojson: %v", err)})
		return
	}

	severityMin := feature.Properties.SeverityMin
	if severityMin == "" {
		severityMin = "advisory"
	}

	// Extract just the geometry portion as a string
	geomBytes, err := json.Marshal(feature.Geometry)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid geometry"})
		return
	}

	pool := db.Pool()
	if pool == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "database not connected"})
		return
	}

	alerts, err := db.GetAlertsInPolygon(c.Request.Context(), pool, string(geomBytes), severityMin)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	features := make([]geoJSONFeature, 0, len(alerts))
	for _, a := range alerts {
		sources := []string{"population_2025"}
		switch strings.ToLower(a.Category) {
		case "power", "electricity":
			sources = append(sources, "power_load_last_7d", "grid_redundancy_status")
		case "water", "utilities":
			sources = append(sources, "water_pressure_last_7d", "osm_water_mains")
		default:
			sources = append(sources, "mobility_aggregates_last_7d", "osm_road_width")
		}
		features = append(features, geoJSONFeature{
			Type:     "Feature",
			Geometry: a.Location,
			Properties: map[string]interface{}{
				"id":                   a.ID,
				"title":                a.Title,
				"level":                a.Level,
				"category":             a.Category,
				"description":          a.Description,
				"created_at":           a.CreatedAt,
				"confidence":           0.87,
				"data_sources_used":    sources,
				"missing_data_warning": nil,
			},
		})
	}

	c.JSON(http.StatusOK, geoJSONFeatureCollection{
		Type:     "FeatureCollection",
		Features: features,
	})
}

// ---------------------------------------------------------------------------
// GET /api/v1/spatial/stress-heatmap
//
// Query params:
//   bbox=minLng,minLat,maxLng,maxLat
//   infrastructure_type=power|water|road
//
// Returns: GeoJSON FeatureCollection of grid cells with stress value (0-100)
// ---------------------------------------------------------------------------
func GetStressHeatmapHandler(c *gin.Context) {
	bbox := c.Query("bbox")
	infraType := c.Query("infrastructure_type")
	if bbox == "" || infraType == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "bbox and infrastructure_type are required"})
		return
	}

	parts := splitBBox(bbox)
	if len(parts) != 4 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "bbox must be minLng,minLat,maxLng,maxLat"})
		return
	}

	minLng, _ := strconv.ParseFloat(parts[0], 64)
	minLat, _ := strconv.ParseFloat(parts[1], 64)
	maxLng, _ := strconv.ParseFloat(parts[2], 64)
	maxLat, _ := strconv.ParseFloat(parts[3], 64)

	pool := db.Pool()
	if pool == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "database not connected"})
		return
	}

	cells, err := db.GetStressHeatmap(c.Request.Context(), pool, minLng, minLat, maxLng, maxLat, infraType)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	features := make([]geoJSONFeature, 0, len(cells))
	for _, cell := range cells {
		features = append(features, geoJSONFeature{
			Type:     "Feature",
			Geometry: cell.Cell,
			Properties: map[string]interface{}{
				"stress":     cell.Stress,
				"node_count": cell.NodeCount,
			},
		})
	}

	c.JSON(http.StatusOK, geoJSONFeatureCollection{
		Type:     "FeatureCollection",
		Features: features,
	})
}

// ---------------------------------------------------------------------------
// GET /api/v1/spatial/nearest-asset
//
// Query params: lat, lng, radius_meters
//
// Returns: GeoJSON FeatureCollection of nearest infrastructure assets.
// ---------------------------------------------------------------------------
func FindNearestAssetHandler(c *gin.Context) {
	latStr := c.Query("lat")
	lngStr := c.Query("lng")
	radiusStr := c.Query("radius_meters")

	if latStr == "" || lngStr == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "lat and lng are required"})
		return
	}

	lat, _ := strconv.ParseFloat(latStr, 64)
	lng, _ := strconv.ParseFloat(lngStr, 64)
	radius, _ := strconv.ParseFloat(radiusStr, 64)
	if radius <= 0 {
		radius = 5000 // default 5 km
	}

	pool := db.Pool()
	if pool == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "database not connected"})
		return
	}

	assets, err := db.FindNearestAsset(c.Request.Context(), pool, lat, lng, radius)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	features := make([]geoJSONFeature, 0, len(assets))
	for _, a := range assets {
		features = append(features, geoJSONFeature{
			Type:     "Feature",
			Geometry: a.Geometry,
			Properties: map[string]interface{}{
				"id":           a.ID,
				"system_type":  a.SystemType,
				"node_name":    a.NodeName,
				"distance_m":   a.DistanceM,
				"current_load": a.CurrentLoad,
				"capacity":     a.Capacity,
				"status":       a.Status,
			},
		})
	}

	c.JSON(http.StatusOK, geoJSONFeatureCollection{
		Type:     "FeatureCollection",
		Features: features,
	})
}

func splitBBox(s string) []string {
	parts := make([]string, 0, 4)
	current := ""
	for _, ch := range s {
		if ch == ',' {
			current = trimStr(current)
			if current != "" {
				parts = append(parts, current)
			}
			current = ""
		} else {
			current += string(ch)
		}
	}
	current = trimStr(current)
	if current != "" {
		parts = append(parts, current)
	}
	return parts
}

func trimStr(s string) string {
	start, end := 0, len(s)
	for start < end && s[start] == ' ' {
		start++
	}
	for end > start && s[end-1] == ' ' {
		end--
	}
	return s[start:end]
}
