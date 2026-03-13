import logging
import os
import mimetypes
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from azure.storage.blob import BlobServiceClient, BlobClient, ContainerClient, generate_blob_sas, BlobSasPermissions
from azure.core.exceptions import ResourceNotFoundError, AzureError
from azure.identity import DefaultAzureCredential

# Allow importing without a full CKAN installation (e.g. for unit tests)
try:
    import ckan.lib.uploader as _ckan_uploader
    from ckan.common import config
    import ckan.plugins.toolkit as toolkit
    _UploadBase = _ckan_uploader.Upload
except ImportError:
    class _UploadBase:  # type: ignore[no-redef]
        """Minimal Upload shim used when CKAN is not installed (e.g. in tests)."""
        def __init__(self, upload_to='', old_filename=None):
            self.upload_to = upload_to
            self.old_filename = old_filename
            self.filename = None
            self.upload_field_storage = None

    class _MockConfig:
        def __init__(self):
            self._data: dict = {}

        def get(self, key, default=None):
            return self._data.get(key, default)

    class _MockToolkit:
        @staticmethod
        def asbool(value, default=False):
            if isinstance(value, bool):
                return value
            return str(value).lower() in ('true', '1', 'yes')

    config = _MockConfig()  # type: ignore[assignment]
    toolkit = _MockToolkit()  # type: ignore[assignment]

log = logging.getLogger(__name__)


class AzureBlobStorage(_UploadBase):
    """
    Azure Blob Storage implementation for CKAN file uploads
    """
    
    def __init__(self, upload_to='', old_filename=None):
        """
        Initialize Azure Blob Storage uploader
        
        :param upload_to: Directory path within container
        :param old_filename: Previous filename for updates
        """
        super().__init__(upload_to, old_filename)
        
        # Azure Storage configuration
        self.account_name = config.get('ckanext.native_cloud_storage.azure.account_name', '')
        self.account_key = config.get('ckanext.native_cloud_storage.azure.account_key', '')
        self.connection_string = config.get('ckanext.native_cloud_storage.azure.connection_string', '')
        self.container_name = config.get('ckanext.native_cloud_storage.azure.container_name', 'ckan-storage')
        self.use_emulator = toolkit.asbool(config.get('ckanext.native_cloud_storage.azure.use_emulator', False))
        
        # Event Hub configuration (for file events)
        self.eventhub_connection_string = config.get('ckanext.native_cloud_storage.azure.eventhub_connection_string', '')
        self.eventhub_name = config.get('ckanext.native_cloud_storage.azure.eventhub_name', 'ckan-file-events')
        
        self._blob_service_client = None
        self._container_client = None
        
    @property
    def blob_service_client(self):
        """Lazy initialization of Azure Blob Service Client"""
        if self._blob_service_client is None:
            self._blob_service_client = self._create_blob_service_client()
        return self._blob_service_client
    
    @property
    def container_client(self):
        """Lazy initialization of Azure Container Client"""
        if self._container_client is None:
            self._container_client = self.blob_service_client.get_container_client(self.container_name)
            self._ensure_container_exists()
        return self._container_client
    
    def _create_blob_service_client(self):
        """Create Azure Blob Service Client with appropriate authentication"""
        try:
            if self.use_emulator:
                # Use development storage emulator
                connection_string = "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"
                log.info("Using Azure Storage Emulator")
                return BlobServiceClient.from_connection_string(connection_string)
            elif self.connection_string:
                # Use connection string
                return BlobServiceClient.from_connection_string(self.connection_string)
            elif self.account_name and self.account_key:
                # Use account name and key
                return BlobServiceClient(
                    account_url=f"https://{self.account_name}.blob.core.windows.net",
                    credential=self.account_key
                )
            elif self.account_name:
                # Use managed identity / default credential
                credential = DefaultAzureCredential()
                return BlobServiceClient(
                    account_url=f"https://{self.account_name}.blob.core.windows.net",
                    credential=credential
                )
            else:
                raise ValueError("Azure Storage configuration is incomplete. Please provide either connection_string, account_name with account_key, or account_name for managed identity.")
                
        except Exception as e:
            log.error(f"Failed to create Azure Blob Service Client: {e}")
            raise
    
    def _ensure_container_exists(self):
        """Ensure the storage container exists"""
        try:
            self.container_client.get_container_properties()
        except ResourceNotFoundError:
            log.info(f"Creating container: {self.container_name}")
            self.container_client.create_container()
    
    def is_emulator_mode(self):
        """Check if running in emulator mode"""
        return self.use_emulator
    
    def test_connection(self):
        """Test Azure Storage connection"""
        try:
            self.container_client.get_container_properties()
            return True
        except Exception as e:
            log.error(f"Azure Storage connection test failed: {e}")
            return False
    
    def upload(self, max_size=2):
        """Upload file to Azure Blob Storage"""
        if self.filename is None:
            return
            
        try:
            # Generate blob name
            blob_name = self._generate_blob_name()
            
            # Get file content
            if hasattr(self.upload_field_storage, 'file'):
                content = self.upload_field_storage.file.read()
                self.upload_field_storage.file.seek(0)
            else:
                content = self.upload_field_storage.read()
            
            # Detect content type
            content_type = mimetypes.guess_type(self.filename)[0] or 'application/octet-stream'
            
            # Upload to Azure Blob Storage
            blob_client = self.container_client.get_blob_client(blob_name)
            blob_client.upload_blob(
                content,
                blob_type="BlockBlob",
                content_settings={'content_type': content_type},
                overwrite=True,
                metadata={
                    'original_filename': self.filename,
                    'upload_time': datetime.now(timezone.utc).isoformat(),
                    'ckan_resource': 'true'
                }
            )
            
            # Store the blob URL
            self.filename = blob_name
            self.url = self._get_blob_url(blob_name)
            
            log.info(f"File uploaded successfully: {blob_name}")
            
            # Send event notification if Event Hub is configured
            self._send_file_event('upload', blob_name)
            
        except Exception as e:
            log.error(f"Failed to upload file to Azure Blob Storage: {e}")
            raise
    
    def _generate_blob_name(self):
        """Generate unique blob name with path"""
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
        safe_filename = self.filename.replace(' ', '_').replace('/', '_')
        
        if self.upload_to:
            return f"{self.upload_to}/{timestamp}_{safe_filename}"
        else:
            return f"{timestamp}_{safe_filename}"
    
    def _get_blob_url(self, blob_name):
        """Get public URL for blob with SAS token if needed"""
        blob_client = self.container_client.get_blob_client(blob_name)
        try:
            if self.use_emulator:
                # For emulator, return direct URL
                return blob_client.url
            else:
                # Generate SAS token for secure access
                sas_token = generate_blob_sas(
                    account_name=self.account_name,
                    container_name=self.container_name,
                    blob_name=blob_name,
                    account_key=self.account_key,
                    permission=BlobSasPermissions(read=True),
                    expiry=datetime.now(timezone.utc) + timedelta(hours=1)
                )
                return f"{blob_client.url}?{sas_token}"
                
        except Exception as e:
            log.error(f"Failed to generate blob URL: {e}")
            return blob_client.url  # Fallback to direct URL
    
    def _send_file_event(self, event_type, blob_name):
        """Send file event to Azure Event Hub"""
        # Skip entirely when Event Hub is not configured AND we are not in emulator
        # mode (emulator mode uses a built-in default connection string as a fallback).
        if not self.eventhub_connection_string and not self.use_emulator:
            return
            
        try:
            from azure.eventhub import EventHubProducerClient, EventData
            
            if self.use_emulator:
                # Use configured connection string or fall back to default emulator value
                connection_string = self.eventhub_connection_string or (
                    "Endpoint=sb://localhost:5672/;"
                    "SharedAccessKeyName=RootManageSharedAccessKey;"
                    "SharedAccessKey=SAS_KEY_VALUE;"
                    "UseDevelopmentEmulator=true"
                )
            else:
                connection_string = self.eventhub_connection_string
            
            producer = EventHubProducerClient.from_connection_string(
                conn_str=connection_string,
                eventhub_name=self.eventhub_name
            )
            
            event_data = {
                'event_type': event_type,
                'blob_name': blob_name,
                'container_name': self.container_name,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'source': 'ckan_native_cloud_storage'
            }
            
            with producer:
                event_data_batch = producer.create_batch()
                event_data_batch.add(EventData(str(event_data)))
                producer.send_batch(event_data_batch)
                
            log.info(f"File event sent to Event Hub: {event_type} - {blob_name}")
            
        except Exception as e:
            log.warning(f"Failed to send file event to Event Hub: {e}")
    
    def migrate_existing_files(self, dry_run=True):
        """Migrate existing local files to Azure Blob Storage"""
        results = {
            'processed': 0,
            'migrated': 0,
            'errors': 0,
            'files': []
        }
        
        # Get CKAN storage path
        storage_path = config.get('ckan.storage_path', '/var/lib/ckan/default')
        resources_path = os.path.join(storage_path, 'resources')
        
        if not os.path.exists(resources_path):
            log.warning(f"Resources directory not found: {resources_path}")
            return results
        
        try:
            for root, dirs, files in os.walk(resources_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, resources_path)
                    
                    results['processed'] += 1
                    
                    try:
                        if not dry_run:
                            # Upload file to Azure
                            with open(file_path, 'rb') as f:
                                blob_name = f"migrated/{rel_path}"
                                blob_client = self.container_client.get_blob_client(blob_name)
                                
                                # Check if blob already exists
                                try:
                                    blob_client.get_blob_properties()
                                    log.info(f"Blob already exists, skipping: {blob_name}")
                                    continue
                                except ResourceNotFoundError:
                                    pass
                                
                                blob_client.upload_blob(
                                    f,
                                    blob_type="BlockBlob",
                                    overwrite=False,
                                    metadata={
                                        'original_path': rel_path,
                                        'migration_time': datetime.now(timezone.utc).isoformat(),
                                        'migrated_from': 'local_storage'
                                    }
                                )
                                
                                results['migrated'] += 1
                                log.info(f"Migrated file: {rel_path} -> {blob_name}")
                        
                        results['files'].append({
                            'local_path': rel_path,
                            'blob_name': f"migrated/{rel_path}" if not dry_run else None,
                            'size': os.path.getsize(file_path),
                            'status': 'migrated' if not dry_run else 'ready_for_migration'
                        })
                        
                    except Exception as e:
                        results['errors'] += 1
                        log.error(f"Failed to migrate file {rel_path}: {e}")
                        results['files'].append({
                            'local_path': rel_path,
                            'error': str(e),
                            'status': 'error'
                        })
                        
        except Exception as e:
            log.error(f"Migration process failed: {e}")
            raise
        
        return results