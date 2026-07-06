import os
from celery import Celery

_redis_pw = os.getenv("REDIS_PASSWORD", "sindio_redis_local")
_redis_host = os.getenv("REDIS_HOST", "localhost")
_redis_port = os.getenv("REDIS_PORT", "6379")

CELERY_BROKER = os.getenv("CELERY_BROKER_URL", f"redis://:{_redis_pw}@{_redis_host}:{_redis_port}/0")
CELERY_BACKEND = os.getenv("CELERY_RESULT_BACKEND", f"redis://:{_redis_pw}@{_redis_host}:{_redis_port}/2")

celery_app = Celery(
    "sindio_worker",
    broker=CELERY_BROKER,
    backend=CELERY_BACKEND,
    include=[
        "app.services.search_service",
        "app.services.alert_generator",
        "app.services.alert_scheduler",
        "app.services.long_interval_scheduler",
    ]
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    result_expires=3600,  # Task results expire after 1 hour (Issue 25)
    task_reject_on_worker_lost=True,
    task_acks_late=True,
    task_default_queue="sindio_tasks",
    task_queues={
        "sindio_tasks": {
            "binding_key": "sindio_tasks",
            "dead_letter_exchange": "sindio_tasks_dlx",
            "dead_letter_routing_key": "sindio_tasks_dlq",
        },
        "sindio_tasks_dlq": {
            "binding_key": "sindio_tasks_dlq",
        },
    },
    task_routes={
        "sindio.*": {"queue": "sindio_tasks"},
    },
    beat_schedule={
        "poll-simulation-outputs": {
            "task": "sindio.generate_alerts",
            "schedule": 300.0, # 5 minutes
            "options": {"queue": "sindio_tasks"},
        },
        "scheduler-master": {
            "task": "sindio.scheduler_master",
            "schedule": 300.0, # 5 minutes
            "options": {"queue": "sindio_tasks"},
        },
        "long-dispatcher": {
            "task": "sindio.long_dispatcher",
            "schedule": 3600.0, # 60 minutes
            "options": {"queue": "sindio_tasks"},
        },
        "sync-simulations-to-timescale": {
            "task": "sindio.sync_simulations_to_timescale",
            "schedule": 86400.0, # Daily
            "options": {"queue": "sindio_tasks"},
        },
        "sync-simulations-to-qdrant": {
            "task": "sindio.sync_simulations_to_qdrant",
            "schedule": 86400.0, # Daily
            "options": {"queue": "sindio_tasks"},
        },
        "index-alert-daily-sync": {
            "task": "sindio.search.index_alert_sync",
            "schedule": 86400.0, # Daily
            "options": {"queue": "sindio_tasks"},
        },
        "index-sim-state-daily-sync": {
            "task": "sindio.search.index_sim_state_sync",
            "schedule": 86400.0, # Daily
            "options": {"queue": "sindio_tasks"},
        },
        "data-retention-cleanup": {
            "task": "sindio.data_retention.cleanup_old_data",
            "schedule": 86400.0, # Daily
            "options": {"queue": "sindio_tasks"},
        },
    }
)

if __name__ == "__main__":
    celery_app.start()
