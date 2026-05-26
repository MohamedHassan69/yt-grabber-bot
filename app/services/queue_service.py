"""
Queue-based download manager.
Prevents OOM on free hosts by serialising downloads per-user
and limiting total concurrent jobs across the bot.
"""
import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from pathlib import Path

from app.utils.logger import setup_logger

logger = setup_logger(__name__)


class JobStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class DownloadJob:
    job_id: str
    user_id: int
    url: str
    format_spec: str
    ext: str
    status: JobStatus = JobStatus.PENDING
    result_path: Optional[Path] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.monotonic)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    on_progress: Optional[Callable] = None
    on_done: Optional[Callable] = None
    on_error: Optional[Callable] = None


class DownloadQueue:
    """
    Global download queue.
    - MAX_CONCURRENT_DOWNLOADS jobs run simultaneously.
    - Each user queues jobs in order.
    - Completed jobs are auto-cleaned after TTL.
    """

    MAX_CONCURRENT = 3
    JOB_TTL = 300   # 5 minutes

    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._jobs: Dict[str, DownloadJob] = {}
        self._user_active: Dict[int, int] = defaultdict(int)
        self._semaphore = asyncio.Semaphore(self.MAX_CONCURRENT)
        self._running = False
        self._worker_task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the background worker."""
        if not self._running:
            self._running = True
            self._worker_task = asyncio.create_task(self._worker())
            logger.info("Download queue worker started.")

    async def stop(self):
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()

    async def enqueue(self, job: DownloadJob) -> str:
        """Add job to queue. Returns job_id."""
        self._jobs[job.job_id] = job
        await self._queue.put(job.job_id)
        logger.info(
            f"Job {job.job_id} queued for user {job.user_id} "
            f"(queue size: {self._queue.qsize()})"
        )
        return job.job_id

    def get_job(self, job_id: str) -> Optional[DownloadJob]:
        return self._jobs.get(job_id)

    def cancel_user_jobs(self, user_id: int):
        """Cancel all pending jobs for a user."""
        for job in self._jobs.values():
            if job.user_id == user_id and job.status == JobStatus.PENDING:
                job.status = JobStatus.CANCELLED

    async def _worker(self):
        """Background worker that pulls jobs from queue and runs them."""
        from app.services.youtube_service import youtube_service

        while self._running:
            try:
                job_id = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                await self._cleanup_old_jobs()
                continue

            job = self._jobs.get(job_id)
            if not job or job.status in (JobStatus.CANCELLED, JobStatus.ERROR):
                self._queue.task_done()
                continue

            async with self._semaphore:
                job.status = JobStatus.RUNNING
                job.started_at = time.monotonic()
                self._user_active[job.user_id] += 1

                try:
                    path = await youtube_service.download(
                        url=job.url,
                        format_spec=job.format_spec,
                        ext=job.ext,
                        on_progress=job.on_progress,
                    )
                    job.result_path = path
                    job.status = JobStatus.DONE
                    job.finished_at = time.monotonic()
                    if job.on_done:
                        asyncio.create_task(job.on_done(job))
                except Exception as e:
                    job.error = str(e)
                    job.status = JobStatus.ERROR
                    job.finished_at = time.monotonic()
                    logger.error(f"Job {job_id} failed: {e}")
                    if job.on_error:
                        asyncio.create_task(job.on_error(job))
                finally:
                    self._user_active[job.user_id] = max(
                        0, self._user_active[job.user_id] - 1
                    )
                    self._queue.task_done()

    async def _cleanup_old_jobs(self):
        """Remove jobs older than JOB_TTL from memory."""
        now = time.monotonic()
        stale = [
            jid for jid, job in self._jobs.items()
            if job.finished_at and (now - job.finished_at) > self.JOB_TTL
        ]
        for jid in stale:
            del self._jobs[jid]

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    def user_active_count(self, user_id: int) -> int:
        return self._user_active.get(user_id, 0)


# Global singleton — started in main.py post_init
download_queue = DownloadQueue()
