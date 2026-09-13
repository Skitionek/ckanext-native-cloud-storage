from unittest.mock import patch


class TestBasicFunctionality:
    """Basic tests that don't require CKAN installation"""

    @patch("ckanext.native_cloud_storage.storage.config")
    def test_emulator_config_parsing(self, mock_config):
        """Test emulator configuration parsing"""
        # Mock configuration for emulator mode
        test_config = {
            "ckanext.native_cloud_storage.azure.use_emulator": "true",
            "ckanext.native_cloud_storage.azure.file_system_name": "test-filesystem",
        }

        mock_config.get.side_effect = lambda key, default=None: test_config.get(
            key, default
        )

        # Mock toolkit.asbool as well
        with patch("ckanext.native_cloud_storage.storage.toolkit") as mock_toolkit:
            mock_toolkit.asbool.return_value = True

            # Import here to avoid CKAN dependency during module load
            from ckanext.native_cloud_storage.storage import AzureBlobStorage

            storage = AzureBlobStorage()

            assert storage.use_emulator is True
            assert storage.file_system_name == "test-filesystem"
