#!/usr/bin/env python3
"""
Demo script for CKAN Native Cloud Storage Extension

This script demonstrates the extension functionality without requiring
a full CKAN installation.
"""

import importlib
import sys
from unittest.mock import patch


def demo_basic_functionality():
    """Demonstrate basic extension functionality"""
    print("CKAN Native Cloud Storage Extension Demo")
    print("=" * 50)

    # Test 1: Azure SDK imports
    print("\n1. Testing Azure SDK imports...")
    try:
        blob_module = importlib.import_module("azure.storage.blob")
        eventhub_module = importlib.import_module("azure.eventhub")
        identity_module = importlib.import_module("azure.identity")

        if not (blob_module and eventhub_module and identity_module):
            raise ImportError("Azure SDK modules failed to import")

        print("   ✓ Azure SDK packages imported successfully")
    except ImportError as e:
        print(f"   ✗ Azure SDK import failed: {e}")
        return False

    # Test 2: Extension module structure
    print("\n2. Testing extension module structure...")
    try:
        plugin_module = importlib.import_module("ckanext.native_cloud_storage.plugin")
        storage_module = importlib.import_module("ckanext.native_cloud_storage.storage")

        if not (plugin_module and storage_module):
            raise ImportError("Extension modules failed to import")

        print("   ✓ Extension modules imported successfully")
    except ImportError as e:
        print(f"   ✗ Extension import failed: {e}")
        return False

    # Test 3: Configuration handling (mocked)
    print("\n3. Testing configuration handling...")
    try:
        # Mock CKAN dependencies
        with (
            patch("ckanext.native_cloud_storage.storage.config") as mock_config,
            patch("ckanext.native_cloud_storage.storage.toolkit") as mock_toolkit,
        ):

            # Set up mock configuration
            test_config = {
                "ckanext.native_cloud_storage.azure.use_emulator": "true",
                "ckanext.native_cloud_storage.azure.container_name": "demo-container",
                "ckanext.native_cloud_storage.azure.account_name": "demoAccount",
            }

            mock_config.get.side_effect = lambda key, default="": test_config.get(
                key, default
            )
            mock_toolkit.asbool.return_value = True

            from ckanext.native_cloud_storage.storage import AzureBlobStorage

            storage_instance = AzureBlobStorage()

            print(f"   ✓ Emulator mode: {storage_instance.is_emulator_mode()}")
            print(f"   ✓ Container name: {storage_instance.container_name}")
            print(f"   ✓ Account name: {storage_instance.account_name}")

    except Exception as e:
        print(f"   ✗ Configuration test failed: {e}")
        return False

    # Test 4: Plugin instantiation (mocked)
    print("\n4. Testing plugin instantiation...")
    try:
        with (
            patch("ckanext.native_cloud_storage.plugin.toolkit"),
            patch("ckanext.native_cloud_storage.plugin.config"),
        ):

            from ckanext.native_cloud_storage.plugin import NativeCloudStoragePlugin

            plugin_instance = NativeCloudStoragePlugin()

            # Test plugin interface methods exist
            assert hasattr(plugin_instance, "update_config")
            assert hasattr(plugin_instance, "get_resource_uploader")
            assert hasattr(plugin_instance, "get_actions")

            print("   ✓ Plugin instantiated successfully")
            print("   ✓ Required interface methods found")

    except Exception as e:
        print(f"   ✗ Plugin test failed: {e}")
        return False

    # Test 5: Docker Compose configuration
    print("\n5. Testing Docker Compose configuration...")
    try:
        import yaml

        with open("docker-compose.yml", "r") as f:
            docker_config = yaml.safe_load(f)

        # Check required services
        services = docker_config.get("services", {})
        required_services = ["azurite", "eventhub-emulator"]

        for service in required_services:
            if service in services:
                print(f"   ✓ {service} service configured")
            else:
                print(f"   ✗ {service} service missing")
                return False

        # Check ports
        azurite_ports = services.get("azurite", {}).get("ports", [])
        if "10000:10000" in azurite_ports:
            print("   ✓ Azurite port 10000 exposed")
        else:
            print("   ✗ Azurite port configuration incorrect")

    except Exception as e:
        print(f"   ✗ Docker Compose test failed: {e}")
        return False

    print("\n" + "=" * 50)
    print("✓ All demo tests passed successfully!")

    print("\nNext steps to use the extension:")
    print("1. Install requirements: pip install -r requirements.txt")
    print("2. Start emulators: docker compose up -d azurite eventhub-emulator")
    print("3. Configure CKAN with the extension settings")
    print("4. Add 'native_cloud_storage' to ckan.plugins in ckan.ini")
    print("5. Restart CKAN and test file uploads")

    return True


if __name__ == "__main__":
    success = demo_basic_functionality()
    sys.exit(0 if success else 1)
