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
use tower_http::cors::CorsLayer;
use tracing::info;
use uuid::Uuid;

lazy_static::lazy_static! {
    static ref METRICS_HANDLE: metrics_exporter_prometheus::PrometheusHandle =
        PrometheusBuilder::new().install_recorder().expect("failed to install recorder");
}

// Data quality metrics helpers
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
    axum::serve(listener, app).await.unwrap();
}

async fn health_check() -> Json<serde_json::Value> {
    Json(serde_json::json!({
        "status": "ok",
        "service": "sindio-streaming-rust",
        "timestamp": Utc::now().to_rfc3339()
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
