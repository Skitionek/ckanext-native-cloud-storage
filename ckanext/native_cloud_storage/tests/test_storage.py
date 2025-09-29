import os
import pytest
from unittest.mock import Mock, patch, MagicMock
from io import BytesIO

from ckanext.native_cloud_storage.storage import AzureBlobStorage


class TestAzureBlobStorage:
    """Test cases for Azure Blob Storage functionality"""
    
    def setup_method(self):
        """Set up test environment"""
        self.test_config = {
            'ckanext.native_cloud_storage.azure.use_emulator': 'true',
            'ckanext.native_cloud_storage.azure.container_name': 'test-container',
            'ckanext.native_cloud_storage.azure.eventhub_name': 'test-eventhub'
        }
        
    @patch('ckanext.native_cloud_storage.storage.config')
    def test_emulator_mode_detection(self, mock_config):
        """Test emulator mode detection"""
        mock_config.get.side_effect = lambda key, default=None: self.test_config.get(key, default)
        
        storage = AzureBlobStorage()
        assert storage.is_emulator_mode() is True
        
    @patch('ckanext.native_cloud_storage.storage.config')
    @patch('ckanext.native_cloud_storage.storage.BlobServiceClient')
    def test_blob_service_client_creation_emulator(self, mock_blob_client, mock_config):
        """Test blob service client creation in emulator mode"""
        mock_config.get.side_effect = lambda key, default=None: self.test_config.get(key, default)
        
        storage = AzureBlobStorage()
        client = storage.blob_service_client
        
        mock_blob_client.from_connection_string.assert_called_once()
        
    @patch('ckanext.native_cloud_storage.storage.config')
    def test_connection_test(self, mock_config):
        """Test storage connection testing"""
        mock_config.get.side_effect = lambda key, default=None: self.test_config.get(key, default)
        
        storage = AzureBlobStorage()
        
        # Mock container client
        mock_container_client = Mock()
        mock_container_client.get_container_properties.return_value = True
        storage._container_client = mock_container_client
        
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
        
        # Mock container client
        mock_blob_client = Mock()
        mock_container_client = Mock()
        mock_container_client.get_blob_client.return_value = mock_blob_client
        storage._container_client = mock_container_client
        
        storage.upload()
        
        mock_blob_client.upload_blob.assert_called_once()
        
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
        
        # Mock container client
        storage._container_client = Mock()
        
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