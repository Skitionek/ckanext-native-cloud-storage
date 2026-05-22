import logging
import os
import mimetypes
import json
from datetime import datetime, timedelta, timezone

from azure.storage.filedatalake import (
    DataLakeServiceClient,
    FileSasPermissions,
    generate_file_sas,
)
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
    Azure Data Lake Gen2 implementation for CKAN file uploads.

    The class name is kept for CKAN/plugin compatibility.
    """
    
    def __init__(self, upload_to='', old_filename=None):
        """
        Initialize Azure Blob Storage uploader
        
        :param upload_to: Directory path within container
        :param old_filename: Previous filename for updates
        """
        super().__init__(upload_to, old_filename)
        
        # Azure Data Lake configuration
        self.account_name = config.get('ckanext.native_cloud_storage.azure.account_name', '')
        self.account_key = config.get('ckanext.native_cloud_storage.azure.account_key', '')
        self.connection_string = config.get('ckanext.native_cloud_storage.azure.connection_string', '')
        configured_fs = config.get('ckanext.native_cloud_storage.azure.file_system_name', '')
        configured_container = config.get('ckanext.native_cloud_storage.azure.container_name', '')
        self.file_system_name = configured_fs or configured_container or 'ckan-storage'
        # Keep legacy attribute for backward compatibility.
        self.container_name = self.file_system_name
        self.use_emulator = toolkit.asbool(config.get('ckanext.native_cloud_storage.azure.use_emulator', False))

        # Service Bus configuration (preferred, based on azure-data-lake-fs).
        self.servicebus_connection_string = config.get('ckanext.native_cloud_storage.azure.servicebus_connection_string', '')
        self.servicebus_queue_name = config.get('ckanext.native_cloud_storage.azure.servicebus_queue_name', 'ckan-file-events')

        # Legacy Event Hub configuration for backward compatibility.
        self.eventhub_connection_string = config.get('ckanext.native_cloud_storage.azure.eventhub_connection_string', '')
        self.eventhub_name = config.get('ckanext.native_cloud_storage.azure.eventhub_name', 'ckan-file-events')

        self._service_client = None
        self._file_system_client = None
        
    @property
    def data_lake_service_client(self):
        """Lazy initialization of Azure Data Lake Service Client."""
        if self._service_client is None:
            self._service_client = self._create_data_lake_service_client()
        return self._service_client
    
    @property
    def file_system_client(self):
        """Lazy initialization of Azure Data Lake FileSystem client."""
        if self._file_system_client is None:
            self._file_system_client = self.data_lake_service_client.get_file_system_client(
                file_system=self.file_system_name
            )
            self._ensure_file_system_exists()
        return self._file_system_client
    
    @property
    def blob_service_client(self):
        """Compatibility alias for older tests/callers."""
        return self.data_lake_service_client

    @property
    def container_client(self):
        """Compatibility alias for older tests/callers."""
        return self.file_system_client

    def _create_data_lake_service_client(self):
        """Create Azure Data Lake Service Client with appropriate authentication."""
        try:
            if self.use_emulator:
                # Use development storage emulator (Azurite).
                connection_string = "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"
                log.info("Using Azure Storage Emulator")
                return DataLakeServiceClient.from_connection_string(connection_string)
            elif self.connection_string:
                return DataLakeServiceClient.from_connection_string(self.connection_string)
            elif self.account_name and self.account_key:
                return DataLakeServiceClient(
                    account_url=f"https://{self.account_name}.dfs.core.windows.net",
                    credential=self.account_key
                )
            elif self.account_name:
                credential = DefaultAzureCredential()
                return DataLakeServiceClient(
                    account_url=f"https://{self.account_name}.dfs.core.windows.net",
                    credential=credential
                )
            else:
                raise ValueError("Azure Storage configuration is incomplete. Please provide either connection_string, account_name with account_key, or account_name for managed identity.")
                
        except Exception as e:
            log.error(f"Failed to create Azure Data Lake Service Client: {e}")
            raise
    
    def _ensure_file_system_exists(self):
        """Ensure the target file system exists."""
        try:
            self.file_system_client.get_file_system_properties()
        except ResourceNotFoundError:
            log.info(f"Creating file system: {self.file_system_name}")
            self.file_system_client.create_file_system()
    
    def is_emulator_mode(self):
        """Check if running in emulator mode"""
        return self.use_emulator
    
    def test_connection(self):
        """Test Azure Storage connection"""
        try:
            self.file_system_client.get_file_system_properties()
            return True
        except Exception as e:
            log.error(f"Azure Storage connection test failed: {e}")
            return False
    
    def upload(self, max_size=2):
        """Upload file to Azure Data Lake Storage Gen2."""
        if self.filename is None:
            return
            
        try:
            # Generate path
            file_path = self._generate_blob_name()
            
            if hasattr(self.upload_field_storage, 'file'):
                content = self.upload_field_storage.file.read()
                self.upload_field_storage.file.seek(0)
            else:
                content = self.upload_field_storage.read()

            content_type = mimetypes.guess_type(self.filename)[0] or 'application/octet-stream'
            
            file_client = self.file_system_client.get_file_client(file_path)
            file_client.upload_data(
                data=content,
                overwrite=True,
                metadata={
                    'original_filename': self.filename,
                    'upload_time': datetime.now(timezone.utc).isoformat(),
                    'ckan_resource': 'true'
                }
            )

            # Keep content type as a metadata fallback in case setting HTTP headers
            # is not supported by the target endpoint/emulator.
            try:
                file_client.set_http_headers(content_settings={'content_type': content_type})
            except Exception:  # pragma: no cover - best-effort compatibility
                pass
            
            self.filename = file_path
            self.url = self._get_blob_url(file_path)
            
            log.info(f"File uploaded successfully: {file_path}")
            
            self._send_file_event('upload', file_path)
            
        except Exception as e:
            log.error(f"Failed to upload file to Azure Data Lake: {e}")
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
        """Get URL for a file path with SAS token when possible."""
        file_path = blob_name.lstrip('/')
        file_client = self.file_system_client.get_file_client(file_path)
        try:
            if self.use_emulator:
                return file_client.url

            directory_name, _, file_name = file_path.rpartition('/')
            if not file_name:
                raise ValueError('Invalid file path for SAS URL generation')

            expiry = datetime.now(timezone.utc) + timedelta(hours=1)
            permission = FileSasPermissions.from_string("r")

            if self.account_key:
                sas_token = generate_file_sas(
                    account_name=self.account_name,
                    file_system_name=self.file_system_name,
                    directory_name=directory_name,
                    file_name=file_name,
                    credential=self.account_key,
                    permission=permission,
                    expiry=expiry,
                )
            else:
                start = datetime.now(timezone.utc) - timedelta(minutes=5)
                user_delegation_key = self.data_lake_service_client.get_user_delegation_key(
                    key_start_time=start,
                    key_expiry_time=expiry,
                )
                sas_token = generate_file_sas(
                    account_name=self.account_name,
                    file_system_name=self.file_system_name,
                    directory_name=directory_name,
                    file_name=file_name,
                    credential=user_delegation_key,
                    permission=permission,
                    expiry=expiry,
                )

            return f"{file_client.url}?{sas_token}"
                
        except Exception as e:
            log.error(f"Failed to generate file URL: {e}")
            return file_client.url
    
    def _send_file_event(self, event_type, blob_name):
        """Send file event to Service Bus queue, fallback to Event Hub."""
        event_data = {
            'event_type': event_type,
            'blob_name': blob_name,
            'container_name': self.file_system_name,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'source': 'ckan_native_cloud_storage'
        }

        if self.servicebus_connection_string:
            self._send_servicebus_event(event_data)
            return

        if self.eventhub_connection_string or self.use_emulator:
            self._send_eventhub_event(event_data)

    def _send_servicebus_event(self, event_data):
        """Send file event to Azure Service Bus queue."""
        try:
            from azure.servicebus import ServiceBusClient, ServiceBusMessage

            with ServiceBusClient.from_connection_string(self.servicebus_connection_string) as client:
                with client.get_queue_sender(queue_name=self.servicebus_queue_name) as sender:
                    sender.send_messages(ServiceBusMessage(json.dumps(event_data)))

            log.info(
                f"File event sent to Service Bus queue: "
                f"{event_data['event_type']} - {event_data['blob_name']}"
            )
        except Exception as e:
            log.warning(f"Failed to send file event to Service Bus: {e}")

    def _send_eventhub_event(self, event_data):
        """Legacy Event Hub publisher for backward compatibility."""
        try:
            from azure.eventhub import EventData, EventHubProducerClient

            if self.use_emulator:
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
            with producer:
                event_data_batch = producer.create_batch()
                event_data_batch.add(EventData(json.dumps(event_data)))
                producer.send_batch(event_data_batch)
            log.info(
                f"File event sent to Event Hub: "
                f"{event_data['event_type']} - {event_data['blob_name']}"
            )
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
                                file_client = self.file_system_client.get_file_client(blob_name)
                                
                                try:
                                    file_client.get_file_properties()
                                    log.info(f"Blob already exists, skipping: {blob_name}")
                                    continue
                                except ResourceNotFoundError:
                                    pass
                                
                                file_client.upload_data(
                                    data=f.read(),
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