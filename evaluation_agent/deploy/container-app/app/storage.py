"""
VoiceLive Audio Processor - Blob Storage Integration

Handles reading datasets and writing outputs to Azure Blob Storage.
"""

import os
import json
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContainerClient

logger = logging.getLogger(__name__)


@dataclass
class DatasetEntry:
    """A single entry from a dataset JSONL file."""
    wav_path: str
    question: Optional[str] = None
    answer: Optional[str] = None  # Ground truth
    conversation_id: Optional[str] = None
    system_prompt: Optional[str] = None
    tool_definitions: Optional[List[Dict]] = None
    
    # For pre-existing evaluation data
    query: Optional[str] = None
    response: Optional[str] = None
    
    # Barge-in metadata
    barge_in: bool = False
    
    # Raw entry for passthrough
    raw: Dict[str, Any] = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DatasetEntry":
        # Normalize list-type answers (e.g. speech-trivia-qa uses ["Paris", "City of Paris"])
        answer_raw = data.get("Answer")
        if isinstance(answer_raw, list):
            answer_raw = " OR ".join(str(a) for a in answer_raw if a) if answer_raw else None
        return cls(
            wav_path=data.get("WavPath") or data.get("audio_path") or "",
            question=data.get("Question"),
            answer=answer_raw,
            conversation_id=data.get("conversationID"),
            system_prompt=data.get("system_prompt"),
            tool_definitions=data.get("tool_definitions"),
            query=data.get("query"),
            response=data.get("response"),
            barge_in=bool(data.get("barge_in", False)),
            raw=data
        )
    
    def has_audio(self) -> bool:
        return bool(self.wav_path)
    
    def has_eval_data(self) -> bool:
        return bool(self.query and self.response)


class BlobStorageClient:
    """Client for Azure Blob Storage operations."""
    
    def __init__(
        self,
        account_name: Optional[str] = None,
        datasets_container: str = "datasets",
        outputs_container: str = "outputs"
    ):
        self.account_name = account_name or os.environ.get("AZURE_STORAGE_ACCOUNT")
        self.datasets_container = datasets_container
        self.outputs_container = outputs_container
        
        if not self.account_name:
            raise ValueError("AZURE_STORAGE_ACCOUNT environment variable required")
        
        credential = DefaultAzureCredential()
        self._client = BlobServiceClient(
            f"https://{self.account_name}.blob.core.windows.net",
            credential=credential
        )
        logger.info(f"Blob storage client initialized: {self.account_name}")
    
    def _normalize_path(self, path: str, container: str) -> str:
        """Normalize blob path (strip container prefix, leading slashes, etc.)."""
        path = path.strip().strip('"\'')
        
        # Remove container prefix if present
        prefixes = [f"{container}/", f"/{container}/", container + "\\"]
        for prefix in prefixes:
            if path.startswith(prefix):
                path = path[len(prefix):]
                break
        
        # Remove leading slashes
        path = path.lstrip("/\\")
        
        return path
    
    def list_datasets(self, prefix: str = "") -> List[Dict[str, Any]]:
        """List available datasets in the datasets container."""
        container_client = self._client.get_container_client(self.datasets_container)
        datasets = []
        
        try:
            blobs = container_client.list_blobs(name_starts_with=prefix if prefix else None)
            for blob in blobs:
                if blob.name.endswith('.jsonl'):
                    datasets.append({
                        "name": blob.name,
                        "size": blob.size,
                        "last_modified": blob.last_modified.isoformat() if blob.last_modified else None
                    })
        except Exception as e:
            logger.error(f"Error listing datasets: {e}")
        
        return datasets
    
    def download_dataset(self, path: str) -> Tuple[str, List[DatasetEntry], str]:
        """
        Download a dataset JSONL file and parse entries.
        
        Args:
            path: Path to dataset in blob storage (flexible format)
            
        Returns:
            Tuple of (local_path, list of DatasetEntry, blob_name)
        """
        normalized = self._normalize_path(path, self.datasets_container)
        container_client = self._client.get_container_client(self.datasets_container)
        
        # Try to find the blob
        blob_name = self._find_blob(container_client, normalized)
        if not blob_name:
            raise FileNotFoundError(f"Dataset not found: {path}")
        
        # Download to temp file
        blob_client = container_client.get_blob_client(blob_name)
        
        temp_dir = tempfile.mkdtemp(prefix="voicelive_dataset_")
        local_path = os.path.join(temp_dir, os.path.basename(blob_name))
        
        with open(local_path, 'wb') as f:
            download_stream = blob_client.download_blob()
            f.write(download_stream.readall())
        
        logger.info(f"Downloaded dataset: {blob_name} -> {local_path}")
        
        # Parse entries
        entries = []
        with open(local_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith(('#', '//')):
                    try:
                        data = json.loads(line)
                        entries.append(DatasetEntry.from_dict(data))
                    except json.JSONDecodeError as e:
                        logger.warning(f"Invalid JSON line: {e}")
        
        logger.info(f"Parsed {len(entries)} entries from dataset")
        return local_path, entries, blob_name
    
    def download_audio_file(self, wav_path: str, local_dir: str) -> str:
        """
        Download an audio file from blob storage.
        
        Args:
            wav_path: Path to audio file (can be relative to datasets container)
            local_dir: Local directory to save to
            
        Returns:
            Local path to downloaded file
        """
        container_client = self._client.get_container_client(self.datasets_container)
        normalized = self._normalize_path(wav_path, self.datasets_container)
        
        blob_name = self._find_blob(container_client, normalized, extensions=['.wav', '.mp3', '.pcm'])
        if not blob_name:
            raise FileNotFoundError(f"Audio file not found: {wav_path}")
        
        blob_client = container_client.get_blob_client(blob_name)
        local_path = os.path.join(local_dir, os.path.basename(blob_name))
        
        with open(local_path, 'wb') as f:
            download_stream = blob_client.download_blob()
            f.write(download_stream.readall())
        
        logger.debug(f"Downloaded audio: {blob_name}")
        return local_path
    
    def upload_results(
        self,
        job_id: str,
        results: List[Dict[str, Any]],
        metadata: Dict[str, Any] = None
    ) -> str:
        """
        Upload evaluation results to blob storage.
        
        Args:
            job_id: Unique job identifier
            results: List of result entries
            metadata: Optional job metadata
            
        Returns:
            Blob path to uploaded results
        """
        container_client = self._client.get_container_client(self.outputs_container)
        
        # Ensure container exists
        try:
            container_client.create_container()
        except Exception as e:
            if "ContainerAlreadyExists" not in str(e):
                logger.warning(f"Container creation issue: {e}")
        
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        base_path = f"voicelive_jobs/{job_id}"
        
        # Upload results JSONL
        results_blob = f"{base_path}/results_{timestamp}.jsonl"
        results_content = "\n".join(json.dumps(r, ensure_ascii=False) for r in results)
        
        blob_client = container_client.get_blob_client(results_blob)
        blob_client.upload_blob(results_content.encode('utf-8'), overwrite=True)
        logger.info(f"Uploaded results: {results_blob}")
        
        # Upload metadata
        if metadata:
            meta_blob = f"{base_path}/metadata.json"
            meta_content = json.dumps({
                **metadata,
                "results_file": results_blob,
                "uploaded_at": datetime.now(timezone.utc).isoformat(),
                "entry_count": len(results)
            }, indent=2)
            
            meta_client = container_client.get_blob_client(meta_blob)
            meta_client.upload_blob(meta_content.encode('utf-8'), overwrite=True)
        
        return results_blob
    
    def upload_log(self, job_id: str, log_content: str, log_name: str = "processing.log") -> str:
        """Upload a log file for a job."""
        container_client = self._client.get_container_client(self.outputs_container)
        
        blob_path = f"voicelive_jobs/{job_id}/logs/{log_name}"
        blob_client = container_client.get_blob_client(blob_path)
        blob_client.upload_blob(log_content.encode('utf-8'), overwrite=True)
        
        logger.debug(f"Uploaded log: {blob_path}")
        return blob_path
    
    def _find_blob(
        self,
        container_client: ContainerClient,
        path: str,
        extensions: List[str] = None
    ) -> Optional[str]:
        """Find a blob using flexible matching."""
        extensions = extensions or ['.jsonl', '.json']
        
        # Try exact match
        try:
            blob_client = container_client.get_blob_client(path)
            blob_client.get_blob_properties()
            return path
        except Exception:
            pass
        
        # Try with extensions
        for ext in extensions:
            if not path.endswith(ext):
                try:
                    test_path = path + ext
                    blob_client = container_client.get_blob_client(test_path)
                    blob_client.get_blob_properties()
                    return test_path
                except Exception:
                    pass
        
        # Try prefix match
        try:
            blobs = list(container_client.list_blobs(name_starts_with=path))
            if blobs:
                # Prefer files with matching extensions
                for blob in blobs:
                    for ext in extensions:
                        if blob.name.endswith(ext):
                            return blob.name
                # Fall back to first blob
                return blobs[0].name
        except Exception:
            pass
        
        return None
