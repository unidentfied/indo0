/// Retry helpers for Kafka consumer connection.
///
/// Retries 3x with exponential back-off (1 s, 2 s, 4 s) before falling
/// back to the mock mobility generator.  Logs every attempt and never
/// panics.

use std::time::Duration;

use tracing::{info, warn};

const RETRIES: u32 = 3;
const BACKOFF_BASE: Duration = Duration::from_secs(1);

/// Calls `f` up to 3 times with exponential back-off.  Returns the
/// result on success or `None` when all retries are exhausted.
pub async fn with_retry<T, E: std::fmt::Debug, F, Fut>(
    label: &str,
    mut f: F,
) -> Option<T>
where
    F: FnMut() -> Fut,
    Fut: std::future::Future<Output = Result<T, E>>,
{
    for attempt in 1..=RETRIES {
        match f().await {
            Ok(val) => return Some(val),
            Err(e) => {
                let delay = BACKOFF_BASE * 2u32.pow(attempt - 1);
                warn!(
                    "{label} — attempt {attempt}/{RETRIES} failed ({e:?}). \
                     Retrying in {delay:?}…"
                );
                tokio::time::sleep(delay).await;
            }
        }
    }
    warn!("{label} — all {RETRIES} retries exhausted — falling back to mock.");
    None
}

/// Wraps a Kafka consumer-creation closure with retry + mock fallback.
pub async fn connect_kafka_with_fallback<C, F, Fut>(
    label: &str,
    f: F,
) -> Option<C>
where
    F: FnMut() -> Fut,
    Fut: std::future::Future<Output = Result<C, Box<dyn std::error::Error + Send + Sync>>>,
{
    for attempt in 1..=RETRIES {
        match f().await {
            Ok(client) => return Some(client),
            Err(e) => {
                let delay = BACKOFF_BASE * 2u32.pow(attempt - 1);
                warn!(
                    "{label} — attempt {attempt}/{RETRIES} failed ({e}). \
                     Retrying in {delay:?}…"
                );
                tokio::time::sleep(delay).await;
            }
        }
    }
    warn!("{label} — all {RETRIES} retries exhausted.");
    info!("{label} — will use mock/synthetic mobility data.");
    None
}
