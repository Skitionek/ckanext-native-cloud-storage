"""
Integration tests for ckanext-native-cloud-storage.

Unlike test_basic.py / test_storage.py (pure-mock unit tests), these tests
boot a real CKAN application (real DB via SQLAlchemy, real plugin loader,
real action/CLI dispatch) using CKAN's own pytest fixtures
(``ckan.tests.pytest_ckan``). Only the Azure SDK boundary itself is mocked
(no real Azure/Storage-emulator is required) -- everything else (plugin
registration, ``toolkit.get_action`` dispatch, ``check_access``, the click
CLI group) runs for real against CKAN.

Requirements to run these tests:

* A CKAN installation with a *complete* set of runtime dependencies
  (importantly: ``flask`` and friends -- a bare ``pip install ckan``
  metapackage is not enough, install CKAN's own ``requirements.txt``, e.g.
  via `pip install -r <path-to-ckan-checkout>/requirements.txt`, or use a
  ckan docker image), plus dev/test deps
  (``pytest-factoryboy``, ``inflection`` -- a transitive dependency of
  ``pytest-factoryboy`` that is not always pulled in automatically and is
  the historical cause of `ModuleNotFoundError: No module named
  'inflection'` when running CKAN's pytest plugin).
* Real Postgres, Solr and Redis instances reachable from the test config
  file (``test.ini`` at the repo root). For local/dev use you can start
  throwaway containers -- see the comment header of ``test.ini`` for the
  exact commands.
* CKAN's own pytest plugin active (``PYTEST_DISABLE_PLUGIN_AUTOLOAD`` must
  NOT be set) since these tests rely on the ``app``, ``with_plugins`` and
  ``ckan_config`` fixtures that CKAN registers via its ``pytest11`` entry
  points.

Run with, e.g.:

    CKAN_INI=test.ini pytest -m integration \
        ckanext/native_cloud_storage/tests/test_integration.py

(A follow-up task, t_622bac48, will wire a fully pinned/documented
single command for CI; keep this docstring as the interim how-to.)

If the environment above is not available, these tests are still valid,
correct CKAN-fixture-based tests -- they will simply fail to collect/run
(pytest will error acquiring the ``app``/``with_plugins`` fixtures) rather
than silently no-op.
"""

from unittest.mock import Mock, patch

import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit
import ckan.tests.helpers as helpers
import pytest
from ckan.tests import factories
from ckanext.native_cloud_storage.commands import native_cloud_storage

pytestmark = pytest.mark.integration


@pytest.mark.ckan_config("ckan.plugins", "native_cloud_storage")
@pytest.mark.usefixtures("with_plugins", "clean_db")
class TestPluginRegistration:
    """The plugin registers correctly with CKAN's plugin loader."""

    def test_plugin_is_loaded(self):
        assert plugins.plugin_loaded("native_cloud_storage")

    def test_plugin_registers_actions(self):
        # get_action raises if the action isn't registered.
        assert toolkit.get_action("storage_status")
        assert toolkit.get_action("storage_migrate")

    def test_plugin_registers_uploader(self):
        from ckanext.native_cloud_storage.storage import AzureBlobStorage

        plugin = plugins.get_plugin("native_cloud_storage")
        uploader = plugin.get_resource_uploader({})
        assert isinstance(uploader, AzureBlobStorage)

        general_uploader = plugin.get_uploader("resources", None)
        assert isinstance(general_uploader, AzureBlobStorage)

    def test_plugin_registers_cli_commands(self):
        plugin = plugins.get_plugin("native_cloud_storage")
        commands = plugin.get_commands()
        names = {c.name for c in commands}
        assert "native-cloud-storage" in names


@pytest.mark.ckan_config("ckan.plugins", "native_cloud_storage")
@pytest.mark.usefixtures("with_plugins", "clean_db")
class TestStorageStatusAction:
    """storage_status action, dispatched through the real CKAN action layer."""

    def test_requires_sysadmin(self):
        user = factories.User()
        context = {"user": user["name"], "ignore_auth": False}

        with pytest.raises(toolkit.NotAuthorized):
            helpers.call_action("storage_status", context=context)

    @patch("ckanext.native_cloud_storage.plugin.AzureBlobStorage")
    def test_success_path(self, mock_storage_cls):
        mock_storage = Mock()
        mock_storage.test_connection.return_value = True
        mock_storage.is_emulator_mode.return_value = True
        mock_storage.container_name = "test-filesystem"
        mock_storage_cls.return_value = mock_storage

        sysadmin = factories.Sysadmin()
        result = helpers.call_action(
            "storage_status", context={"user": sysadmin["name"], "ignore_auth": False}
        )

        assert result["success"] is True
        assert result["status"] == "connected"
        assert result["storage_type"] == "azure_data_lake_gen2"
        assert result["container_name"] == "test-filesystem"

    def test_error_path(self):
        sysadmin = factories.Sysadmin()

        with patch(
            "ckanext.native_cloud_storage.plugin.AzureBlobStorage"
        ) as mock_storage_cls:
            mock_storage_cls.side_effect = RuntimeError("boom: cannot reach azure")

            result = helpers.call_action(
                "storage_status",
                context={"user": sysadmin["name"], "ignore_auth": False},
            )

        assert result["success"] is False
        assert result["status"] == "error"
        assert "boom" in result["error"]


@pytest.mark.ckan_config("ckan.plugins", "native_cloud_storage")
@pytest.mark.usefixtures("with_plugins", "clean_db")
class TestStorageMigrateAction:
    """storage_migrate action, dispatched through the real CKAN action layer."""

    def test_requires_sysadmin(self):
        user = factories.User()
        context = {"user": user["name"], "ignore_auth": False}

        with pytest.raises(toolkit.NotAuthorized):
            helpers.call_action("storage_migrate", context=context)

    @patch("ckanext.native_cloud_storage.plugin.AzureBlobStorage")
    def test_success_path_dry_run(self, mock_storage_cls):
        mock_storage = Mock()
        mock_storage.migrate_existing_files.return_value = {
            "processed": 2,
            "migrated": 0,
            "errors": 0,
            "files": [
                {"status": "would_migrate", "local_path": "/a.txt"},
                {"status": "would_migrate", "local_path": "/b.txt"},
            ],
        }
        mock_storage_cls.return_value = mock_storage

        sysadmin = factories.Sysadmin()
        result = helpers.call_action(
            "storage_migrate",
            context={"user": sysadmin["name"], "ignore_auth": False},
            dry_run=True,
        )

        assert result["success"] is True
        assert result["dry_run"] is True
        assert result["results"]["processed"] == 2
        mock_storage.migrate_existing_files.assert_called_once_with(dry_run=True)

    @patch("ckanext.native_cloud_storage.plugin.AzureBlobStorage")
    def test_error_path(self, mock_storage_cls):
        mock_storage = Mock()
        mock_storage.migrate_existing_files.side_effect = RuntimeError(
            "boom: migration failed"
        )
        mock_storage_cls.return_value = mock_storage

        sysadmin = factories.Sysadmin()
        result = helpers.call_action(
            "storage_migrate",
            context={"user": sysadmin["name"], "ignore_auth": False},
            dry_run=False,
        )

        assert result["success"] is False
        assert "boom" in result["error"]


@pytest.mark.ckan_config("ckan.plugins", "native_cloud_storage")
@pytest.mark.usefixtures("with_plugins", "clean_db")
class TestCLICommands:
    """CLI commands, invoked through the real click test runner + real actions."""

    @patch("ckanext.native_cloud_storage.plugin.AzureBlobStorage")
    def test_status_command_success(self, mock_storage_cls, cli):
        mock_storage = Mock()
        mock_storage.test_connection.return_value = True
        mock_storage.is_emulator_mode.return_value = True
        mock_storage.container_name = "test-filesystem"
        mock_storage_cls.return_value = mock_storage

        result = cli.invoke(native_cloud_storage, ["status"])

        assert result.exit_code == 0
        assert "Connection successful" in result.output

    @patch("ckanext.native_cloud_storage.plugin.AzureBlobStorage")
    def test_status_command_failure(self, mock_storage_cls, cli):
        mock_storage_cls.side_effect = RuntimeError("boom: no connection")

        result = cli.invoke(native_cloud_storage, ["status"])

        # storage_status swallows the exception and returns a
        # success=False dict, but that dict lacks storage_type/container
        # keys, so the status command's own echo logic fails and falls
        # into its own error handler (error_shout doesn't exit non-zero).
        assert result.exit_code == 0
        assert "Failed to check storage status" in result.output

    @patch("ckanext.native_cloud_storage.plugin.AzureBlobStorage")
    def test_migrate_command_dry_run(self, mock_storage_cls, cli):
        mock_storage = Mock()
        mock_storage.migrate_existing_files.return_value = {
            "processed": 1,
            "migrated": 0,
            "errors": 0,
            "files": [{"status": "would_migrate", "local_path": "/a.txt"}],
        }
        mock_storage_cls.return_value = mock_storage

        result = cli.invoke(native_cloud_storage, ["migrate", "--dry-run"])

        assert result.exit_code == 0
        assert "DRY RUN" in result.output
        assert "Files processed: 1" in result.output

    @patch("ckanext.native_cloud_storage.storage.AzureBlobStorage")
    def test_setup_command_success(self, mock_storage_cls, cli):
        mock_storage = Mock()
        mock_storage.test_connection.return_value = True
        mock_storage.container_name = "test-filesystem"
        mock_storage.is_emulator_mode.return_value = True
        mock_storage_cls.return_value = mock_storage

        result = cli.invoke(native_cloud_storage, ["setup"])

        assert result.exit_code == 0
        assert "Setup completed successfully" in result.output

    @patch("ckanext.native_cloud_storage.storage.AzureBlobStorage")
    def test_setup_command_connection_failure(self, mock_storage_cls, cli):
        mock_storage = Mock()
        mock_storage.test_connection.return_value = False
        mock_storage_cls.return_value = mock_storage

        result = cli.invoke(native_cloud_storage, ["setup"])

        # error_shout() only echoes to stderr in CKAN's CLI helper; it does
        # not raise/exit, so the command still "succeeds" from click's
        # perspective but the failure message is present in the output.
        assert result.exit_code == 0
        assert "Cannot connect to Azure Storage" in result.output
