package handlers

import (
	"log"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/gorilla/websocket"
	"github.com/sindio/api/internal/middleware"
)

var upgrader = websocket.Upgrader{
	ReadBufferSize:  1024,
	WriteBufferSize: 1024,
	CheckOrigin: func(r *http.Request) bool {
		return true // Allow all origins in development
	},
}

// RedisClient abstracts the Redis pub/sub interface.
type RedisClient interface {
	Subscribe(channel string) PubSub
}

// PubSub abstracts a Redis PubSub subscription.
type PubSub interface {
	Channel() <-chan string
	Close() error
}

// LiveAlertsWS handles WS /api/v1/live — upgrades to WebSocket and streams
// real-time alerts.  If a RedisClient is provided it subscribes to the
// "sindio:alerts:live" channel; otherwise it falls back to periodic mock
// alerts.
func LiveAlertsWS(redisClient RedisClient) gin.HandlerFunc {
	return func(c *gin.Context) {
		conn, err := upgrader.Upgrade(c.Writer, c.Request, nil)
		if err != nil {
			log.Printf("websocket upgrade error: %v", err)
			return
		}
		defer conn.Close()

		done := make(chan struct{})

		// Read pump — handle client close
		go func() {
			defer close(done)
			for {
				if _, _, err := conn.ReadMessage(); err != nil {
					return
				}
			}
		}()

		// Write pump — stream alerts
		if redisClient != nil {
			streamFromRedis(conn, redisClient, done)
		} else {
			streamMockAlerts(conn, done)
		}
	}
}

func streamFromRedis(conn *websocket.Conn, client RedisClient, done <-chan struct{}) {
	pubsub := client.Subscribe("sindio:alerts:live")
	defer pubsub.Close()

	ch := pubsub.Channel()
	ticker := time.NewTicker(5 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-done:
			return
		case msg, ok := <-ch:
			if !ok {
				return
			}
			if err := conn.WriteMessage(websocket.TextMessage, []byte(msg)); err != nil {
				return
			}
		case <-ticker.C:
			if err := conn.WriteMessage(websocket.PingMessage, nil); err != nil {
				return
			}
		}
	}
}

func streamMockAlerts(conn *websocket.Conn, done <-chan struct{}) {
	mockMessages := []string{
		`{"id":"ALT-WS-001","timestamp":"09:42:15 AM","level":"critical","category":"electricity","infrastructure_type":"power","ward":"Kilimani","title":"Transformer 4-A thermal overload","description":"Cooling system failure detected.","lat":-1.2900,"lng":36.7850,"severity_score":94.0,"confidence":0.91,"data_sources_used":["population_2025","power_load_last_7d","grid_redundancy_status"],"missing_data_warning":"No real-time power data for last 6 hours, used historic average"}`,
		`{"id":"ALT-WS-002","timestamp":"09:45:00 AM","level":"warning","category":"water","infrastructure_type":"water","ward":"Upper Hill","title":"Pressure fluctuation in zone B","description":"Cyclic pressure drop every 90s.","lat":-1.2975,"lng":36.8122,"severity_score":60.0,"confidence":0.83,"data_sources_used":["population_2025","water_pressure_last_7d","osm_water_mains"],"missing_data_warning":null}`,
		`{"id":"ALT-WS-003","timestamp":"09:47:30 AM","level":"critical","category":"roads","infrastructure_type":"roads","ward":"CBD","title":"Bridge 7 structural alert","description":"Strain gauge reading exceeds design threshold.","lat":-1.2833,"lng":36.8219,"severity_score":87.0,"confidence":0.89,"data_sources_used":["population_2025","mobility_aggregates_last_7d","osm_road_width"],"missing_data_warning":"Mobility stream delayed by 15 minutes, using last available aggregate"}`,
		`{"id":"ALT-WS-004","timestamp":"09:50:00 AM","level":"advisory","category":"traffic","infrastructure_type":"roads","ward":"Westlands","title":"Route 23 diverted","description":"Accident clearance in progress.","lat":-1.2670,"lng":36.8090,"severity_score":35.0,"confidence":0.78,"data_sources_used":["population_2025","mobility_aggregates_last_7d","osm_road_width"],"missing_data_warning":null}`,
		`{"id":"ALT-WS-005","timestamp":"09:52:00 AM","level":"warning","category":"electricity","infrastructure_type":"power","ward":"Industrial Area","title":"Grid frequency deviation","description":"Frequency at 49.92 Hz.","lat":-1.3200,"lng":36.8500,"severity_score":71.0,"confidence":0.87,"data_sources_used":["population_2025","power_load_last_7d","grid_redundancy_status"],"missing_data_warning":null}`,
	}

	idx := 0
	ticker := time.NewTicker(3 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-done:
			return
		case <-ticker.C:
			msg := mockMessages[idx%len(mockMessages)]
			idx++
			if err := conn.WriteMessage(websocket.TextMessage, []byte(msg)); err != nil {
				return
			}
			middleware.RecordAlert("info", "ws_stream")
		}
	}
}
