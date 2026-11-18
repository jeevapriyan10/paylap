import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, text

from app.config import settings
from app.db import SessionLocal
from app.models import Organization
from app.services.expiry import expire_due_contracts
from app.services.reconciliation import run_reconciliation
from app.services.webhooks import process_pending_webhooks

logger = logging.getLogger("paylap.scheduler")

LOCK_NAME = "paylap:job_leader"


class JobScheduler:
    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_reconcile_date: Optional[str] = None

    def start(self):
        if not settings.PAYLAP_JOBS_ENABLED:
            logger.info("Background jobs scheduler is disabled via PAYLAP_JOBS_ENABLED=false")
            return
        if self._task and not self._task.done():
            try:
                if self._task.get_loop() != asyncio.get_running_loop():
                    self._task.cancel()
                    self._task = None
            except Exception:
                self._task = None
        if self._running and self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop())
        logger.info("Background jobs scheduler task created")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                if self._task.get_loop() == asyncio.get_running_loop():
                    await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        logger.info("Background jobs scheduler stopped")

    async def _scheduler_loop(self):
        logger.info("Background scheduler loop starting...")
        while self._running:
            try:
                # Run iteration in threadpool to not block asyncio event loop
                await asyncio.to_thread(self._run_scheduled_tasks)
            except Exception as exc:
                logger.error(f"Error in scheduler loop: {exc}", exc_info=True)

            # Sleep 15 seconds before next polling iteration
            await asyncio.sleep(15.0)

    def _run_scheduled_tasks(self):
        with SessionLocal() as db:
            # 1. Attempt non-blocking session-level advisory lock
            has_lock = db.scalar(
                text("SELECT pg_try_advisory_lock(hashtext(:lock_name))"),
                {"lock_name": LOCK_NAME},
            )
            if not has_lock:
                logger.debug("Another instance holds the job leader advisory lock; skipping run.")
                return

            try:
                now = datetime.now(timezone.utc)

                # Job 1: Contract Expiry
                expired_ids = expire_due_contracts(db)
                if expired_ids:
                    logger.info(f"Expired {len(expired_ids)} contracts: {expired_ids}")

                # Job 2: Webhook Retries
                delivered = process_pending_webhooks(db)
                if delivered:
                    logger.info(f"Delivered {delivered} retried webhooks")

                # Job 3: Daily Reconciliation
                today_str = now.strftime("%Y-%m-%d")
                if now.hour == settings.PAYLAP_RECONCILE_HOUR_UTC and self._last_reconcile_date != today_str:
                    logger.info("Running daily scheduled reconciliation for all active organizations...")
                    orgs = db.scalars(select(Organization)).all()
                    for org in orgs:
                        try:
                            # Reconcile simulated environment
                            run_reconciliation(db, org.id, environment="simulated")
                            # If org has live/sandbox credentials, reconcile sandbox as well
                            if org.live_enabled and settings.PAYLAP_ALLOW_LIVE:
                                run_reconciliation(db, org.id, environment="live")
                            else:
                                run_reconciliation(db, org.id, environment="sandbox")
                        except Exception as e:
                            logger.error(f"Reconciliation error for org {org.id}: {e}")
                    self._last_reconcile_date = today_str

            finally:
                # Release advisory lock
                db.execute(
                    text("SELECT pg_advisory_unlock(hashtext(:lock_name))"),
                    {"lock_name": LOCK_NAME},
                )
                db.commit()


scheduler = JobScheduler()
