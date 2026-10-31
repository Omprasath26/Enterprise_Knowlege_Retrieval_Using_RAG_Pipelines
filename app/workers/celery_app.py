
from celery import Celery

from app.core.config import get_settings


settings = get_settings()

celery_app = Celery(
    "enterprise_knowledge_retrieval",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.ingestion_tasks"],
)

celery_app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    # Time configuration
    timezone="UTC",
    enable_utc=True,

    # Task tracking
    task_track_started=True,
    task_ignore_result=False,
    result_expires=3600,

    # Worker reliability
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,

    # Task execution
    task_default_queue="document_ingestion",
)
