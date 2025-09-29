#!/usr/bin/env python3
"""
Validation script for CKAN Native Cloud Storage extension setup
"""
import os
import sys
import subprocess
import requests

def check_python_packages():
    """Check if required Python packages are installed"""
    print("Checking Python packages...")
    
    required_packages = [
        'azure-storage-blob',
        'azure-eventhub', 
        'azure-identity',
        'ckan'
    ]
    
    missing_packages = []
    for package in required_packages:
        try:
            __import__(package.replace('-', '.'))
            print(f"  ✓ {package}")
        except ImportError:
            print(f"  ✗ {package} - MISSING")
            missing_packages.append(package)
    
    if missing_packages:
        print(f"\nMissing packages: {missing_packages}")
        print("Install with: pip install " + " ".join(missing_packages))
        return False
    
    return True

def check_emulator_connectivity():
    """Check if Azure emulators are running and accessible"""
    print("\nChecking Azure emulators...")
    
    # Check Azurite (Storage Emulator)
    try:
        response = requests.get('http://localhost:10000/devstoreaccount1', timeout=5)
        if response.status_code == 400:  # Expected response from Azurite
            print("  ✓ Azurite (Storage Emulator) is running")
            azurite_ok = True
        else:
            print("  ✗ Azurite responded but with unexpected status")
            azurite_ok = False
    except requests.exceptions.RequestException:
        print("  ✗ Azurite (Storage Emulator) is not accessible")
        print("    Start with: docker run -p 10000:10000 mcr.microsoft.com/azure-storage/azurite")
        azurite_ok = False
    
    # Check Event Hub Emulator (harder to test directly)
    try:
        result = subprocess.run(['docker', 'ps'], capture_output=True, text=True)
        if 'eventhubs-emulator' in result.stdout:
            print("  ✓ Event Hub Emulator container is running")
            eventhub_ok = True
        else:
            print("  ✗ Event Hub Emulator container not found")
            print("    Start with: docker run -p 5672:5672 mcr.microsoft.com/azure-messaging/eventhubs-emulator")
            eventhub_ok = False
    except subprocess.SubprocessError:
        print("  ? Unable to check Event Hub Emulator (Docker not available)")
        eventhub_ok = None
    
    return azurite_ok, eventhub_ok

def check_ckan_config():
    """Check CKAN configuration for the extension"""
    print("\nChecking CKAN configuration...")
    
    config_hints = [
        "Add to ckan.ini:",
        "  ckan.plugins = ... native_cloud_storage",
        "  ckanext.native_cloud_storage.azure.use_emulator = true",
        "  ckanext.native_cloud_storage.azure.container_name = ckan-storage"
    ]
    
    print("\n".join(config_hints))
    return True

def main():
    """Main validation function"""
    print("CKAN Native Cloud Storage Extension - Setup Validation")
    print("=" * 60)
    
    all_ok = True
    
    # Check Python packages
    if not check_python_packages():
        all_ok = False
    
    # Check emulators
    azurite_ok, eventhub_ok = check_emulator_connectivity()
    if not azurite_ok:
        all_ok = False
    
    # Show configuration guidance
    check_ckan_config()
    
    print("\n" + "=" * 60)
    if all_ok:
        print("✓ Setup validation completed successfully!")
        print("\nNext steps:")
        print("1. Configure CKAN with the extension settings")
        print("2. Restart CKAN")
        print("3. Test file uploads")
    else:
        print("✗ Setup validation found issues that need to be resolved")
        print("\nPlease fix the issues above and run this script again")
        sys.exit(1)

if __name__ == '__main__':
    main()