"""
Celery task — drives a single ConversionJob to a terminal state.

The heavy lifting (pull + qemu-img/virt-v2v in-cluster) lives in
:class:`app.services.converter.service.ConverterService`. This task is a thin
wrapper that:

1. Opens its own DB session (Celery worker is not in a request context).
2. Records the celery task id on the job row for traceability.
3. Calls ``service.run_job`` synchronously.
4. Lets Celery handle retry on transient errors via ``autoretry_for``.

Idempotency: ``run_job`` checks ``status in {READY, CANCELLED, EXPIRED}`` and
returns early — re-enqueueing a finished job is a no-op.
"""

from __future__ import annotations

import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

from app.core.celery_app import celery_app  # noqa: F401  # NOSONAR (registers app)
from app.core.database import SessionLocal
from app.crud import conversion as crud_conversion
from app.models.conversion import ConversionStatus
from app.services.converter.errors import ConversionError, is_transient
from app.services.converter.service import ConverterService

logger = logging.getLogger(__name__)


@shared_task(
    name="app.tasks.conversion.run_conversion_job",
    bind=True,
    autoretry_for=(),  # we retry manually based on error bucket
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
)
def run_conversion_job(self, job_id: int) -> str:
    """Drive ConversionJob ``job_id`` to a terminal state. Returns the status."""
    db = SessionLocal()
    try:
        # Stamp the celery task id for ops traceability.
        crud_conversion.update_job(
            db, job_id, {"celery_task_id": self.request.id},
        )

        service = ConverterService()
        try:
            terminal = service.run_job(db, job_id)
        except SoftTimeLimitExceeded:
            crud_conversion.set_job_status(
                db, job_id, ConversionStatus.FAILED,
                error_code="ERR_TIMEOUT",
                error_message="Soft time limit exceeded",
            )
            raise

        if terminal == ConversionStatus.FAILED:
            job = crud_conversion.get_job(db, job_id)
            if job is not None and job.error_code and is_transient(job.error_code):
                if self.request.retries < self.max_retries:
                    logger.warning(
                        "Retrying conversion job %s (transient %s, attempt %s)",
                        job_id, job.error_code, self.request.retries + 1,
                    )
                    crud_conversion.set_job_status(
                        db, job_id, ConversionStatus.RETRYING,
                    )
                    raise self.retry(
                        exc=ConversionError(job.error_code, job.error_message or ""),
                    )

        return terminal.value
    finally:
        db.close()
