use std::time::Duration;

use chrono::Utc;
use rand::Rng;
use tokio::sync::mpsc;
use tracing::{error, info, warn};

use super::models::MobilityPing;
use crate::retry;

const NAIROBI_CENTER_LAT: f64 = -1.2921;
const NAIROBI_CENTER_LON: f64 = 36.8219;
const GPS_JITTER: f64 = 0.05;

pub enum MobilitySource {
    Kafka {
        topic: String,
        brokers: String,
        group_id: String,
    },
    Mock {
        pings_per_second: u64,
    },
}

pub async fn spawn_source(
    source: MobilitySource,
    tx: mpsc::Sender<MobilityPing>,
) {
    match source {
        MobilitySource::Kafka {
            topic,
            brokers,
            group_id,
        } => {
            info!("Connecting to Kafka: brokers={}, topic={}", brokers, topic);

            match run_kafka_consumer(&topic, &brokers, &group_id, tx.clone()).await {
                Ok(()) => info!("Kafka consumer exited cleanly"),
                Err(e) => {
                    warn!("Kafka unavailable: {}. Falling back to mock GPS data.", e);
                    run_mock_fallback(tx).await;
                }
            }
        }
        MobilitySource::Mock { pings_per_second } => {
            info!(
                "Running in mock mode: {} pings/sec from historic taxi data",
                pings_per_second
            );
            run_mock_generator(tx, pings_per_second).await;
        }
    }
}

async fn run_kafka_consumer(
    topic: &str,
    brokers: &str,
    group_id: &str,
    tx: mpsc::Sender<MobilityPing>,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    use rdkafka::config::ClientConfig;
    use rdkafka::consumer::{Consumer, StreamConsumer};
    use rdkafka::message::Message;

    // Retry consumer creation with exponential back-off (1s, 2s, 4s)
    let consumer: StreamConsumer = retry::connect_kafka_with_fallback(
        "kafka_stream_consumer",
        || {
            let brokers = brokers.to_string();
            let group_id = group_id.to_string();
            async move {
                let c: StreamConsumer = ClientConfig::new()
                    .set("bootstrap.servers", &brokers)
                    .set("group.id", &group_id)
                    .set("auto.offset.reset", "latest")
                    .set("enable.auto.commit", "true")
                    .set("session.timeout.ms", "30000")
                    .set("max.poll.interval.ms", "60000")
                    .create()?;
                Ok(c)
            }
        },
    )
    .await
    .ok_or_else(|| "kafka: all retries exhausted — falling back to mock".to_string())?;

    consumer.subscribe(&[topic])?;

    let mut stream = consumer.stream();

    while let Some(result) = futures::StreamExt::next(&mut stream).await {
        match result {
            Ok(msg) => {
                if let Some(payload) = msg.payload() {
                    match serde_json::from_slice::<MobilityPing>(payload) {
                        Ok(ping) => {
                            if tx.send(ping).await.is_err() {
                                error!("Downstream channel closed, exiting Kafka consumer");
                                break;
                            }
                        }
                        Err(e) => {
                            warn!("Failed to parse Kafka message: {:?}", e);
                        }
                    }
                }
            }
            Err(e) => {
                error!("Kafka receive error: {:?}", e);
                return Err(Box::new(e));
            }
        }
    }

    Ok(())
}

async fn run_mock_generator(tx: mpsc::Sender<MobilityPing>, pps: u64) {
    let interval = Duration::from_secs_f64(1.0 / pps as f64);
    let mut rng = rand::thread_rng();

    let routes: Vec<(f64, f64)> = vec![
        (36.7000, -1.3800),
        (36.8090, -1.2670),
        (36.8580, -1.2700),
        (36.8122, -1.2975),
        (36.7850, -1.2900),
        (36.8219, -1.2833),
        (36.7700, -1.3700),
        (36.7900, -1.3000),
        (36.7200, -1.3800),
    ];

    let mut positions: Vec<(f64, f64, f64)> = routes
        .iter()
        .map(|(lon, lat)| (*lon, *lat, 0.0))
        .collect();

    loop {
        for (lon, lat, speed) in positions.iter_mut() {
            *lon += rng.gen_range(-0.003..0.003);
            *lat += rng.gen_range(-0.003..0.003);

            let max_speed = if *lat > -1.35 || *lon > 36.95 {
                22.2
            } else if *lat < -1.38 || *lon < 36.7 || *lon > 37.05 {
                10.0
            } else {
                13.9
            };

            let congestion_factor = rng.gen_range(0.2..1.5);
            *speed = (max_speed * congestion_factor).clamp(0.0, 30.0);

            let ping = MobilityPing {
                device_id_hash: format!("device_{:04}", rng.gen_range(0..5000)),
                lat: lat.clamp(
                    NAIROBI_CENTER_LAT - GPS_JITTER,
                    NAIROBI_CENTER_LAT + GPS_JITTER,
                ),
                lon: lon.clamp(
                    NAIROBI_CENTER_LON - GPS_JITTER,
                    NAIROBI_CENTER_LON + GPS_JITTER,
                ),
                timestamp: Utc::now().to_rfc3339(),
                speed_ms: *speed,
            };

            if tx.send(ping).await.is_err() {
                error!("Downstream channel closed, exiting mock generator");
                return;
            }

            tokio::time::sleep(interval).await;
        }
    }
}

async fn run_mock_fallback(tx: mpsc::Sender<MobilityPing>) {
    warn!("Entering Kafka mock fallback mode");
    run_mock_generator(tx, 50).await;
}
