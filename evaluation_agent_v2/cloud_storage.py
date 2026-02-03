"""
Cloud Storage Module for VoiceLive Evaluation Agent

Provides Azure Blob Storage integration for cloud deployments.
Supports both cloud mode (blob storage) and local mode (filesystem).

Environment Variables:
    AZURE_STORAGE_ACCOUNT: Storage account name (enables cloud mode)
    AZURE_STORAGE_DATASETS_CONTAINER: Container for datasets (default: datasets)
    AZURE_STORAGE_OUTPUTS_CONTAINER: Container for outputs (default: outputs)
    
Usage:
    from cloud_storage import CloudStorageClient, is_cloud_mode
    
    if is_cloud_mode():
        client = CloudStorageClient()
        datasets = client.list_datasets()
        local_path = client.download_dataset("path/to/dataset.jsonl")
        client.upload_results("local/results.jsonl", "remote/results.jsonl")
"""

import os
import tempfile
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import dataclass


def is_cloud_mode() -> bool:
    """Check if running in cloud mode (Azure Blob Storage enabled)."""
    return os.environ.get("AZURE_STORAGE_ACCOUNT") is not None


@dataclass
class BlobInfo:
    """Information about a blob in storage."""
    name: str
    size: int
    last_modified: str
    container: str
    
    @property
    def full_path(self) -> str:
        return f"{self.container}/{self.name}"


class CloudStorageClient:
    """
    Azure Blob Storage client for cloud deployments.
    
    Provides methods to:
    - List datasets in the datasets container
    - Download datasets to local temp files for processing
    - Upload evaluation results to the outputs container
    """
    
    def __init__(
        self,
        account_name: Optional[str] = None,
        datasets_container: Optional[str] = None,
        outputs_container: Optional[str] = None,
    ):
        """
        Initialize the cloud storage client.
        
        Args:
            account_name: Storage account name (default: from env var)
            datasets_container: Container for datasets (default: from env var or 'datasets')
            outputs_container: Container for outputs (default: from env var or 'outputs')
        """
        self.account_name = account_name or os.environ.get("AZURE_STORAGE_ACCOUNT")
        self.datasets_container = datasets_container or os.environ.get(
            "AZURE_STORAGE_DATASETS_CONTAINER", "datasets"
        )
        self.outputs_container = outputs_container or os.environ.get(
            "AZURE_STORAGE_OUTPUTS_CONTAINER", "outputs"
        )
        
        if not self.account_name:
            raise ValueError(
                "Storage account name required. Set AZURE_STORAGE_ACCOUNT environment variable."
            )
        
        # Lazy-load the Azure SDK
        self._blob_service_client = None
    
    @property
    def blob_service_client(self):
        """Lazy-load the BlobServiceClient."""
        if self._blob_service_client is None:
            from azure.identity import DefaultAzureCredential
            from azure.storage.blob import BlobServiceClient
            
            account_url = f"https://{self.account_name}.blob.core.windows.net"
            credential = DefaultAzureCredential()
            self._blob_service_client = BlobServiceClient(account_url, credential=credential)
        
        return self._blob_service_client
    
    def list_datasets(self, prefix: str = "", extensions: List[str] = None) -> List[BlobInfo]:
        """
        List datasets in the datasets container.
        
        Args:
            prefix: Optional prefix to filter blobs (e.g., "project-a/")
            extensions: File extensions to include (default: ['.jsonl'])
        
        Returns:
            List of BlobInfo objects for matching blobs
        """
        if extensions is None:
            extensions = ['.jsonl']
        
        container_client = self.blob_service_client.get_container_client(self.datasets_container)
        blobs = []
        
        for blob in container_client.list_blobs(name_starts_with=prefix):
            # Filter by extension
            if any(blob.name.lower().endswith(ext) for ext in extensions):
                blobs.append(BlobInfo(
                    name=blob.name,
                    size=blob.size,
                    last_modified=str(blob.last_modified),
                    container=self.datasets_container
                ))
        
        return blobs
    
    def download_dataset(self, blob_path: str, local_path: Optional[str] = None) -> str:
        """
        Download a dataset from blob storage to a local file.
        
        Args:
            blob_path: Path to the blob (relative to datasets container)
            local_path: Local path to save to (default: temp file)
        
        Returns:
            Local file path where the dataset was saved
        """
        container_client = self.blob_service_client.get_container_client(self.datasets_container)
        blob_client = container_client.get_blob_client(blob_path)
        
        # Determine local path
        if local_path is None:
            # Create temp file with same extension
            suffix = Path(blob_path).suffix or '.jsonl'
            fd, local_path = tempfile.mkstemp(suffix=suffix)
            os.close(fd)
        
        # Ensure directory exists
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        
        # Download
        with open(local_path, "wb") as f:
            download_stream = blob_client.download_blob()
            f.write(download_stream.readall())
        
        return local_path
    
    def upload_results(
        self,
        local_path: str,
        blob_path: str,
        overwrite: bool = True
    ) -> str:
        """
        Upload evaluation results to the outputs container.
        
        Args:
            local_path: Local file path to upload
            blob_path: Destination path in the outputs container
            overwrite: Whether to overwrite existing blob
        
        Returns:
            Full blob URL
        """
        container_client = self.blob_service_client.get_container_client(self.outputs_container)
        blob_client = container_client.get_blob_client(blob_path)
        
        with open(local_path, "rb") as f:
            blob_client.upload_blob(f, overwrite=overwrite)
        
        return blob_client.url
    
    def upload_directory(
        self,
        local_dir: str,
        blob_prefix: str,
        extensions: List[str] = None
    ) -> List[str]:
        """
        Upload a directory of files to the outputs container.
        
        Args:
            local_dir: Local directory to upload
            blob_prefix: Prefix for all uploaded blobs
            extensions: File extensions to include (default: all)
        
        Returns:
            List of uploaded blob URLs
        """
        uploaded = []
        local_path = Path(local_dir)
        
        for file_path in local_path.rglob("*"):
            if file_path.is_file():
                # Check extension filter
                if extensions and not any(file_path.suffix.lower() == ext for ext in extensions):
                    continue
                
                # Calculate relative path for blob
                relative_path = file_path.relative_to(local_path)
                blob_path = f"{blob_prefix}/{relative_path}".replace("\\", "/")
                
                url = self.upload_results(str(file_path), blob_path)
                uploaded.append(url)
        
        return uploaded
    
    def download_to_temp_dir(self, blob_prefix: str) -> str:
        """
        Download all blobs with a prefix to a temp directory.
        
        Args:
            blob_prefix: Prefix to filter blobs (e.g., "2026-02-03_10-30-00/")
        
        Returns:
            Path to temp directory containing downloaded files
        """
        container_client = self.blob_service_client.get_container_client(self.outputs_container)
        temp_dir = tempfile.mkdtemp()
        
        for blob in container_client.list_blobs(name_starts_with=blob_prefix):
            # Calculate local path
            relative_path = blob.name[len(blob_prefix):].lstrip("/")
            local_path = Path(temp_dir) / relative_path
            
            # Ensure directory exists
            local_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Download
            blob_client = container_client.get_blob_client(blob.name)
            with open(local_path, "wb") as f:
                download_stream = blob_client.download_blob()
                f.write(download_stream.readall())
        
        return temp_dir
    
    def get_dataset_info(self, blob_path: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a dataset blob.
        
        Args:
            blob_path: Path to the blob
        
        Returns:
            Dictionary with blob properties, or None if not found
        """
        container_client = self.blob_service_client.get_container_client(self.datasets_container)
        blob_client = container_client.get_blob_client(blob_path)
        
        try:
            props = blob_client.get_blob_properties()
            return {
                "name": blob_path,
                "size": props.size,
                "last_modified": str(props.last_modified),
                "content_type": props.content_settings.content_type,
                "container": self.datasets_container,
                "url": blob_client.url
            }
        except Exception:
            return None


def get_storage_client() -> Optional[CloudStorageClient]:
    """
    Get a CloudStorageClient if in cloud mode, otherwise None.
    
    Returns:
        CloudStorageClient instance or None if in local mode
    """
    if is_cloud_mode():
        return CloudStorageClient()
    return None
