package db

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

func severityThreshold(severityMin string) []string {
	switch strings.ToLower(severityMin) {
	case "critical":
		return []string{"critical"}
	case "warning":
		return []string{"critical", "warning"}
	default:
		return []string{"critical", "warning", "advisory"}
	}
}

// AlertInPolygon is one alert row returned by the spatial query.
type AlertInPolygon struct {
	ID                 string          `json:"id"`
	Title              string          `json:"title"`
	Level              string          `json:"level"`
	Category           string          `json:"category"`
	Description        string          `json:"description"`
	Location           json.RawMessage `json:"location"`
	CreatedAt          time.Time       `json:"created_at"`
	Confidence         float64         `json:"confidence"`
	DataSourcesUsed    []string        `json:"data_sources_used"`
	MissingDataWarning *string         `json:"missing_data_warning"`
}

// HeatmapCell is a single grid cell in the stress heatmap response.
type HeatmapCell struct {
	Cell      json.RawMessage `json:"geometry"`
	Stress    int             `json:"stress"`
	NodeCount int             `json:"node_count"`
}

// NearestAsset is a single nearest-asset result row.
type NearestAsset struct {
	ID          string          `json:"id"`
	SystemType  string          `json:"system_type"`
	NodeName    string          `json:"node_name"`
	Geometry    json.RawMessage `json:"geometry"`
	DistanceM   float64         `json:"distance_m"`
	CurrentLoad float64         `json:"current_load"`
	Capacity    float64         `json:"capacity"`
	Status      string          `json:"status"`
}

// ---------------------------------------------------------------------------
// GetAlertsInPolygon returns alerts whose location falls inside the GeoJSON
// polygon, filtered by minimum severity level.  Uses the GIST index on
// alerts(location) for sub-100 ms response.
// ---------------------------------------------------------------------------
func GetAlertsInPolygon(ctx context.Context, p *pgxpool.Pool, geojsonPolygon string, severityMin string) ([]AlertInPolygon, error) {
	levels := severityThreshold(severityMin)

	query := `
		SELECT
			a.id,
			a.title,
			a.level,
			a.category,
			COALESCE(a.description, ''),
			COALESCE(ST_AsGeoJSON(a.location)::jsonb, 'null'::jsonb),
			a.created_at
		FROM alerts a
		WHERE ST_Within(a.location::geometry, ST_GeomFromGeoJSON($1))
		  AND a.level = ANY($2)
		  AND a.resolved_at IS NULL
		ORDER BY a.created_at DESC
		LIMIT 200;
	`

	rows, err := RetryRows(ctx, p, "GetAlertsInPolygon", query, geojsonPolygon, levels)
	if err != nil {
		return nil, fmt.Errorf("GetAlertsInPolygon: %w", err)
	}
	defer rows.Close()

	var alerts []AlertInPolygon
	for rows.Next() {
		var a AlertInPolygon
		if err := rows.Scan(&a.ID, &a.Title, &a.Level, &a.Category, &a.Description, &a.Location, &a.CreatedAt); err != nil {
			return nil, fmt.Errorf("GetAlertsInPolygon scan: %w", err)
		}
		alerts = append(alerts, a)
	}
	return alerts, rows.Err()
}

// ---------------------------------------------------------------------------
// GetStressHeatmap returns a GeoJSON FeatureCollection of grid cells with
// stress values (0-100) for a given infrastructure_type within the bounding
// box.  Uses GIST index on infrastructure_nodes(location) and ST_SquareGrid
// for cell generation.  Sub-100 ms target for 200–500 m grid cells.
// ---------------------------------------------------------------------------
func GetStressHeatmap(ctx context.Context, p *pgxpool.Pool, minLng, minLat, maxLng, maxLat float64, infraType string) ([]HeatmapCell, error) {
	query := `
		WITH bbox AS (
			SELECT ST_MakeEnvelope($1, $2, $3, $4, 4326)::geometry AS geom
		),
		grid AS (
			SELECT (ST_SquareGrid(
				GREATEST(($4 - $1) / 50, 0.001),
				bbox.geom
			)).geom AS cell
			FROM bbox
		),
		cell_nodes AS (
			SELECT
				grid.cell,
				n.current_load,
				n.capacity
			FROM grid
			INNER JOIN infrastructure_nodes n
				ON ST_Within(n.location::geometry, grid.cell)
				AND n.system_type = $5
				AND n.status = 'active'
		),
		aggregated AS (
			SELECT
				cell,
				GREATEST(0, LEAST(100,
					(AVG(current_load) / NULLIF(AVG(capacity), 0)) * 100
				))::INT AS stress,
				COUNT(*)::INT AS node_count
			FROM cell_nodes
			GROUP BY cell
		)
		SELECT
			ST_AsGeoJSON(cell)::jsonb,
			stress,
			node_count
		FROM aggregated
		ORDER BY stress DESC
		LIMIT 500;
	`

	rows, err := RetryRows(ctx, p, "GetStressHeatmap", query, minLng, minLat, maxLng, maxLat, infraType)
	if err != nil {
		return nil, fmt.Errorf("GetStressHeatmap: %w", err)
	}
	defer rows.Close()

	var cells []HeatmapCell
	for rows.Next() {
		var c HeatmapCell
		if err := rows.Scan(&c.Cell, &c.Stress, &c.NodeCount); err != nil {
			return nil, fmt.Errorf("GetStressHeatmap scan: %w", err)
		}
		cells = append(cells, c)
	}
	return cells, rows.Err()
}

// ---------------------------------------------------------------------------
// FindNearestAsset returns the closest water/power/road assets within the
// given radius (meters) from a lat/lon point.  Uses the geography <-> KNN
// operator for sub-100 ms response.
// ---------------------------------------------------------------------------
func FindNearestAsset(ctx context.Context, p *pgxpool.Pool, lat, lng, radiusM float64) ([]NearestAsset, error) {
	query := `
		SELECT
			n.id,
			n.system_type,
			n.node_name,
			ST_AsGeoJSON(n.location::geometry)::jsonb,
			ST_Distance(n.location, ST_GeogFromText($1))::numeric(10,1) AS distance_m,
			COALESCE(n.current_load, 0),
			COALESCE(n.capacity, 0),
			n.status
		FROM infrastructure_nodes n
		WHERE ST_DWithin(n.location, ST_GeogFromText($1), $2)
		ORDER BY n.location <-> ST_GeogFromText($1)
		LIMIT 20;
	`

	pointWKT := fmt.Sprintf("POINT(%f %f)", lng, lat)
	rows, err := RetryRows(ctx, p, "FindNearestAsset", query, pointWKT, radiusM)
	if err != nil {
		return nil, fmt.Errorf("FindNearestAsset: %w", err)
	}
	defer rows.Close()

	var assets []NearestAsset
	for rows.Next() {
		var a NearestAsset
		if err := rows.Scan(&a.ID, &a.SystemType, &a.NodeName, &a.Geometry, &a.DistanceM, &a.CurrentLoad, &a.Capacity, &a.Status); err != nil {
			return nil, fmt.Errorf("FindNearestAsset scan: %w", err)
		}
		assets = append(assets, a)
	}
	return assets, rows.Err()
}
