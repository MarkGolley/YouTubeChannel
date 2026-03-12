from __future__ import annotations

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from config import Settings


class PipelineScheduler:
    def __init__(self, settings: Settings, logger):
        self.settings = settings
        self.logger = logger
        self.scheduler = BlockingScheduler(timezone=settings.timezone)

    def start(self, job_callable) -> None:
        trigger = CronTrigger(
            hour=self.settings.schedule_hour,
            minute=self.settings.schedule_minute,
            timezone=self.settings.timezone,
        )
        self.scheduler.add_job(
            func=lambda: self._run_safe(job_callable),
            trigger=trigger,
            id="youtube_pipeline_daily",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
            replace_existing=True,
        )
        self.logger.info(
            "scheduler_started",
            extra={
                "timezone": self.settings.timezone,
                "hour": self.settings.schedule_hour,
                "minute": self.settings.schedule_minute,
            },
        )

        if self.settings.run_once_on_start:
            self._run_safe(job_callable)

        self.scheduler.start()

    def _run_safe(self, job_callable) -> None:
        try:
            job_callable()
        except Exception:
            self.logger.exception("scheduled_job_failed")
