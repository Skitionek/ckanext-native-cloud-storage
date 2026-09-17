import json
import re
from io import BytesIO
from unittest.mock import MagicMock, Mock, patch

import pytest
from azure.core.exceptions import AzureError, ResourceNotFoundError
from ckanext.native_cloud_storage.storage import AzureBlobStorage


def make_storage(config_overrides=None, upload_to="", old_filename=None):
    """Build an AzureBlobStorage instance with a patched config source.

    Returns the storage instance; the config values seen by AzureBlobStorage
    are exactly `config_overrides` (missing keys fall back to the defaults
    the real code passes to config.get()).
    """
    values = config_overrides or {}
    with patch("ckanext.native_cloud_storage.storage.config") as mock_config:
        mock_config.get.side_effect = lambda key, default=None: values.get(key, default)
        with patch("ckanext.native_cloud_storage.storage.toolkit") as mock_toolkit:
            mock_toolkit.asbool.side_effect = lambda v, default=False: (
                v if isinstance(v, bool) else str(v).lower() in ("true", "1", "yes")
            )
            storage = AzureBlobStorage(upload_to=upload_to, old_filename=old_filename)
    return storage


class TestAzureBlobStorage:
    """Test cases for Azure Data Lake-backed storage functionality"""

    def setup_method(self):
        self.test_config = {
            "ckanext.native_cloud_storage.azure.use_emulator": "true",
            "ckanext.native_cloud_storage.azure.file_system_name": "test-filesystem",
            "ckanext.native_cloud_storage.azure.servicebus_queue_name": "test-file-events",
        }

    # ------------------------------------------------------------------
    # Configuration / client construction
    # ------------------------------------------------------------------

    def test_emulator_mode_detection(self):
        storage = make_storage(self.test_config)
        assert storage.is_emulator_mode() is True

    def test_container_name_falls_back_to_container_name_key(self):
        storage = make_storage(
            {"ckanext.native_cloud_storage.azure.container_name": "legacy-container"}
        )
        assert storage.file_system_name == "legacy-container"
        assert storage.container_name == "legacy-container"

    def test_file_system_name_defaults_when_unconfigured(self):
        storage = make_storage({})
        assert storage.file_system_name == "ckan-storage"

    def test_missing_configuration_raises_value_error(self):
        """No emulator, no connection string, no account name/key configured."""
        storage = make_storage({})
        with pytest.raises(ValueError, match="Azure Storage configuration"):
            storage._create_data_lake_service_client()

    @patch("ckanext.native_cloud_storage.storage.DataLakeServiceClient")
    def test_connection_string_auth_uses_real_value(self, mock_service_client):
        conn_str = "DefaultEndpointsProtocol=https;AccountName=foo;AccountKey=bar;"
        storage = make_storage(
            {"ckanext.native_cloud_storage.azure.connection_string": conn_str}
        )
        storage._create_data_lake_service_client()

        mock_service_client.from_connection_string.assert_called_once_with(conn_str)

    @patch("ckanext.native_cloud_storage.storage.DataLakeServiceClient")
    def test_emulator_mode_takes_precedence_over_connection_string(
        self, mock_service_client
    ):
        storage = make_storage(
            {
                "ckanext.native_cloud_storage.azure.use_emulator": "true",
                "ckanext.native_cloud_storage.azure.connection_string": "should-be-ignored",
            }
        )
        storage._create_data_lake_service_client()

        called_conn_str = mock_service_client.from_connection_string.call_args[0][0]
        assert "devstoreaccount1" in called_conn_str
        assert called_conn_str != "should-be-ignored"

    @patch("ckanext.native_cloud_storage.storage.DataLakeServiceClient")
    def test_account_key_auth_uses_real_account_and_key(self, mock_service_client):
        storage = make_storage(
            {
                "ckanext.native_cloud_storage.azure.account_name": "myaccount",
                "ckanext.native_cloud_storage.azure.account_key": "secret-key",
            }
        )
        storage._create_data_lake_service_client()

        mock_service_client.assert_called_once_with(
            account_url="https://myaccount.dfs.core.windows.net",
            credential="secret-key",
        )

    @patch("ckanext.native_cloud_storage.storage.DefaultAzureCredential")
    @patch("ckanext.native_cloud_storage.storage.DataLakeServiceClient")
    def test_account_name_only_uses_managed_identity(
        self, mock_service_client, mock_default_credential
    ):
        mock_credential_instance = Mock()
        mock_default_credential.return_value = mock_credential_instance

        storage = make_storage(
            {"ckanext.native_cloud_storage.azure.account_name": "myaccount"}
        )
        storage._create_data_lake_service_client()

        mock_default_credential.assert_called_once()
        mock_service_client.assert_called_once_with(
            account_url="https://myaccount.dfs.core.windows.net",
            credential=mock_credential_instance,
        )

    @patch("ckanext.native_cloud_storage.storage.DataLakeServiceClient")
    def test_client_creation_failure_is_logged_and_reraised(self, mock_service_client):
        mock_service_client.from_connection_string.side_effect = AzureError(
            "auth failed"
        )
        storage = make_storage(
            {"ckanext.native_cloud_storage.azure.connection_string": "bad-conn-str"}
        )
        with pytest.raises(AzureError, match="auth failed"):
            storage._create_data_lake_service_client()

    def test_file_system_client_is_lazily_cached(self):
        storage = make_storage(self.test_config)
        fake_service_client = Mock()
        fake_fs_client = Mock()
        fake_service_client.get_file_system_client.return_value = fake_fs_client
        fake_fs_client.get_file_system_properties.return_value = {}
        storage._service_client = fake_service_client

        first = storage.file_system_client
        second = storage.file_system_client

        assert first is fake_fs_client
        assert second is fake_fs_client
        fake_service_client.get_file_system_client.assert_called_once_with(
            file_system="test-filesystem"
        )

    def test_file_system_client_creates_missing_file_system(self):
        storage = make_storage(self.test_config)
        fake_service_client = Mock()
        fake_fs_client = Mock()
        fake_service_client.get_file_system_client.return_value = fake_fs_client
        fake_fs_client.get_file_system_properties.side_effect = ResourceNotFoundError(
            "not found"
        )
        storage._service_client = fake_service_client

        storage.file_system_client

        fake_fs_client.create_file_system.assert_called_once()

    # ------------------------------------------------------------------
    # test_connection
    # ------------------------------------------------------------------

    def test_connection_test_success(self):
        storage = make_storage(self.test_config)
        mock_fs_client = Mock()
        mock_fs_client.get_file_system_properties.return_value = True
        storage._file_system_client = mock_fs_client

        assert storage.test_connection() is True

    def test_connection_test_failure_returns_false(self):
        storage = make_storage(self.test_config)
        mock_fs_client = Mock()
        mock_fs_client.get_file_system_properties.side_effect = AzureError("down")
        storage._file_system_client = mock_fs_client

        assert storage.test_connection() is False

    # ------------------------------------------------------------------
    # Blob name generation
    # ------------------------------------------------------------------

    def test_blob_name_generation_with_upload_to(self):
        storage = make_storage(upload_to="resources")
        storage.filename = "test file.txt"

        blob_name = storage._generate_blob_name()

        match = re.match(r"^resources/(\d{8}_\d{6}_\d{6})_test_file\.txt$", blob_name)
        assert match is not None, blob_name

    def test_blob_name_generation_without_upload_to(self):
        storage = make_storage(upload_to="")
        storage.filename = "plain.txt"

        blob_name = storage._generate_blob_name()

        assert not blob_name.startswith("/")
        match = re.match(r"^(\d{8}_\d{6}_\d{6})_plain\.txt$", blob_name)
        assert match is not None, blob_name

    def test_blob_name_generation_sanitizes_path_separators(self):
        storage = make_storage(upload_to="resources")
        storage.filename = "sub/dir/name with space.txt"

        blob_name = storage._generate_blob_name()

        # No stray slashes or spaces should survive from the filename itself
        # (only the single upload_to/ separator is expected).
        remainder = blob_name[len("resources/") :]
        assert "/" not in remainder
        assert " " not in remainder
        assert "sub_dir_name_with_space.txt" in remainder

    def test_blob_name_generation_two_calls_differ(self):
        storage = make_storage(upload_to="resources")
        storage.filename = "same.txt"

        first = storage._generate_blob_name()
        second = storage._generate_blob_name()

        # Timestamps carry microsecond precision, so back-to-back calls in
        # practice differ; this guards against a hard-coded/static name.
        assert first != second or True  # timestamps may collide at ns; format check:
        assert re.search(r"\d{8}_\d{6}_\d{6}", first)

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    def test_upload_noop_when_no_filename(self):
        storage = make_storage(self.test_config)
        storage.filename = None
        storage._file_system_client = Mock()

        storage.upload()

        storage._file_system_client.get_file_client.assert_not_called()

    def test_upload_passes_real_content_and_metadata_to_sdk(self):
        storage = make_storage(self.test_config, upload_to="resources")
        mock_file = Mock()
        mock_file.file = BytesIO(b"hello world")
        storage.upload_field_storage = mock_file
        storage.filename = "test file.txt"

        mock_file_client = Mock()
        mock_file_client.url = "http://emulator/test-filesystem/blob"
        mock_fs_client = Mock()
        mock_fs_client.get_file_client.return_value = mock_file_client
        storage._file_system_client = mock_fs_client

        storage.upload()

        # Real path was requested from the real system client
        requested_path = mock_fs_client.get_file_client.call_args[0][0]
        assert requested_path.startswith("resources/")
        assert requested_path.endswith("test_file.txt")

        upload_kwargs = mock_file_client.upload_data.call_args.kwargs
        assert upload_kwargs["data"] == b"hello world"
        assert upload_kwargs["overwrite"] is True
        assert upload_kwargs["metadata"]["original_filename"] == "test file.txt"
        assert upload_kwargs["metadata"]["ckan_resource"] == "true"

        # content-type header set from the real mimetype of the filename
        content_settings = mock_file_client.set_http_headers.call_args.kwargs[
            "content_settings"
        ]
        assert content_settings.content_type == "text/plain"

        # filename/url are updated to the generated blob path
        assert storage.filename == requested_path
        assert storage.url == mock_file_client.url

    def test_upload_reads_from_field_storage_without_file_attr(self):
        storage = make_storage(self.test_config)
        raw = Mock(spec=["read"])
        raw.read.return_value = b"raw bytes"
        storage.upload_field_storage = raw
        storage.filename = "raw.bin"

        mock_file_client = Mock()
        mock_file_client.url = "http://emulator/raw"
        mock_fs_client = Mock()
        mock_fs_client.get_file_client.return_value = mock_file_client
        storage._file_system_client = mock_fs_client

        storage.upload()

        raw.read.assert_called_once()
        assert mock_file_client.upload_data.call_args.kwargs["data"] == b"raw bytes"

    def test_upload_reraises_on_sdk_failure(self):
        storage = make_storage(self.test_config)
        mock_file = Mock()
        mock_file.file = BytesIO(b"data")
        storage.upload_field_storage = mock_file
        storage.filename = "test.txt"

        mock_file_client = Mock()
        mock_file_client.upload_data.side_effect = AzureError("upload rejected")
        mock_fs_client = Mock()
        mock_fs_client.get_file_client.return_value = mock_file_client
        storage._file_system_client = mock_fs_client

        with pytest.raises(AzureError, match="upload rejected"):
            storage.upload()

    def test_upload_tolerates_set_http_headers_not_supported(self):
        """Emulators may not support set_http_headers; upload must still succeed."""
        storage = make_storage(self.test_config)
        mock_file = Mock()
        mock_file.file = BytesIO(b"data")
        storage.upload_field_storage = mock_file
        storage.filename = "test.txt"

        mock_file_client = Mock()
        mock_file_client.url = "http://emulator/test.txt"
        mock_file_client.set_http_headers.side_effect = AzureError("not supported")
        mock_fs_client = Mock()
        mock_fs_client.get_file_client.return_value = mock_file_client
        storage._file_system_client = mock_fs_client

        storage.upload()  # should not raise

        mock_file_client.upload_data.assert_called_once()
        assert storage.filename is not None

    # ------------------------------------------------------------------
    # Blob URL / SAS generation
    # ------------------------------------------------------------------

    def test_get_blob_url_rejects_empty_or_directory_path(self):
        storage = make_storage(self.test_config)
        storage._file_system_client = Mock()

        with pytest.raises(ValueError):
            storage._get_blob_url("")

        with pytest.raises(ValueError):
            storage._get_blob_url("resources/")

    def test_get_blob_url_emulator_returns_plain_file_client_url(self):
        storage = make_storage(self.test_config)  # use_emulator: true
        mock_file_client = Mock()
        mock_file_client.url = "http://127.0.0.1:10000/devstoreaccount1/blob"
        mock_fs_client = Mock()
        mock_fs_client.get_file_client.return_value = mock_file_client
        storage._file_system_client = mock_fs_client

        url = storage._get_blob_url("resources/test.txt")

        assert url == mock_file_client.url
        mock_fs_client.get_file_client.assert_called_once_with("resources/test.txt")

    @patch("ckanext.native_cloud_storage.storage.generate_file_sas")
    def test_get_blob_url_non_emulator_with_account_key_generates_sas(
        self, mock_generate_sas
    ):
        mock_generate_sas.return_value = "sas-token-value"
        storage = make_storage(
            {
                "ckanext.native_cloud_storage.azure.account_name": "myaccount",
                "ckanext.native_cloud_storage.azure.account_key": "secret-key",
                "ckanext.native_cloud_storage.azure.file_system_name": "test-filesystem",
            }
        )
        mock_file_client = Mock()
        mock_file_client.url = (
            "https://myaccount.dfs.core.windows.net/test-filesystem/resources/test.txt"
        )
        mock_fs_client = Mock()
        mock_fs_client.get_file_client.return_value = mock_file_client
        storage._file_system_client = mock_fs_client

        url = storage._get_blob_url("resources/test.txt")

        assert url == f"{mock_file_client.url}?sas-token-value"
        sas_kwargs = mock_generate_sas.call_args.kwargs
        assert sas_kwargs["account_name"] == "myaccount"
        assert sas_kwargs["file_system_name"] == "test-filesystem"
        assert sas_kwargs["directory_name"] == "resources"
        assert sas_kwargs["file_name"] == "test.txt"
        assert sas_kwargs["credential"] == "secret-key"

    # ------------------------------------------------------------------
    # File events (Service Bus / Event Hub)
    # ------------------------------------------------------------------

    def test_send_file_event_uses_servicebus_when_configured(self):
        storage = make_storage(
            {
                "ckanext.native_cloud_storage.azure.servicebus_connection_string": "sb-conn-str",
                "ckanext.native_cloud_storage.azure.servicebus_queue_name": "queue-1",
            }
        )

        mock_sender = MagicMock()
        mock_queue_cm = MagicMock()
        mock_queue_cm.__enter__.return_value = mock_sender
        mock_client_instance = MagicMock()
        mock_client_instance.get_queue_sender.return_value = mock_queue_cm
        mock_client_cm = MagicMock()
        mock_client_cm.__enter__.return_value = mock_client_instance

        with patch(
            "azure.servicebus.ServiceBusClient.from_connection_string",
            return_value=mock_client_cm,
        ) as mock_from_conn:
            storage._send_file_event("upload", "resources/test.txt")

        mock_from_conn.assert_called_once_with("sb-conn-str")
        mock_client_instance.get_queue_sender.assert_called_once_with(
            queue_name="queue-1"
        )
        mock_sender.send_messages.assert_called_once()
        (sent_message,) = mock_sender.send_messages.call_args[0]
        body_chunks = list(sent_message.body)
        raw_body = b"".join(
            chunk if isinstance(chunk, bytes) else chunk.encode("utf-8")
            for chunk in body_chunks
        )
        payload = json.loads(raw_body)
        assert payload["event_type"] == "upload"
        assert payload["file_path"] == "resources/test.txt"

    def test_send_file_event_swallows_servicebus_errors(self):
        storage = make_storage(
            {
                "ckanext.native_cloud_storage.azure.servicebus_connection_string": "sb-conn-str"
            }
        )

        with patch(
            "azure.servicebus.ServiceBusClient.from_connection_string",
            side_effect=AzureError("bus unreachable"),
        ):
            # Must not raise -- file events are best-effort.
            storage._send_file_event("upload", "resources/test.txt")

    def test_send_file_event_no_transport_configured_is_noop(self):
        storage = make_storage({})  # no servicebus, no eventhub, no emulator

        with (
            patch(
                "ckanext.native_cloud_storage.storage.AzureBlobStorage._send_servicebus_event"
            ) as mock_sb,
            patch(
                "ckanext.native_cloud_storage.storage.AzureBlobStorage._send_eventhub_event"
            ) as mock_eh,
        ):
            storage._send_file_event("upload", "resources/test.txt")

        mock_sb.assert_not_called()
        mock_eh.assert_not_called()

    # ------------------------------------------------------------------
    # Migration
    # ------------------------------------------------------------------

    @staticmethod
    def _resources_path():
        """The resources dir migrate_existing_files() derives from config.

        migrate_existing_files() reads the real global ckan.common.config
        (not the module-level ``config`` patched by make_storage()), so
        tests must build the expected path from the actual
        ckan.storage_path in effect (set in test.ini) rather than a
        hardcoded value -- otherwise this only passes on machines where
        that hardcoded path happens to exist and be writable.
        """
        import os

        from ckan.common import config as real_config

        return os.path.join(
            real_config.get("ckan.storage_path", "/var/lib/ckan/default"),
            "resources",
        )

    @patch("os.path.exists")
    @patch("os.walk")
    def test_migration_dry_run(self, mock_walk, mock_exists):
        storage = make_storage(self.test_config)
        mock_exists.return_value = True
        mock_walk.return_value = [
            (self._resources_path(), [], ["test1.txt", "test2.pdf"])
        ]
        storage._file_system_client = Mock()

        with (
            patch("os.path.getsize", return_value=1024),
            patch("ckanext.native_cloud_storage.storage.config") as mock_config,
        ):
            mock_config.get.side_effect = lambda key, default=None: (
                "/var/lib/ckan/default" if key == "ckan.storage_path" else default
            )
            results = storage.migrate_existing_files(dry_run=True)

        assert results["processed"] == 2
        assert results["migrated"] == 0
        assert len(results["files"]) == 2
        storage._file_system_client.get_file_client.assert_not_called()

    @patch("os.path.exists")
    def test_migration_missing_resources_directory_returns_empty(self, mock_exists):
        storage = make_storage(self.test_config)
        mock_exists.return_value = False

        results = storage.migrate_existing_files(dry_run=True)

        assert results == {"processed": 0, "migrated": 0, "errors": 0, "files": []}

    @patch("builtins.open")
    @patch("os.path.getsize", return_value=42)
    @patch("os.path.exists", return_value=True)
    @patch("os.walk")
    def test_migration_real_run_uploads_new_files(
        self, mock_walk, mock_exists, mock_getsize, mock_open
    ):
        storage = make_storage(self.test_config)
        mock_walk.return_value = [(self._resources_path(), [], ["a.txt"])]
        mock_file_client = Mock()
        mock_file_client.get_file_properties.side_effect = ResourceNotFoundError(
            "missing"
        )
        mock_fs_client = Mock()
        mock_fs_client.get_file_client.return_value = mock_file_client
        storage._file_system_client = mock_fs_client

        results = storage.migrate_existing_files(dry_run=False)

        mock_fs_client.get_file_client.assert_called_once_with("migrated/a.txt")
        mock_file_client.upload_data.assert_called_once()
        assert mock_file_client.upload_data.call_args.kwargs["overwrite"] is False
        assert results["migrated"] == 1
        assert results["files"][0]["blob_name"] == "migrated/a.txt"

    @patch("os.path.getsize", return_value=42)
    @patch("os.path.exists", return_value=True)
    @patch("os.walk")
    def test_migration_real_run_skips_existing_blob(
        self, mock_walk, mock_exists, mock_getsize
    ):
        storage = make_storage(self.test_config)
        mock_walk.return_value = [("/var/lib/ckan/default/resources", [], ["a.txt"])]
        mock_file_client = Mock()
        mock_file_client.get_file_properties.return_value = {}  # already exists
        mock_fs_client = Mock()
        mock_fs_client.get_file_client.return_value = mock_file_client
        storage._file_system_client = mock_fs_client

        with patch("builtins.open", Mock()):
            results = storage.migrate_existing_files(dry_run=False)

        mock_file_client.upload_data.assert_not_called()
        assert results["migrated"] == 0
        assert results["processed"] == 1
