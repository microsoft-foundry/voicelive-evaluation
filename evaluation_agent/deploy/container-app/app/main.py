"""
VoiceLive Audio Processor - FastAPI Application

Main API endpoints for the Container App.
Authentication is handled by Entra ID Easy Auth (platform-level) — no app-level auth needed.
"""

import os
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .jobs import job_manager, JobStatus
from .processor import start_processing_job
from .config import SessionConfig


# Configure Azure Monitor OpenTelemetry (before logging setup)
if os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        configure_azure_monitor()
        print("Azure Monitor OpenTelemetry configured")
    except ImportError:
        print("azure-monitor-opentelemetry not installed, skipping telemetry")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="VoiceLive Audio Processor",
    description="Process audio files through Azure VoiceLive SDK for evaluation",
    version="1.0.0"
)


# Request/Response Models

class RunAudioTestsRequest(BaseModel):
    """Request to start audio processing job."""
    dataset_path: str = Field(
        ...,
        description="Path to dataset in blob storage (e.g., 'Eiffel_Tower_Visit_1' or 'datasets/sample.jsonl')"
    )
    session_mode: str = Field(
        default="per-conversation",
        description="How to group files: 'per-conversation', 'per-file', or 'single'"
    )
    max_workers: int = Field(
        default=4,
        description="Maximum parallel workers (for future use)"
    )
    session_config: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional session configuration override"
    )


class RunAudioTestsResponse(BaseModel):
    """Response when starting a job."""
    status: str
    job_id: str
    message: str
    check_status_instruction: str


class CheckJobStatusRequest(BaseModel):
    """Request to check job status."""
    job_id: str = Field(..., description="The job ID returned from run_voicelive_audio_tests")


class JobProgressResponse(BaseModel):
    """Job progress information."""
    total_files: int
    files_processed: int
    files_failed: int
    percent_complete: float
    current_file: Optional[str]
    current_conversation: Optional[str]


class JobStatusResponse(BaseModel):
    """Job status response."""
    job_id: str
    status: str
    created_at: str
    started_at: Optional[str]
    completed_at: Optional[str]
    duration_seconds: Optional[float]
    dataset_path: str
    session_mode: str
    progress: JobProgressResponse
    output_path: Optional[str]
    results_count: int
    error: Optional[str]
    message: str


# Endpoints

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "running_jobs": job_manager.get_running_count()
    }


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "VoiceLive Audio Processor",
        "version": "1.0.0",
        "endpoints": {
            "/health": "Health check",
            "/run_voicelive_audio_tests": "POST - Start audio processing job",
            "/check_job_status": "POST - Check job status",
            "/jobs": "GET - List all jobs",
            "/jobs/{job_id}": "GET - Get job details"
        }
    }


@app.post("/run_voicelive_audio_tests", response_model=RunAudioTestsResponse)
async def run_voicelive_audio_tests(
    request: RunAudioTestsRequest,
):
    """
    Start a VoiceLive audio processing job.
    
    Processes raw audio files through Azure VoiceLive SDK and generates
    evaluation-ready JSONL with query/response fields.
    
    This is an async operation - returns immediately with job_id for status polling.
    """
    try:
        # Validate session mode
        if request.session_mode not in ["per-conversation", "per-file", "single"]:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid session_mode: {request.session_mode}. Must be 'per-conversation', 'per-file', or 'single'"
            )
        
        # Start processing job
        job_id = await start_processing_job(
            dataset_path=request.dataset_path,
            session_mode=request.session_mode,
            max_workers=request.max_workers,
            session_config=request.session_config
        )
        
        return RunAudioTestsResponse(
            status="started",
            job_id=job_id,
            message="VoiceLive audio processing job started. Use check_job_status to monitor progress.",
            check_status_instruction=f"Call check_job_status with job_id: {job_id}"
        )
        
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.exception(f"Error starting job: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/check_job_status", response_model=JobStatusResponse)
async def check_job_status(
    request: CheckJobStatusRequest,
):
    """
    Check the status of a VoiceLive processing job.
    
    Returns current status, progress, and output path when completed.
    """
    job = await job_manager.get_job(request.job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {request.job_id}")
    
    # Build message based on status
    if job.status == JobStatus.COMPLETED:
        message = f"Processing completed. Output available at: {job.output_path}"
    elif job.status == JobStatus.FAILED:
        message = f"Processing failed: {job.error}"
    elif job.status == JobStatus.RUNNING:
        progress = job.progress
        message = f"Processing in progress: {progress.files_processed}/{progress.total_files} files completed"
    elif job.status == JobStatus.QUEUED:
        message = "Job is queued and will start soon"
    else:
        message = f"Job status: {job.status.value}"
    
    job_dict = job.to_dict()
    
    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status.value,
        created_at=job_dict["created_at"],
        started_at=job_dict["started_at"],
        completed_at=job_dict["completed_at"],
        duration_seconds=job_dict["duration_seconds"],
        dataset_path=job.dataset_path,
        session_mode=job.session_mode,
        progress=JobProgressResponse(**job_dict["progress"]),
        output_path=job.output_path,
        results_count=job.results_count,
        error=job.error,
        message=message
    )


@app.get("/jobs")
async def list_jobs(
    status: Optional[str] = None,
    limit: int = 20
):
    """List all jobs, optionally filtered by status."""
    filter_status = None
    if status:
        try:
            filter_status = JobStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    
    jobs = await job_manager.list_jobs(status=filter_status, limit=limit)
    
    return {
        "jobs": [j.to_dict() for j in jobs],
        "total": len(jobs)
    }


@app.get("/jobs/{job_id}")
async def get_job(job_id: str):
    """Get details of a specific job."""
    job = await job_manager.get_job(job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    
    return job.to_dict()


@app.delete("/jobs/{job_id}")
async def cancel_job(job_id: str):
    """Cancel a running job."""
    cancelled = await job_manager.cancel_job(job_id)
    
    if not cancelled:
        job = await job_manager.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
        raise HTTPException(
            status_code=400,
            detail=f"Job cannot be cancelled (status: {job.status.value})"
        )
    
    return {"status": "cancelled", "job_id": job_id}


@app.get("/config/default")
async def get_default_config():
    """Get the default session configuration."""
    from .config import DEFAULT_SESSION_CONFIG
    return DEFAULT_SESSION_CONFIG.to_dict()


# OpenAPI customization for agent integration
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    
    from fastapi.openapi.utils import get_openapi
    
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    
    # Add server URL placeholder
    openapi_schema["servers"] = [
        {
            "url": "https://{containerAppName}.{region}.azurecontainerapps.io",
            "variables": {
                "containerAppName": {"default": "voicelive-processor"},
                "region": {"default": "eastus2"}
            }
        }
    ]
    
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi
