"""APScheduler cron jobs for triggering autonomous trading loops."""

import asyncio
import logging
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from stock_agent.autonomy import run_autonomous_loop

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def _parse_cron(cron_str: str) -> dict:
    """Parse a cron string into APScheduler kwargs."""
    parts = cron_str.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron string (expected 5 parts): {cron_str}")
    return {
        "minute": parts[0],
        "hour": parts[1],
        "day": parts[2],
        "month": parts[3],
        "day_of_week": parts[4],
    }


async def _run_loop_job():
    """Wrapper that catches errors so the scheduler keeps running."""
    try:
        await run_autonomous_loop()
    except Exception as e:
        logger.error("Autonomous loop failed: %s", e, exc_info=True)


def start_scheduler():
    """Start the APScheduler with the autonomous loop cron job."""
    global _scheduler
    if _scheduler is not None:
        logger.warning("Scheduler already running")
        return

    cron_str = os.environ.get("AUTONOMOUS_LOOP_CRON", "0 9,13,16 * * 1-5")
    logger.info("Starting scheduler with cron: %s", cron_str)

    _scheduler = AsyncIOScheduler()
    cron_kwargs = _parse_cron(cron_str)
    _scheduler.add_job(
        _run_loop_job,
        trigger=CronTrigger(**cron_kwargs),
        id="autonomous_loop",
        name="Autonomous Trading Loop",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("Scheduler started. Next run: %s", _scheduler.get_job("autonomous_loop").next_run_time)


def stop_scheduler():
    """Stop the scheduler."""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown()
        _scheduler = None
        logger.info("Scheduler stopped")


async def trigger_manual_loop():
    """Manually trigger an autonomous loop (for testing)."""
    logger.info("Manual autonomous loop triggered")
    await run_autonomous_loop()
