"""Storage backends."""

import os
import shutil
from abc import ABC, abstractmethod


class StorageBackend(ABC):
    """Base storage backend."""

    @abstractmethod
    def upload(self, source_path: str, dest_path: str) -> str:
        """Upload file."""
        pass

    @abstractmethod
    def download(self, source_path: str, dest_path: str) -> None:
        """Download file."""
        pass

    @abstractmethod
    def delete(self, path: str) -> None:
        """Delete file."""
        pass

    @abstractmethod
    def exists(self, path: str) -> bool:
        """Check if file exists."""
        pass

    @abstractmethod
    def get_url(self, path: str, expires_in: int = 3600) -> str:
        """Get file URL."""
        pass


class LocalStorage(StorageBackend):
    """Local filesystem storage."""

    def __init__(self, base_path: str = "/tmp/storage") -> None:
        """Initialize local storage."""
        self.base_path = base_path
        os.makedirs(base_path, exist_ok=True)

    def upload(self, source_path: str, dest_path: str) -> str:
        """Upload file to local storage."""
        full_path = os.path.join(self.base_path, dest_path.lstrip("/"))
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        shutil.copy2(source_path, full_path)
        return full_path

    def download(self, source_path: str, dest_path: str) -> None:
        """Download file from local storage."""
        full_path = os.path.join(self.base_path, source_path.lstrip("/"))
        shutil.copy2(full_path, dest_path)

    def delete(self, path: str) -> None:
        """Delete file from local storage."""
        full_path = os.path.join(self.base_path, path.lstrip("/"))
        if os.path.exists(full_path):
            os.remove(full_path)

    def exists(self, path: str) -> bool:
        """Check if file exists in local storage."""
        full_path = os.path.join(self.base_path, path.lstrip("/"))
        return os.path.exists(full_path)

    def get_url(self, path: str, expires_in: int = 3600) -> str:
        """Get file URL."""
        return f"file://{os.path.join(self.base_path, path.lstrip('/'))}"


class S3Storage(StorageBackend):
    """AWS S3 storage."""

    def __init__(
        self,
        bucket: str,
        region: str = "us-east-1",
        access_key: str | None = None,
        secret_key: str | None = None,  # noqa: E501
    ) -> None:
        """Initialize S3 storage."""
        self.bucket = bucket
        # Implementation requires boto3

    def upload(self, source_path: str, dest_path: str) -> str:
        """Upload to S3."""
        # Implementation with boto3
        return f"s3://{self.bucket}/{dest_path}"

    def download(self, source_path: str, dest_path: str) -> None:
        """Download from S3."""
        pass

    def delete(self, path: str) -> None:
        """Delete from S3."""
        pass

    def exists(self, path: str) -> bool:
        """Check if exists in S3."""
        return False

    def get_url(self, path: str, expires_in: int = 3600) -> str:
        """Get presigned URL."""
        return f"https://{self.bucket}.s3.amazonaws.com/{path}"


class AzureStorage(StorageBackend):
    """Azure Blob storage."""

    def __init__(self, container: str, connection_string: str) -> None:
        """Initialize Azure storage."""
        self.container = container
        # Implementation requires azure-storage-blob

    def upload(self, source_path: str, dest_path: str) -> str:
        """Upload to Azure."""
        return f"https://{self.container}.blob.core.windows.net/{dest_path}"

    def download(self, source_path: str, dest_path: str) -> None:
        """Download from Azure."""
        pass

    def delete(self, path: str) -> None:
        """Delete from Azure."""
        pass

    def exists(self, path: str) -> bool:
        """Check if exists in Azure."""
        return False

    def get_url(self, path: str, expires_in: int = 3600) -> str:
        """Get SAS URL."""
        return f"https://{self.container}.blob.core.windows.net/{path}"
