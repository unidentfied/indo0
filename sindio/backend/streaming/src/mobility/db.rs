use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use tracing::{error, info, warn};

use super::models::H3BinAggregate;

const BATCH_SIZE: usize = 512;
const DB_URL_ENV: &str = "DATABASE_URL";

pub async fn connect() -> Result<PgPool, sqlx::Error> {
    let url =
        std::env::var(DB_URL_ENV).unwrap_or_else(|_| {
            "postgresql://sindio_user:sindio_pass@localhost:5432/sindio".into()
        });

    info!("Connecting to TimescaleDB at {}", mask_password(&url));

    PgPoolOptions::new()
        .max_connections(8)
        .min_connections(2)
        .acquire_timeout(std::time::Duration::from_secs(30))
        .connect(&url)
        .await
}

pub async fn connect_with_retry() -> Result<PgPool, sqlx::Error> {
    let mut last_err: Option<sqlx::Error> = None;
    for attempt in 1..=3 {
        match connect().await {
            Ok(pool) => return Ok(pool),
            Err(e) => {
                last_err = Some(e);
                let delay = std::time::Duration::from_secs(2u64.pow(attempt - 1));
                warn!(
                    "DB connection attempt {}/3 failed. Retrying in {:.0}s…",
                    attempt,
                    delay.as_secs()
                );
                tokio::time::sleep(delay).await;
            }
        }
    }
    Err(last_err.unwrap())
}

pub async fn batch_insert(
    pool: &PgPool,
    aggregates: &[H3BinAggregate],
) -> Result<u64, sqlx::Error> {
    if aggregates.is_empty() {
        return Ok(0);
    }

    let mut inserted = 0u64;

    for chunk in aggregates.chunks(BATCH_SIZE) {
        let mut tx = pool.begin().await?;

        for agg in chunk {
            let result = sqlx::query(
                r#"
                INSERT INTO mobility_aggregates
                    (time, h3_index, h3_resolution, vehicle_count,
                     avg_speed_ms, p50_speed_ms, p95_speed_ms,
                     congestion_index, freeflow_speed_ms, bounding_pings)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                ON CONFLICT (h3_index, time) DO UPDATE SET
                    vehicle_count    = EXCLUDED.vehicle_count,
                    avg_speed_ms     = EXCLUDED.avg_speed_ms,
                    p50_speed_ms     = EXCLUDED.p50_speed_ms,
                    p95_speed_ms     = EXCLUDED.p95_speed_ms,
                    congestion_index = EXCLUDED.congestion_index,
                    bounding_pings   = EXCLUDED.bounding_pings
                "#,
            )
            .bind(&agg.window_start)
            .bind(&agg.h3_index)
            .bind(agg.h3_resolution as i16)
            .bind(agg.vehicle_count as i32)
            .bind(agg.avg_speed_ms)
            .bind(agg.p50_speed_ms)
            .bind(agg.p95_speed_ms)
            .bind(agg.congestion_index)
            .bind(agg.freeflow_speed_ms)
            .bind(serde_json::json!({
                "total_pings": agg.total_pings,
                "window_seconds": 300
            }))
            .execute(&mut *tx)
            .await;

            match result {
                Ok(_) => inserted += 1,
                Err(e) => {
                    error!(
                        "Insert failed for h3={} time={}: {:?}",
                        agg.h3_index, agg.window_start, e
                    );
                }
            }
        }

        tx.commit().await?;
    }

    if inserted > 0 {
        info!(
            "Batch-inserted {} aggregate rows ({} chunks)",
            inserted,
            aggregates.len().div_ceil(BATCH_SIZE)
        );
    }

    Ok(inserted)
}

fn mask_password(url: &str) -> String {
    if let Some(at) = url.find('@') {
        let prefix = &url[..at];
        if let Some(colon) = prefix.rfind(':') {
            format!("{}:****@{}", &prefix[..colon], &url[at + 1..])
        } else {
            url.to_string()
        }
    } else {
        url.replace(
            &std::env::var("DB_PASSWORD").unwrap_or_default(),
            "****",
        )
    }
}
