import json
import logging
import mimetypes
import os
from datetime import datetime, timezone

from azure.identity import DefaultAzureCredential
from azure_data_lake_fs import (
    AzureDataLakeFsClient,
    AzureDataLakeFsConfig,
    SasPolicy,
    ServiceBusSettings,
)

# Allow importing without a full CKAN installation (e.g. for unit tests)
try:
    import ckan.lib.uploader as _ckan_uploader
    import ckan.plugins.toolkit as toolkit
    from ckan.common import config

    _UploadBase = _ckan_uploader.Upload
except ImportError:

    class _UploadBase:  # type: ignore[no-redef]
        """Minimal Upload shim used when CKAN is not installed (e.g. in tests)."""

        def __init__(self, upload_to="", old_filename=None):
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
            return str(value).lower() in ("true", "1", "yes")

    config = _MockConfig()  # type: ignore[assignment]
    toolkit = _MockToolkit()  # type: ignore[assignment]

log = logging.getLogger(__name__)

# Well-known development account of the Azurite storage emulator.
EMULATOR_CONNECTION_STRING = (
    "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;"
    "AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/"
    "K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"
)

# Read-only SAS URLs handed out for uploaded files stay valid for an hour.
SAS_POLICY = SasPolicy(expiry_minutes=60, download_permissions="r")


class AzureBlobStorage(_UploadBase):
    """
    Azure Data Lake Gen2 implementation for CKAN file uploads.

    The class name is kept for CKAN/plugin compatibility.
    """

    def __init__(self, upload_to="", old_filename=None):
        """
        Initialize Azure Blob Storage uploader

        :param upload_to: Directory path within container
        :param old_filename: Previous filename for updates
        """
        super().__init__(upload_to, old_filename)
        # CKAN's real ckan.lib.uploader.Upload.__init__ stores this
        # positional argument as self.object_type, not self.upload_to --
        # explicitly set it here so both the real CKAN base class and the
        # test shim expose a consistent self.upload_to attribute.
        self.upload_to = upload_to

        # CKAN's real ckan.lib.uploader.Upload stores the first positional
        # arg as ``self.object_type`` (and may perform filesystem side
        # effects such as creating a local upload directory) rather than
        # ``self.upload_to``. The lightweight shim used when CKAN isn't
        # installed does set ``self.upload_to``. Set it explicitly here so
        # behavior is identical against both the real CKAN base class and
        # the shim.
        self.upload_to = upload_to

        # Azure Data Lake configuration
        self.account_name = config.get(
            "ckanext.native_cloud_storage.azure.account_name", ""
        )
        self.account_key = config.get(
            "ckanext.native_cloud_storage.azure.account_key", ""
        )
        self.connection_string = config.get(
            "ckanext.native_cloud_storage.azure.connection_string", ""
        )
        configured_fs = config.get(
            "ckanext.native_cloud_storage.azure.file_system_name", ""
        )
        configured_container = config.get(
            "ckanext.native_cloud_storage.azure.container_name", ""
        )
        self.file_system_name = configured_fs or configured_container or "ckan-storage"
        # Keep legacy attribute for backward compatibility.
        self.container_name = self.file_system_name
        self.use_emulator = toolkit.asbool(
            config.get("ckanext.native_cloud_storage.azure.use_emulator", False)
        )

        # Service Bus configuration (preferred, based on azure-data-lake-fs).
        self.servicebus_connection_string = config.get(
            "ckanext.native_cloud_storage.azure.servicebus_connection_string", ""
        )
        self.servicebus_queue_name = config.get(
            "ckanext.native_cloud_storage.azure.servicebus_queue_name",
            "ckan-file-events",
        )

        # Legacy Event Hub configuration for backward compatibility.
        self.eventhub_connection_string = config.get(
            "ckanext.native_cloud_storage.azure.eventhub_connection_string", ""
        )
        self.eventhub_name = config.get(
            "ckanext.native_cloud_storage.azure.eventhub_name", "ckan-file-events"
        )

        self._client = None

    @property
    def client(self):
        """Lazily built azure-data-lake-fs client; ensures the file system exists."""
        if self._client is None:
            try:
                client = AzureDataLakeFsClient.from_azure(
                    config=self._build_config(),
                    service_bus_settings=self._build_service_bus_settings(),
                )
            except Exception as e:
                log.error(f"Failed to create Azure Data Lake client: {e}")
                raise
            client.ensure_file_system()
            self._client = client
        return self._client

    def _build_config(self):
        """Build the azure-data-lake-fs config for the configured auth mode."""
        if self.use_emulator:
            log.info("Using Azure Storage Emulator")
            return AzureDataLakeFsConfig.from_connection_string(
                EMULATOR_CONNECTION_STRING,
                self.file_system_name,
                sas_policy=SAS_POLICY,
            )
        if self.connection_string:
            return AzureDataLakeFsConfig.from_connection_string(
                self.connection_string,
                self.file_system_name,
                sas_policy=SAS_POLICY,
            )
        if self.account_name and self.account_key:
            return AzureDataLakeFsConfig(
                account_name=self.account_name,
                file_system_name=self.file_system_name,
                account_key=self.account_key,
                sas_policy=SAS_POLICY,
            )
        if self.account_name:
            return AzureDataLakeFsConfig(
                account_name=self.account_name,
                file_system_name=self.file_system_name,
                credential=DefaultAzureCredential(),
                sas_policy=SAS_POLICY,
            )
        raise ValueError(
            "Azure Storage configuration is incomplete. Please provide either "
            "connection_string, account_name with account_key, or account_name "
            "for managed identity."
        )

    def _build_service_bus_settings(self):
        if not (self.servicebus_connection_string and self.servicebus_queue_name):
            return None
        return ServiceBusSettings(
            connection_string=self.servicebus_connection_string,
            queue_name=self.servicebus_queue_name,
        )

    def is_emulator_mode(self):
        """Check if running in emulator mode"""
        return self.use_emulator

    def test_connection(self):
        """Test Azure Storage connection"""
        try:
            self.client.ensure_file_system()
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

            if hasattr(self.upload_field_storage, "file"):
                content = self.upload_field_storage.file.read()
                self.upload_field_storage.file.seek(0)
            else:
                content = self.upload_field_storage.read()

            content_type = (
                mimetypes.guess_type(self.filename)[0] or "application/octet-stream"
            )

            self.client.upload(
                file_path,
                content,
                overwrite=True,
                metadata={
                    "original_filename": self.filename,
                    "upload_time": datetime.now(timezone.utc).isoformat(),
                    "ckan_resource": "true",
                },
                content_type=content_type,
            )

            self.filename = file_path
            self.url = self._get_blob_url(file_path)

            log.info(f"File uploaded successfully: {file_path}")

            self._send_file_event("upload", file_path)

        except Exception as e:
            log.error(f"Failed to upload file to Azure Data Lake: {e}")
            raise

    def _generate_blob_name(self):
        """Generate unique blob name with path"""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        safe_filename = self.filename.replace(" ", "_").replace("/", "_")

        if self.upload_to:
            return f"{self.upload_to}/{timestamp}_{safe_filename}"
        else:
            return f"{timestamp}_{safe_filename}"

    def _get_blob_url(self, file_path):
        """Get URL for a file path with SAS token when possible."""
        file_path = file_path.lstrip("/")
        if not file_path or file_path.endswith("/"):
            raise ValueError("Invalid file path for SAS URL generation")
        try:
            return self.client.open_download_context(file_path).sas_url
        except Exception as e:
            log.error(f"Failed to generate file URL: {e}")
            return self.client.url_for(file_path)

    def _send_file_event(self, event_type, file_path):
        """Send file event to Service Bus queue, fallback to Event Hub."""
        event_data = {
            "event_type": event_type,
            "file_path": file_path,
            "blob_name": file_path,  # Legacy key kept for compatibility.
            "container_name": self.file_system_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "ckan_native_cloud_storage",
        }

        if self.servicebus_connection_string:
            self._send_servicebus_event(event_data)
            return

        if self.eventhub_connection_string or self.use_emulator:
            self._send_eventhub_event(event_data)

    def _send_servicebus_event(self, event_data):
        """Send file event to Azure Service Bus queue."""
        try:
            self.client.publish_change(event_data)
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
                conn_str=connection_string, eventhub_name=self.eventhub_name
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
        results = {"processed": 0, "migrated": 0, "errors": 0, "files": []}

        # Get CKAN storage path
        storage_path = config.get("ckan.storage_path", "/var/lib/ckan/default")
        resources_path = os.path.join(storage_path, "resources")

        if not os.path.exists(resources_path):
            log.warning(f"Resources directory not found: {resources_path}")
            return results

        try:
            for root, dirs, files in os.walk(resources_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, resources_path)

                    results["processed"] += 1

                    try:
                        if not dry_run:
                            # Upload file to Azure
                            with open(file_path, "rb") as f:
                                blob_name = f"migrated/{rel_path}"
                                if self.client.exists(blob_name):
                                    log.info(
                                        f"Blob already exists, skipping: {blob_name}"
                                    )
                                    continue

                                self.client.upload(
                                    blob_name,
                                    f,
                                    overwrite=False,
                                    metadata={
                                        "original_path": rel_path,
                                        "migration_time": datetime.now(
                                            timezone.utc
                                        ).isoformat(),
                                        "migrated_from": "local_storage",
                                    },
                                )

                                results["migrated"] += 1
                                log.info(f"Migrated file: {rel_path} -> {blob_name}")

                        results["files"].append(
                            {
                                "local_path": rel_path,
                                "blob_name": (
                                    f"migrated/{rel_path}" if not dry_run else None
                                ),
                                "size": os.path.getsize(file_path),
                                "status": (
                                    "migrated" if not dry_run else "ready_for_migration"
                                ),
                            }
                        )

                    except Exception as e:
                        results["errors"] += 1
                        log.error(f"Failed to migrate file {rel_path}: {e}")
                        results["files"].append(
                            {"local_path": rel_path, "error": str(e), "status": "error"}
                        )

        except Exception as e:
            log.error(f"Migration process failed: {e}")
            raise

        return results
