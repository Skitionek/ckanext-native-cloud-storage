import os
import pytest
from unittest.mock import Mock, patch, MagicMock
from io import BytesIO

from ckanext.native_cloud_storage.storage import AzureBlobStorage


class TestAzureBlobStorage:
    """Test cases for Azure Data Lake-backed storage functionality"""
    
    def setup_method(self):
        """Set up test environment"""
        self.test_config = {
            'ckanext.native_cloud_storage.azure.use_emulator': 'true',
            'ckanext.native_cloud_storage.azure.file_system_name': 'test-filesystem',
            'ckanext.native_cloud_storage.azure.servicebus_queue_name': 'test-file-events'
        }
        
    @patch('ckanext.native_cloud_storage.storage.config')
    def test_emulator_mode_detection(self, mock_config):
        """Test emulator mode detection"""
        mock_config.get.side_effect = lambda key, default=None: self.test_config.get(key, default)
        
        storage = AzureBlobStorage()
        assert storage.is_emulator_mode() is True
        
    @patch('ckanext.native_cloud_storage.storage.config')
    @patch('ckanext.native_cloud_storage.storage.DataLakeServiceClient')
    def test_data_lake_service_client_creation_emulator(self, mock_service_client, mock_config):
        """Test data lake service client creation in emulator mode"""
        mock_config.get.side_effect = lambda key, default=None: self.test_config.get(key, default)
        
        storage = AzureBlobStorage()
        client = storage.blob_service_client
        
        mock_service_client.from_connection_string.assert_called_once()
        
    @patch('ckanext.native_cloud_storage.storage.config')
    def test_connection_test(self, mock_config):
        """Test storage connection testing"""
        mock_config.get.side_effect = lambda key, default=None: self.test_config.get(key, default)
        
        storage = AzureBlobStorage()
        
        mock_fs_client = Mock()
        mock_fs_client.get_file_system_properties.return_value = True
        storage._file_system_client = mock_fs_client
        
        assert storage.test_connection() is True
        
    @patch('ckanext.native_cloud_storage.storage.config')
    def test_upload_file(self, mock_config):
        """Test file upload functionality"""
        mock_config.get.side_effect = lambda key, default=None: self.test_config.get(key, default)
        
        storage = AzureBlobStorage()
        
        # Mock file upload
        mock_file = Mock()
        mock_file.file = BytesIO(b'test content')
        mock_file.filename = 'test.txt'
        
        storage.upload_field_storage = mock_file
        storage.filename = 'test.txt'
        
        mock_file_client = Mock()
        mock_fs_client = Mock()
        mock_fs_client.get_file_client.return_value = mock_file_client
        storage._file_system_client = mock_fs_client
        
        storage.upload()
        
        mock_file_client.upload_data.assert_called_once()
        
    @patch('ckanext.native_cloud_storage.storage.config')
    @patch('os.path.exists')
    @patch('os.walk')
    def test_migration_dry_run(self, mock_walk, mock_exists, mock_config):
        """Test migration in dry run mode"""
        mock_config.get.side_effect = lambda key, default=None: self.test_config.get(key, default)
        mock_exists.return_value = True
        mock_walk.return_value = [
            ('/var/lib/ckan/default/resources', [], ['test1.txt', 'test2.pdf'])
        ]
        
        storage = AzureBlobStorage()
        
        storage._file_system_client = Mock()
        
        with patch('os.path.getsize', return_value=1024):
            results = storage.migrate_existing_files(dry_run=True)
            
        assert results['processed'] == 2
        assert results['migrated'] == 0  # Dry run shouldn't migrate
        assert len(results['files']) == 2
        
    def test_blob_name_generation(self):
        """Test blob name generation"""
        storage = AzureBlobStorage(upload_to='resources')
        storage.filename = 'test file.txt'
        
        blob_name = storage._generate_blob_name()
        
        assert 'resources/' in blob_name
        assert 'test_file.txt' in blob_name
        assert blob_name != storage.filename  # Should be modified