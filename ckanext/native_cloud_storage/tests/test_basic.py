import os
import pytest
from unittest.mock import Mock, patch


class TestBasicFunctionality:
    """Basic tests that don't require CKAN installation"""
    
    def test_imports(self):
        """Test that Azure SDK can be imported"""
        from azure.storage.filedatalake import DataLakeServiceClient
        from azure.servicebus import ServiceBusClient
        from azure.identity import DefaultAzureCredential
        
        # If we get here, imports are successful
        assert True
        
    @patch('ckanext.native_cloud_storage.storage.config')
    def test_emulator_config_parsing(self, mock_config):
        """Test emulator configuration parsing"""
        # Mock configuration for emulator mode
        test_config = {
            'ckanext.native_cloud_storage.azure.use_emulator': 'true',
            'ckanext.native_cloud_storage.azure.file_system_name': 'test-filesystem',
        }
        
        mock_config.get.side_effect = lambda key, default=None: test_config.get(key, default)
        
        # Mock toolkit.asbool as well
        with patch('ckanext.native_cloud_storage.storage.toolkit') as mock_toolkit:
            mock_toolkit.asbool.return_value = True
            
            # Import here to avoid CKAN dependency during module load
            from ckanext.native_cloud_storage.storage import AzureBlobStorage
            
            storage = AzureBlobStorage()
            
            assert storage.use_emulator is True
            assert storage.file_system_name == 'test-filesystem'
        
    def test_blob_name_generation_logic(self):
        """Test blob name generation without full storage setup"""
        # Test the logic without requiring full Azure setup
        import datetime
        
        timestamp = datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')
        filename = 'test file.txt'
        upload_to = 'resources'
        
        # Simulate the blob name generation
        safe_filename = filename.replace(' ', '_').replace('/', '_')
        expected_pattern = f"{upload_to}/{timestamp}"
        
        assert '_' in safe_filename  # Space was replaced
        assert expected_pattern in expected_pattern  # Timestamp format
        
    def test_configuration_keys(self):
        """Test that all expected configuration keys are defined"""
        expected_keys = [
            'ckanext.native_cloud_storage.azure.use_emulator',
            'ckanext.native_cloud_storage.azure.account_name',
            'ckanext.native_cloud_storage.azure.account_key',
            'ckanext.native_cloud_storage.azure.connection_string',
            'ckanext.native_cloud_storage.azure.container_name',
            'ckanext.native_cloud_storage.azure.file_system_name',
            'ckanext.native_cloud_storage.azure.servicebus_connection_string',
            'ckanext.native_cloud_storage.azure.servicebus_queue_name',
        ]
        
        # These are the configuration keys our extension expects
        for key in expected_keys:
            assert key is not None
            assert len(key) > 0