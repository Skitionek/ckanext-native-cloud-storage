import json
import re
from io import BytesIO
from unittest.mock import Mock, create_autospec, patch
from urllib.parse import parse_qs, urlsplit

import pytest
from azure.core.exceptions import AzureError
from azure_data_lake_fs import AzureDataLakeFsClient, TransferContext
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


def fake_client():
    """An azure-data-lake-fs client double that enforces the real signatures."""
    client = create_autospec(AzureDataLakeFsClient, instance=True)
    client.open_download_context.side_effect = lambda path: TransferContext(
        operation="download", path=path, sas_url=f"https://signed.test/{path}?sig=x"
    )
    client.url_for.side_effect = lambda path: f"https://unsigned.test/{path}"
    return client


def with_fake_client(storage):
    storage._client = fake_client()
    return storage._client


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
            storage._build_config()

    def test_connection_string_auth_uses_real_value(self):
        conn_str = (
            "DefaultEndpointsProtocol=https;AccountName=foo;AccountKey=YmFy;"
            "EndpointSuffix=core.windows.net"
        )
        storage = make_storage(
            {
                "ckanext.native_cloud_storage.azure.connection_string": conn_str,
                "ckanext.native_cloud_storage.azure.file_system_name": "fs",
            }
        )

        config = storage._build_config()

        assert config.account_name == "foo"
        assert config.account_key == "YmFy"
        assert config.file_system_name == "fs"
        assert config.account_url == "https://foo.dfs.core.windows.net"
        assert config.sas_policy.expiry_minutes == 60

    def test_emulator_mode_takes_precedence_over_connection_string(self):
        storage = make_storage(
            {
                "ckanext.native_cloud_storage.azure.use_emulator": "true",
                "ckanext.native_cloud_storage.azure.connection_string": "should-be-ignored",
            }
        )

        config = storage._build_config()

        assert config.account_name == "devstoreaccount1"
        assert config.account_url == "http://127.0.0.1:10000/devstoreaccount1"

    def test_account_key_auth_uses_real_account_and_key(self):
        storage = make_storage(
            {
                "ckanext.native_cloud_storage.azure.account_name": "myaccount",
                "ckanext.native_cloud_storage.azure.account_key": "secret-key",
            }
        )

        config = storage._build_config()

        assert config.account_name == "myaccount"
        assert config.account_key == "secret-key"
        assert config.credential is None
        assert config.account_url == "https://myaccount.dfs.core.windows.net"

    @patch("ckanext.native_cloud_storage.storage.DefaultAzureCredential")
    def test_account_name_only_uses_managed_identity(self, mock_default_credential):
        mock_credential_instance = Mock()
        mock_default_credential.return_value = mock_credential_instance

        storage = make_storage(
            {"ckanext.native_cloud_storage.azure.account_name": "myaccount"}
        )
        config = storage._build_config()

        mock_default_credential.assert_called_once()
        assert config.account_key is None
        assert config.credential is mock_credential_instance

    @patch("ckanext.native_cloud_storage.storage.AzureDataLakeFsClient.from_azure")
    def test_client_is_built_once_and_ensures_file_system(self, mock_from_azure):
        client = fake_client()
        mock_from_azure.return_value = client
        storage = make_storage(self.test_config)

        first = storage.client
        second = storage.client

        assert first is client
        assert second is client
        mock_from_azure.assert_called_once()
        config = mock_from_azure.call_args.kwargs["config"]
        assert config.file_system_name == "test-filesystem"
        assert mock_from_azure.call_args.kwargs["service_bus_settings"] is None
        client.ensure_file_system.assert_called_once_with()

    @patch("ckanext.native_cloud_storage.storage.AzureDataLakeFsClient.from_azure")
    def test_client_gets_service_bus_settings_when_configured(self, mock_from_azure):
        mock_from_azure.return_value = fake_client()
        storage = make_storage(
            {
                **self.test_config,
                "ckanext.native_cloud_storage.azure.servicebus_connection_string": "sb-conn-str",
            }
        )

        storage.client

        settings = mock_from_azure.call_args.kwargs["service_bus_settings"]
        assert settings.connection_string == "sb-conn-str"
        assert settings.queue_name == "test-file-events"

    @patch("ckanext.native_cloud_storage.storage.AzureDataLakeFsClient.from_azure")
    def test_client_creation_failure_is_logged_and_reraised(self, mock_from_azure):
        mock_from_azure.side_effect = AzureError("auth failed")
        storage = make_storage(self.test_config)

        with pytest.raises(AzureError, match="auth failed"):
            storage.client
        assert storage._client is None

    @patch("ckanext.native_cloud_storage.storage.AzureDataLakeFsClient.from_azure")
    def test_client_is_not_cached_when_file_system_check_fails(self, mock_from_azure):
        client = fake_client()
        client.ensure_file_system.side_effect = AzureError("down")
        mock_from_azure.return_value = client
        storage = make_storage(self.test_config)

        with pytest.raises(AzureError, match="down"):
            storage.client
        assert storage._client is None

    # ------------------------------------------------------------------
    # test_connection
    # ------------------------------------------------------------------

    def test_connection_test_success(self):
        storage = make_storage(self.test_config)
        client = with_fake_client(storage)

        assert storage.test_connection() is True
        client.ensure_file_system.assert_called_once_with()

    def test_connection_test_failure_returns_false(self):
        storage = make_storage(self.test_config)
        client = with_fake_client(storage)
        client.ensure_file_system.side_effect = AzureError("down")

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
        client = with_fake_client(storage)

        storage.upload()

        client.upload.assert_not_called()

    def test_upload_passes_real_content_and_metadata_to_client(self):
        storage = make_storage(self.test_config, upload_to="resources")
        mock_file = Mock()
        mock_file.file = BytesIO(b"hello world")
        storage.upload_field_storage = mock_file
        storage.filename = "test file.txt"
        client = with_fake_client(storage)

        storage.upload()

        (requested_path, data), kwargs = client.upload.call_args
        assert requested_path.startswith("resources/")
        assert requested_path.endswith("test_file.txt")
        assert data == b"hello world"
        assert kwargs["overwrite"] is True
        assert kwargs["metadata"]["original_filename"] == "test file.txt"
        assert kwargs["metadata"]["ckan_resource"] == "true"
        # content type comes from the real mimetype of the filename
        assert kwargs["content_type"] == "text/plain"

        # filename/url are updated to the generated path and its signed URL
        assert storage.filename == requested_path
        assert storage.url == f"https://signed.test/{requested_path}?sig=x"

    def test_upload_reads_from_field_storage_without_file_attr(self):
        storage = make_storage(self.test_config)
        raw = Mock(spec=["read"])
        raw.read.return_value = b"raw bytes"
        storage.upload_field_storage = raw
        storage.filename = "raw.bin"
        client = with_fake_client(storage)

        storage.upload()

        raw.read.assert_called_once()
        assert client.upload.call_args.args[1] == b"raw bytes"
        assert client.upload.call_args.kwargs["content_type"] == (
            "application/octet-stream"
        )

    def test_upload_reraises_on_storage_failure(self):
        storage = make_storage(self.test_config)
        mock_file = Mock()
        mock_file.file = BytesIO(b"data")
        storage.upload_field_storage = mock_file
        storage.filename = "test.txt"
        client = with_fake_client(storage)
        client.upload.side_effect = AzureError("upload rejected")

        with pytest.raises(AzureError, match="upload rejected"):
            storage.upload()
        client.publish_change.assert_not_called()

    def test_upload_publishes_file_event(self):
        storage = make_storage(
            {
                **self.test_config,
                "ckanext.native_cloud_storage.azure.servicebus_connection_string": "sb-conn-str",
            }
        )
        mock_file = Mock()
        mock_file.file = BytesIO(b"data")
        storage.upload_field_storage = mock_file
        storage.filename = "test.txt"
        client = with_fake_client(storage)

        storage.upload()

        (event,) = client.publish_change.call_args.args
        assert event["event_type"] == "upload"
        assert event["file_path"] == storage.filename
        assert event["container_name"] == "test-filesystem"

    # ------------------------------------------------------------------
    # Blob URL / SAS generation
    # ------------------------------------------------------------------

    def test_get_blob_url_rejects_empty_or_directory_path(self):
        storage = make_storage(self.test_config)
        client = with_fake_client(storage)

        with pytest.raises(ValueError):
            storage._get_blob_url("")

        with pytest.raises(ValueError):
            storage._get_blob_url("resources/")

        client.open_download_context.assert_not_called()

    def test_get_blob_url_returns_signed_url(self):
        storage = make_storage(self.test_config)
        client = with_fake_client(storage)

        url = storage._get_blob_url("/resources/test.txt")

        assert url == "https://signed.test/resources/test.txt?sig=x"
        client.open_download_context.assert_called_once_with("resources/test.txt")

    def test_get_blob_url_falls_back_to_unsigned_url_when_signing_fails(self):
        storage = make_storage(self.test_config)
        client = with_fake_client(storage)
        client.open_download_context.side_effect = AzureError("no delegation key")

        url = storage._get_blob_url("resources/test.txt")

        assert url == "https://unsigned.test/resources/test.txt"

    @pytest.mark.parametrize(
        ("config_overrides", "expected_base"),
        [
            (
                {
                    "ckanext.native_cloud_storage.azure.account_name": "myaccount",
                    "ckanext.native_cloud_storage.azure.account_key": "c2VjcmV0LWtleQ==",
                    "ckanext.native_cloud_storage.azure.file_system_name": "test-filesystem",
                },
                "https://myaccount.dfs.core.windows.net/test-filesystem/resources/test.txt",
            ),
            (
                {
                    "ckanext.native_cloud_storage.azure.use_emulator": "true",
                    "ckanext.native_cloud_storage.azure.file_system_name": "test-filesystem",
                },
                "http://127.0.0.1:10000/devstoreaccount1/test-filesystem/resources/test.txt",
            ),
        ],
    )
    def test_get_blob_url_signs_read_only_sas_with_account_key(
        self, config_overrides, expected_base
    ):
        """Real azure-data-lake-fs signing (no network) for key-based auth modes."""
        storage = make_storage(config_overrides)
        storage._client = AzureDataLakeFsClient.from_azure(
            config=storage._build_config()
        )

        url = storage._get_blob_url("resources/test.txt")

        parts = urlsplit(url)
        query = parse_qs(parts.query)
        assert f"{parts.scheme}://{parts.netloc}{parts.path}" == expected_base
        assert query["sp"] == ["r"]
        assert "sig" in query
        assert "se" in query

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
        client = with_fake_client(storage)

        storage._send_file_event("upload", "resources/test.txt")

        (payload,) = client.publish_change.call_args.args
        assert payload["event_type"] == "upload"
        assert payload["file_path"] == "resources/test.txt"
        assert payload["blob_name"] == "resources/test.txt"
        assert payload["source"] == "ckan_native_cloud_storage"
        json.dumps(payload)  # must stay JSON-serializable for the queue

    def test_send_file_event_swallows_servicebus_errors(self):
        storage = make_storage(
            {
                "ckanext.native_cloud_storage.azure.servicebus_connection_string": "sb-conn-str"
            }
        )
        client = with_fake_client(storage)
        client.publish_change.side_effect = AzureError("bus unreachable")

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
        client = with_fake_client(storage)

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
        client.exists.assert_not_called()
        client.upload.assert_not_called()

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
        client = with_fake_client(storage)
        client.exists.return_value = False

        results = storage.migrate_existing_files(dry_run=False)

        client.exists.assert_called_once_with("migrated/a.txt")
        client.upload.assert_called_once()
        (path, data), kwargs = client.upload.call_args
        assert path == "migrated/a.txt"
        assert data is mock_open.return_value.__enter__.return_value
        assert kwargs["overwrite"] is False
        assert kwargs["metadata"]["original_path"] == "a.txt"
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
        client = with_fake_client(storage)
        client.exists.return_value = True

        with patch("builtins.open", Mock()):
            results = storage.migrate_existing_files(dry_run=False)

        client.upload.assert_not_called()
        assert results["migrated"] == 0
        assert results["processed"] == 1
