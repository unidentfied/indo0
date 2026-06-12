use std::collections::HashMap;

use chrono::{DateTime, Duration, Utc};
use h3o::CellIndex;
use tracing::{debug, info, warn};

use super::models::{H3BinAggregate, MobilityPing};

const H3_RESOLUTION: u8 = 9;
const WINDOW_SECONDS: i64 = 300;

pub struct AggregationWindow {
    resolution: u8,
    duration: Duration,
    windows: HashMap<(String, DateTime<Utc>), Vec<f64>>,
    freeflow_speeds: HashMap<String, f64>,
}

impl Default for AggregationWindow {
    fn default() -> Self {
        Self {
            resolution: H3_RESOLUTION,
            duration: Duration::seconds(WINDOW_SECONDS),
            windows: HashMap::with_capacity(10_000),
            freeflow_speeds: HashMap::with_capacity(10_000),
        }
    }
}

impl AggregationWindow {
    pub fn add_ping(&mut self, ping: &MobilityPing) {
        let h3 = match h3o::LatLng::new(ping.lat, ping.lon) {
            Ok(pos) => match pos.to_cell(self.resolution) {
                Some(cell) => cell,
                None => {
                    warn!("H3 conversion failed for ({}, {})", ping.lat, ping.lon);
                    return;
                }
            },
            Err(e) => {
                warn!("Invalid lat/lon ({}, {}): {:?}", ping.lat, ping.lon, e);
                return;
            }
        };

        let h3_str = h3.to_string();

        let ts = match DateTime::parse_from_rfc3339(&ping.timestamp) {
            Ok(t) => t.with_timezone(&Utc),
            Err(_) => {
                debug!("Invalid timestamp format: {}", ping.timestamp);
                return;
            }
        };

        let window_start = truncate_to_window(ts, self.duration);

        let key = (h3_str.clone(), window_start);
        self.windows.entry(key).or_default().push(ping.speed_ms);

        let freeflow = self.freeflow_speeds.entry(h3_str).or_insert_with(|| {
            estimate_freeflow(ping.lon, ping.lat)
        });
        *freeflow = freeflow.max(ping.speed_ms);
    }

    pub fn drain_complete(
        &mut self,
        now: DateTime<Utc>,
    ) -> Vec<H3BinAggregate> {
        let cutoff = truncate_to_window(now, self.duration);

        let complete: Vec<_> = self
            .windows
            .iter()
            .filter(|((_, ws), _)| *ws < cutoff)
            .map(|((h3, ws), _)| (h3.clone(), *ws))
            .collect();

        let mut results = Vec::with_capacity(complete.len());

        for (h3, ws) in complete {
            if let Some(speeds) = self.windows.remove(&(h3.clone(), ws)) {
                let freeflow = self.freeflow_speeds.get(&h3).copied().unwrap_or(13.9);
                let total_pings = speeds.len() as u64;

                if speeds.is_empty() {
                    continue;
                }

                let agg = H3BinAggregate::new(
                    h3,
                    self.resolution,
                    ws,
                    &speeds,
                    freeflow,
                    total_pings,
                );

                results.push(agg);
            }
        }

        if !results.is_empty() {
            info!("Drained {} complete windows", results.len());
        }

        results
    }

    pub fn len(&self) -> usize {
        self.windows.len()
    }
}

fn truncate_to_window(ts: DateTime<Utc>, duration: Duration) -> DateTime<Utc> {
    let secs = ts.timestamp();
    let dur_secs = duration.num_seconds();
    let remainder = secs % dur_secs;
    if remainder < 0 {
        DateTime::from_timestamp(secs - remainder - dur_secs, 0).unwrap_or(ts)
    } else {
        DateTime::from_timestamp(secs - remainder, 0).unwrap_or(ts)
    }
}

fn estimate_freeflow(lon: f64, lat: f64) -> f64 {
    let is_highway = lat > -1.35 || lon > 36.95;
    if is_highway {
        22.2
    } else if lat < -1.38 || lon < 36.7 || lon > 37.05 {
        10.0
    } else {
        13.9
    }
}
