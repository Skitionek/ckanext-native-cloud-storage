import logging
import os
from urllib.parse import urlparse

import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit
from ckan.common import config

from ckanext.native_cloud_storage.storage import AzureBlobStorage
from ckanext.native_cloud_storage import commands

log = logging.getLogger(__name__)


class NativeCloudStoragePlugin(plugins.SingletonPlugin):
    """
    CKAN plugin for native cloud storage integration with Azure Data Lake Gen2
    """
    
    plugins.implements(plugins.IConfigurer)
    plugins.implements(plugins.IUploader, inherit=True)
    plugins.implements(plugins.IActions)
    plugins.implements(plugins.IClick)
    
    def update_config(self, config_):
        """Update CKAN config with plugin settings"""
        toolkit.add_template_directory(config_, 'templates')
        toolkit.add_public_directory(config_, 'public')
        toolkit.add_resource('public', 'native_cloud_storage')
    
    def get_resource_uploader(self, data_dict):
        """Return the Azure Data Lake uploader for resources"""
        return AzureBlobStorage()
    
    def get_uploader(self, upload_to, old_filename=None):
        """Return the Azure Data Lake uploader for general storage"""
        return AzureBlobStorage(upload_to=upload_to, old_filename=old_filename)
    
    def get_actions(self):
        """Register custom actions"""
        return {
            'storage_status': storage_status,
            'storage_migrate': storage_migrate,
        }
    
    def get_commands(self):
        """Register CLI commands"""
        return commands.get_commands()


def storage_status(context, data_dict):
    """
    Action to check Azure storage connection status
    
    :returns: Storage connection status information
    :rtype: dict
    """
    toolkit.check_access('sysadmin', context)
    
    try:
        storage = AzureBlobStorage()
        status = storage.test_connection()
        return {
            'success': True,
            'status': 'connected' if status else 'disconnected',
            'storage_type': 'azure_data_lake_gen2',
            'emulator_mode': storage.is_emulator_mode(),
            'container_name': storage.container_name
        }
    except Exception as e:
        log.error(f"Storage status check failed: {e}")
        return {
            'success': False,
            'error': str(e),
            'status': 'error'
        }


def storage_migrate(context, data_dict):
    """
    Action to migrate existing files to Azure storage
    
    :returns: Migration status and results
    :rtype: dict
    """
    toolkit.check_access('sysadmin', context)
    
    dry_run = data_dict.get('dry_run', True)
    
    try:
        storage = AzureBlobStorage()
        results = storage.migrate_existing_files(dry_run=dry_run)
        return {
            'success': True,
            'results': results,
            'dry_run': dry_run
        }
    except Exception as e:
        log.error(f"Storage migration failed: {e}")
        return {
            'success': False,
            'error': str(e)
        }