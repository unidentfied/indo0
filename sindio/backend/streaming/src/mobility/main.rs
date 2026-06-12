use chrono::Utc;
use tokio::sync::mpsc;
use tracing::{error, info, warn};

use crate::aggregation::AggregationWindow;
use crate::db;
use crate::models::MobilityPing;
use crate::retry;
use crate::source::{spawn_source, MobilitySource};

mod aggregation;
mod db;
mod models;
mod source;
mod retry;

const CHANNEL_CAPACITY: usize = 100_000;
const FLUSH_INTERVAL_SECS: u64 = 60;

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(
            std::env::var("RUST_LOG")
                .unwrap_or_else(|_| "sindio_streaming=info,rdkafka=warn".into()),
        )
        .init();

    info!("🚦 Sindio Mobility Consumer starting…");

    let kafka_enabled = std::env::var("KAFKA_BROKERS").is_ok();

    let source = if kafka_enabled {
        let brokers = std::env::var("KAFKA_BROKERS").unwrap();
        let topic = std::env::var("KAFKA_TOPIC")
            .unwrap_or_else(|_| "nairobi.mobility.raw".into());
        let group_id = std::env::var("KAFKA_GROUP_ID")
            .unwrap_or_else(|_| "sindio-mobility-consumer".into());

        info!("Kafka mode: {} → {}", topic, brokers);
        MobilitySource::Kafka {
            topic,
            brokers,
            group_id,
        }
    } else {
        warn!("KAFKA_BROKERS not set — using mock GPS taxi data");
        MobilitySource::Mock {
            pings_per_second: 200,
        }
    };

    let pool = match db::connect_with_retry().await {
        Ok(p) => {
            info!("TimescaleDB connected");
            p
        }
        Err(e) => {
            error!("TimescaleDB unavailable after retries: {}. Starting without DB — aggregates will be logged only.", e);
            return;
        }
    };

    let (tx, mut rx) = mpsc::channel::<MobilityPing>(CHANNEL_CAPACITY);

    let agg_handle = {
        let pool = pool.clone();

        tokio::spawn(async move {
            let mut window = AggregationWindow::default();
            let mut last_flush = Utc::now();

            loop {
                tokio::select! {
                    maybe_ping = rx.recv() => {
                        match maybe_ping {
                            Some(ping) => {
                                window.add_ping(&ping);
                                if rx.len() > (CHANNEL_CAPACITY as f64 * 0.8) as usize {
                                    warn!(
                                        "Channel backpressure: {} / {} messages waiting",
                                        rx.len(),
                                        CHANNEL_CAPACITY
                                    );
                                }
                            }
                            None => {
                                warn!("Source channel closed, flushing and exiting.");
                                let remaining = window.drain_complete(Utc::now());
                                if !remaining.is_empty() {
                                    let _ = db::batch_insert(&pool, &remaining).await;
                                }
                                break;
                            }
                        }
                    }
                    _ = tokio::time::sleep(tokio::time::Duration::from_secs(FLUSH_INTERVAL_SECS)) => {
                        let now = Utc::now();
                        let since_last = (now - last_flush).num_seconds();
                        if since_last >= FLUSH_INTERVAL_SECS as i64 {
                            let aggregates = window.drain_complete(now);
                            if !aggregates.is_empty() {
                                match db::batch_insert(&pool, &aggregates).await {
                                    Ok(n) => {
                                        info!(
                                            "Flushed {} rows ({} active windows)",
                                            n,
                                            window.len()
                                        );
                                    }
                                    Err(e) => error!("Flush failed: {:?}", e),
                                }
                            }
                            last_flush = now;
                        }
                    }
                }
            }
        })
    };

    tokio::spawn(async move {
        spawn_source(source, tx).await;
        info!("Source task finished");
    });

    let _ = tokio::join!(agg_handle);

    info!("Sindio Mobility Consumer shut down");
}
