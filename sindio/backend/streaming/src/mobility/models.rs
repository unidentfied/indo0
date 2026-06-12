use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MobilityPing {
    pub device_id_hash: String,
    pub lat: f64,
    pub lon: f64,
    pub timestamp: String,
    pub speed_ms: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct H3BinAggregate {
    pub h3_index: String,
    pub h3_resolution: u8,
    pub window_start: DateTime<Utc>,
    pub vehicle_count: u32,
    pub avg_speed_ms: f64,
    pub p50_speed_ms: f64,
    pub p95_speed_ms: f64,
    pub congestion_index: f64,
    pub freeflow_speed_ms: f64,
    pub total_pings: u64,
}

impl H3BinAggregate {
    pub fn new(
        h3_index: String,
        resolution: u8,
        window_start: DateTime<Utc>,
        speeds: &[f64],
        freeflow_speed_ms: f64,
        total_pings: u64,
    ) -> Self {
        let vehicle_count = speeds.len() as u32;
        let avg_speed = if vehicle_count > 0 {
            speeds.iter().sum::<f64>() / vehicle_count as f64
        } else {
            0.0
        };

        let mut sorted = speeds.to_vec();
        sorted.sort_unstable_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
        let p50 = percentile(&sorted, 0.50);
        let p95 = percentile(&sorted, 0.95);
        let congestion = if freeflow_speed_ms > 0.0 && avg_speed > 0.0 {
            avg_speed / freeflow_speed_ms
        } else {
            1.0
        };

        Self {
            h3_index,
            h3_resolution: resolution,
            window_start,
            vehicle_count,
            avg_speed_ms: (avg_speed * 1000.0).round() / 1000.0,
            p50_speed_ms: (p50 * 1000.0).round() / 1000.0,
            p95_speed_ms: (p95 * 1000.0).round() / 1000.0,
            congestion_index: (congestion * 10000.0).round() / 10000.0,
            freeflow_speed_ms,
            total_pings,
        }
    }
}

fn percentile(sorted: &[f64], p: f64) -> f64 {
    if sorted.is_empty() {
        return 0.0;
    }
    let idx = ((sorted.len() as f64 - 1.0) * p).round() as usize;
    sorted[idx.min(sorted.len() - 1)]
}
