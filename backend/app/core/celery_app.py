"""
Celery application — orchestrates async parallel migrations.

Workers consume from three queues:
- ``migrations``  : end-to-end orchestrator (one task per Migration row)
- ``conversions`` : per-disk converter jobs (qemu-img / virt-v2v wait loop)
- ``discovery``   : reserved for hypervisor sync tasks (future)

Configuration is centralised in :class:`app.core.config.Settings`. Tasks are
auto-discovered from the ``app.tasks`` package.

Durability posture:
- ``acks_late=True``               — message is only ack'd once the task returns.
- ``reject_on_worker_lost=True``   — if the worker dies mid-task, the broker
                                     re-queues the message.
- ``worker_prefetch_multiplier=1`` — never hoard messages a slow task can't
                                     process; lets healthy workers pick them up.
"""

from celery import Celery

from app.core.config import settings


celery_app = Celery(
    "shiftwise",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.conversion",
        "app.tasks.migration",
    ],
)

celery_app.conf.update(
    task_serializer=settings.CELERY_TASK_SERIALIZER,
    result_serializer=settings.CELERY_RESULT_SERIALIZER,
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,

    task_always_eager=settings.CELERY_TASK_ALWAYS_EAGER,
    task_eager_propagates=settings.CELERY_TASK_ALWAYS_EAGER,

    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_acks_on_failure_or_timeout=False,
    worker_prefetch_multiplier=1,

    task_soft_time_limit=settings.CELERY_TASK_SOFT_TIME_LIMIT,
    task_time_limit=settings.CELERY_TASK_TIME_LIMIT,

    task_default_queue="migrations",
    task_routes={
        "app.tasks.migration.*":  {"queue": "migrations"},
        "app.tasks.conversion.*": {"queue": "conversions"},
        "app.tasks.discovery.*":  {"queue": "discovery"},
    },

    result_expires=24 * 3600,
)
