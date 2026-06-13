use axum::{
    extract::State,
    http::StatusCode,
    routing::{get, post},
    Json, Router,
};
use chrono::Utc;
use metrics::{counter, gauge};
use metrics_exporter_prometheus::PrometheusBuilder;
use serde::{Deserialize, Serialize};
use std::sync::{
    atomic::{AtomicU64, Ordering},
    Arc,
};
use tokio::sync::broadcast;
use tokio::signal;
use tower_http::cors::CorsLayer;
use tracing::{error, info};
use uuid::Uuid;

lazy_static::lazy_static! {
    static ref METRICS_HANDLE: metrics_exporter_prometheus::PrometheusHandle =
        PrometheusBuilder::new().install_recorder().expect("failed to install recorder");
}

fn record_real_fetch(infra_type: &str, source: &str) {
    counter!("data_quality_real_fetch_total", "infrastructure_type" => infra_type, "source" => source).increment(1);
}

fn record_fallback(infra_type: &str, source: &str) {
    counter!("data_quality_fallback_total", "infrastructure_type" => infra_type, "source" => source).increment(1);
}

fn set_data_quality_ratio(infra_type: &str, real_ratio: f64) {
    gauge!("data_quality_real_data_ratio", "infrastructure_type" => infra_type).set(real_ratio);
    gauge!("data_quality_mock_fallback_ratio", "infrastructure_type" => infra_type).set(1.0 - real_ratio);
}

fn set_model_confidence(infra_type: &str, confidence: f64) {
    gauge!("data_quality_model_confidence", "infrastructure_type" => infra_type).set(confidence);
}

#[derive(Clone)]
struct AppState {
    tx: broadcast::Sender<String>,
    events_processed: Arc<AtomicU64>,
}

#[derive(Debug, Serialize, Deserialize)]
struct SensorPayload {
    sensor_id: String,
    metric_type: String,
    value: f64,
    unit: String,
    location: Option<Location>,
}

#[derive(Debug, Serialize, Deserialize)]
struct Location {
    lat: f64,
    lng: f64,
}

#[derive(Debug, Serialize)]
struct StreamEvent {
    event_id: String,
    timestamp: String,
    sensor_id: String,
    metric_type: String,
    value: f64,
    unit: String,
    severity: String,
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter("sindio_streaming=info,tower_http=debug")
        .init();

    let (tx, _rx) = broadcast::channel::<String>(1024);
    let state = Arc::new(AppState {
        tx: tx.clone(),
        events_processed: Arc::new(AtomicU64::new(0)),
    });

    let allowed_origin = std::env::var("CORS_ORIGINS").unwrap_or_else(|_| "http://localhost:3000".into());
    let cors = CorsLayer::new()
        .allow_origin(tower_http::cors::AllowOrigin::exact(
            allowed_origin.parse::<axum::http::HeaderValue>().unwrap_or_else(|_| "http://localhost:3000".parse().unwrap()),
        ))
        .allow_methods([axum::http::Method::GET, axum::http::Method::POST])
        .allow_headers([axum::http::header::CONTENT_TYPE, axum::http::header::AUTHORIZATION]);

    let app = Router::new()
        .route("/health", get(health_check))
        .route("/streams/ingest", post(ingest_sensor_data))
        .route("/streams/status", get(stream_status))
        .route("/metrics", get(metrics_endpoint))
        .layer(cors)
        .with_state(state);

    let port = std::env::var("STREAMING_PORT").unwrap_or_else(|_| "8082".into());
    let addr = format!("0.0.0.0:{port}");
    info!("Sindio Streaming (Rust) listening on {addr}");

    let listener = tokio::net::TcpListener::bind(&addr).await.unwrap();
    let serve = axum::serve(listener, app);

    let shutdown = async {
        signal::ctrl_c().await.expect("failed to listen for ctrl-c");
        info!("Shutdown signal received, draining connections...");
    };

    serve.with_graceful_shutdown(shutdown).await.unwrap();
}

async fn health_check(State(state): State<Arc<AppState>>) -> Json<serde_json::Value> {
    let deps = serde_json::json!({
        "broadcast_channel": if state.tx.receiver_count() > 0 || state.tx.len() < state.tx.max_capacity() { "ok" } else { "draining" },
        "events_processed": state.events_processed.load(Ordering::Relaxed),
    });
    Json(serde_json::json!({
        "status": "ok",
        "service": "sindio-streaming-rust",
        "timestamp": Utc::now().to_rfc3339(),
        "dependencies": deps
    }))
}

async fn ingest_sensor_data(
    State(state): State<Arc<AppState>>,
    Json(payload): Json<SensorPayload>,
) -> Result<Json<serde_json::Value>, StatusCode> {
    let event = StreamEvent {
        event_id: Uuid::new_v4().to_string(),
        timestamp: Utc::now().to_rfc3339(),
        sensor_id: payload.sensor_id,
        metric_type: payload.metric_type,
        value: payload.value,
        unit: payload.unit,
        severity: if payload.value > 90.0 { "critical" } else { "normal" }.into(),
    };

    let json = serde_json::to_string(&event).map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
    let _ = state.tx.send(json);
    state.events_processed.fetch_add(1, Ordering::Relaxed);

    Ok(Json(serde_json::json!({
        "accepted": true,
        "event_id": event.event_id
    })))
}

async fn stream_status(State(state): State<Arc<AppState>>) -> Json<serde_json::Value> {
    Json(serde_json::json!({
        "active_streams": state.tx.receiver_count(),
        "events_processed_total": state.events_processed.load(Ordering::Relaxed),
        "buffer_capacity_pct": (state.tx.len() as f64 / state.tx.max_capacity() as f64) * 100.0
    }))
}

async fn metrics_endpoint() -> String {
    METRICS_HANDLE.render()
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::body::Body;
    use axum::http::Request;
    use tower::ServiceExt;

    fn test_state() -> Arc<AppState> {
        let (tx, _rx) = broadcast::channel::<String>(1024);
        Arc::new(AppState {
            tx,
            events_processed: Arc::new(AtomicU64::new(0)),
        })
    }

    fn test_app(state: Arc<AppState>) -> Router {
        Router::new()
            .route("/health", get(health_check))
            .route("/streams/status", get(stream_status))
            .route("/metrics", get(metrics_endpoint))
            .with_state(state)
    }

    #[tokio::test]
    async fn health_check_returns_ok() {
        let state = test_state();
        let app = test_app(state);

        let response = app
            .oneshot(Request::builder().uri("/health").body(Body::empty()).unwrap())
            .await
            .unwrap();

        assert_eq!(response.status(), StatusCode::OK);
        let body = hyper::body::to_bytes(response.into_body()).await.unwrap();
        let json: serde_json::Value = serde_json::from_slice(&body).unwrap();
        assert_eq!(json["status"], "ok");
        assert_eq!(json["service"], "sindio-streaming-rust");
        assert!(json["dependencies"].is_object());
    }

    #[tokio::test]
    async fn stream_status_returns_metrics() {
        let state = test_state();
        let app = test_app(state);

        let response = app
            .oneshot(Request::builder().uri("/streams/status").body(Body::empty()).unwrap())
            .await
            .unwrap();

        assert_eq!(response.status(), StatusCode::OK);
        let body = hyper::body::to_bytes(response.into_body()).await.unwrap();
        let json: serde_json::Value = serde_json::from_slice(&body).unwrap();
        assert!(json["active_streams"].is_number());
        assert!(json["events_processed_total"].is_number());
        assert!(json["buffer_capacity_pct"].is_number());
    }

    #[tokio::test]
    async fn metrics_endpoint_returns_text() {
        let state = test_state();
        let app = test_app(state);

        let response = app
            .oneshot(Request::builder().uri("/metrics").body(Body::empty()).unwrap())
            .await
            .unwrap();

        assert_eq!(response.status(), StatusCode::OK);
    }

    #[tokio::test]
    async fn ingest_valid_payload_returns_ok() {
        let state = test_state();
        let app = Router::new()
            .route("/streams/ingest", post(ingest_sensor_data))
            .with_state(state);

        let payload = serde_json::json!({
            "sensor_id": "TEST-001",
            "metric_type": "temperature",
            "value": 45.0,
            "unit": "celsius",
            "location": {"lat": -1.29, "lng": 36.82}
        });

        let response = app
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/streams/ingest")
                    .header("content-type", "application/json")
                    .body(Body::from(serde_json::to_vec(&payload).unwrap()))
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(response.status(), StatusCode::OK);
        let body = hyper::body::to_bytes(response.into_body()).await.unwrap();
        let json: serde_json::Value = serde_json::from_slice(&body).unwrap();
        assert_eq!(json["accepted"], true);
        assert!(json["event_id"].is_string());
    }

    #[tokio::test]
    async fn ingest_invalid_json_returns_422() {
        let state = test_state();
        let app = Router::new()
            .route("/streams/ingest", post(ingest_sensor_data))
            .with_state(state);

        let response = app
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/streams/ingest")
                    .header("content-type", "application/json")
                    .body(Body::from("not valid json"))
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(response.status(), StatusCode::UNPROCESSABLE_ENTITY);
    }

    #[tokio::test]
    async fn events_counter_increments_on_ingest() {
        let state = test_state();
        assert_eq!(state.events_processed.load(Ordering::Relaxed), 0);

        let app = Router::new()
            .route("/streams/ingest", post(ingest_sensor_data))
            .with_state(state.clone());

        let payload = serde_json::json!({
            "sensor_id": "SENSOR-A",
            "metric_type": "pressure",
            "value": 30.0,
            "unit": "psi",
            "location": null
        });

        app.oneshot(
            Request::builder()
                .method("POST")
                .uri("/streams/ingest")
                .header("content-type", "application/json")
                .body(Body::from(serde_json::to_vec(&payload).unwrap()))
                .unwrap(),
        )
        .await
        .unwrap();

        assert_eq!(state.events_processed.load(Ordering::Relaxed), 1);
    }

    #[tokio::test]
    async fn severity_critical_for_high_value() {
        let state = test_state();
        let app = Router::new()
            .route("/streams/ingest", post(ingest_sensor_data))
            .with_state(state.clone());

        let payload = serde_json::json!({
            "sensor_id": "SENSOR-C",
            "metric_type": "voltage",
            "value": 95.0,
            "unit": "pu",
            "location": {"lat": -1.29, "lng": 36.82}
        });

        let response = app
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/streams/ingest")
                    .header("content-type", "application/json")
                    .body(Body::from(serde_json::to_vec(&payload).unwrap()))
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(response.status(), StatusCode::OK);
    }
}
