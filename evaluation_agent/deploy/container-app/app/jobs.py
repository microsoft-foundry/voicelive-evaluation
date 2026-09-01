"""
VoiceLive Audio Processor - Job Manager

Manages async processing jobs with status tracking.
Uses Azure Table Storage for persistence across Container App restarts.
"""

import asyncio
import os
import uuid
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from collections import OrderedDict

logger = logging.getLogger(__name__)

# Table Storage persistence (best-effort — falls back to in-memory only)
_table_client = None


def _get_table_client():
    """Get or create the Table Storage client for job persistence."""
    global _table_client
    if _table_client is not None:
        return _table_client
    try:
        from azure.data.tables import TableClient
        from azure.identity import DefaultAzureCredential
        account = os.environ.get("AZURE_STORAGE_ACCOUNT")
        if not account:
            return None
        _table_client = TableClient(
            endpoint=f"https://{account}.table.core.windows.net",
            table_name="voicelivejobs",
            credential=DefaultAzureCredential(),
        )
        _table_client.create_table()
    except Exception as e:
        if "TableAlreadyExists" not in str(e):
            logger.warning(f"Table Storage init failed (jobs will be in-memory only): {e}")
            _table_client = None
        # TableAlreadyExists is fine
    return _table_client


def _persist_job(job: "Job"):
    """Write job state to Table Storage (best-effort)."""
    tc = _get_table_client()
    if not tc:
        return
    try:
        entity = {
            "PartitionKey": "jobs",
            "RowKey": job.job_id,
            "dataset_path": job.dataset_path,
            "status": job.status.value,
            "created_at": job.created_at.isoformat() if job.created_at else "",
            "started_at": job.started_at.isoformat() if job.started_at else "",
            "completed_at": job.completed_at.isoformat() if job.completed_at else "",
            "session_mode": job.session_mode,
            "output_path": job.output_path or "",
            "results_count": job.results_count,
            "error": job.error or "",
            "files_processed": job.progress.files_processed,
            "files_failed": job.progress.files_failed,
            "total_files": job.progress.total_files,
        }
        tc.upsert_entity(entity)
    except Exception as e:
        logger.debug(f"Failed to persist job {job.job_id}: {e}")


def load_job_from_table(job_id: str) -> Optional[Dict[str, Any]]:
    """Load a job from Table Storage (used by Function App fallback)."""
    tc = _get_table_client()
    if not tc:
        return None
    try:
        entity = tc.get_entity("jobs", job_id)
        return {
            "job_id": entity["RowKey"],
            "dataset_path": entity.get("dataset_path", ""),
            "status": entity.get("status", "unknown"),
            "created_at": entity.get("created_at", ""),
            "started_at": entity.get("started_at", ""),
            "completed_at": entity.get("completed_at", ""),
            "session_mode": entity.get("session_mode", ""),
            "output_path": entity.get("output_path", ""),
            "results_count": int(entity.get("results_count", 0)),
            "error": entity.get("error", "") or None,
            "progress": {
                "files_processed": int(entity.get("files_processed", 0)),
                "files_failed": int(entity.get("files_failed", 0)),
                "total_files": int(entity.get("total_files", 0)),
                "percent_complete": round(
                    (
                        int(entity.get("files_processed", 0))
                        + int(entity.get("files_failed", 0))
                    )
                    / max(int(entity.get("total_files", 1)), 1)
                    * 100,
                    1,
                ),
            },
        }
    except Exception:
        return None


class JobStatus(str, Enum):
    """Job processing status."""
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class JobProgress:
    """Progress tracking for a job."""
    total_files: int = 0
    files_processed: int = 0
    files_failed: int = 0
    current_file: Optional[str] = None
    current_conversation: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        accounted_files = self.files_processed + self.files_failed
        return {
            "total_files": self.total_files,
            "files_processed": self.files_processed,
            "files_failed": self.files_failed,
            "percent_complete": round(accounted_files / self.total_files * 100, 1) if self.total_files > 0 else 0,
            "current_file": self.current_file,
            "current_conversation": self.current_conversation
        }


@dataclass
class Job:
    """A VoiceLive processing job."""
    job_id: str
    dataset_path: str
    status: JobStatus = JobStatus.QUEUED
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Configuration
    session_mode: str = "per-conversation"
    max_workers: int = 4
    session_config: Optional[Dict[str, Any]] = None
    
    # Progress
    progress: JobProgress = field(default_factory=JobProgress)
    
    # Results
    output_path: Optional[str] = None
    results_count: int = 0
    error: Optional[str] = None
    
    # Processing task
    _task: Optional[asyncio.Task] = field(default=None, repr=False)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "job_id": self.job_id,
            "dataset_path": self.dataset_path,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self._calculate_duration(),
            "session_mode": self.session_mode,
            "max_workers": self.max_workers,
            "progress": self.progress.to_dict(),
            "output_path": self.output_path,
            "results_count": self.results_count,
            "error": self.error
        }
    
    def _calculate_duration(self) -> Optional[float]:
        if not self.started_at:
            return None
        end = self.completed_at or datetime.now(timezone.utc)
        return round((end - self.started_at).total_seconds(), 2)


class JobManager:
    """
    Manages async processing jobs.
    
    Maintains job state, handles concurrent execution, and provides status queries.
    """
    
    def __init__(self, max_concurrent_jobs: int = 5, max_job_history: int = 100):
        self.max_concurrent_jobs = max_concurrent_jobs
        self.max_job_history = max_job_history
        self._jobs: OrderedDict[str, Job] = OrderedDict()
        self._lock = asyncio.Lock()
    
    async def create_job(
        self,
        dataset_path: str,
        session_mode: str = "per-conversation",
        max_workers: int = 4,
        session_config: Optional[Dict[str, Any]] = None
    ) -> Job:
        """Create a new processing job."""
        job_id = str(uuid.uuid4())
        
        job = Job(
            job_id=job_id,
            dataset_path=dataset_path,
            session_mode=session_mode,
            max_workers=max_workers,
            session_config=session_config
        )
        
        async with self._lock:
            # Clean up old jobs if needed
            while len(self._jobs) >= self.max_job_history:
                oldest_id = next(iter(self._jobs))
                old_job = self._jobs.pop(oldest_id)
                if old_job._task and not old_job._task.done():
                    old_job._task.cancel()
            
            self._jobs[job_id] = job
        
        logger.info(f"Created job {job_id} for dataset: {dataset_path}")
        if session_config and "agent" in session_config:
            logger.info(f"Job created with agent mode: {session_config['agent'].get('agent_name')}")
        _persist_job(job)
        return job
    
    async def get_job(self, job_id: str) -> Optional[Job]:
        """Get a job by ID."""
        async with self._lock:
            return self._jobs.get(job_id)
    
    async def update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        error: Optional[str] = None,
        output_path: Optional[str] = None,
        results_count: Optional[int] = None
    ) -> None:
        """Update job status."""
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            
            job.status = status
            
            if status == JobStatus.RUNNING and job.started_at is None:
                job.started_at = datetime.now(timezone.utc)
            elif status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
                job.completed_at = datetime.now(timezone.utc)
            
            if error:
                job.error = error
            if output_path:
                job.output_path = output_path
            if results_count is not None:
                job.results_count = results_count
        
        logger.info(f"Job {job_id} status: {status.value}")
        _persist_job(job)
    
    async def update_job_progress(
        self,
        job_id: str,
        files_processed: Optional[int] = None,
        files_failed: Optional[int] = None,
        current_file: Optional[str] = None,
        current_conversation: Optional[str] = None,
        total_files: Optional[int] = None
    ) -> None:
        """Update job progress."""
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            
            if total_files is not None:
                job.progress.total_files = total_files
            if files_processed is not None:
                job.progress.files_processed = files_processed
            if files_failed is not None:
                job.progress.files_failed = files_failed
            if current_file is not None:
                job.progress.current_file = current_file
            if current_conversation is not None:
                job.progress.current_conversation = current_conversation
    
    async def set_job_task(self, job_id: str, task: asyncio.Task) -> None:
        """Set the processing task for a job."""
        async with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job._task = task
    
    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a running job."""
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            
            if job._task and not job._task.done():
                job._task.cancel()
                job.status = JobStatus.CANCELLED
                job.completed_at = datetime.now(timezone.utc)
                logger.info(f"Cancelled job {job_id}")
                return True
            
            return False
    
    async def list_jobs(
        self,
        status: Optional[JobStatus] = None,
        limit: int = 20
    ) -> List[Job]:
        """List jobs, optionally filtered by status."""
        jobs = list(self._jobs.values())
        
        if status:
            jobs = [j for j in jobs if j.status == status]
        
        # Return most recent first
        jobs.reverse()
        return jobs[:limit]
    
    def get_running_count(self) -> int:
        """Get count of currently running jobs."""
        return sum(1 for j in self._jobs.values() if j.status == JobStatus.RUNNING)
    
    def can_start_job(self) -> bool:
        """Check if a new job can be started."""
        return self.get_running_count() < self.max_concurrent_jobs


# Global job manager instance
job_manager = JobManager()
