# Installation Guide for CKAN Native Cloud Storage Extension

This guide provides step-by-step instructions for installing and configuring the CKAN Native Cloud Storage Extension with Azure support.

## Prerequisites

- CKAN 2.9+ installed and running
- Python 3.10+
- Docker (for development with emulators)
- Azure Storage Account (for production) or Azure Storage Emulator (for development)

## Installation Steps

### 1. Install the Extension

```bash
# Option A: Install from PyPI (when available)
pip install ckanext-native-cloud-storage

# Option B: Install from source
git clone https://github.com/Skitionek/ckanext-native-cloud-storage.git
cd ckanext-native-cloud-storage
pip install -e .
pip install -r requirements.txt
```

### 2. Development Setup with Emulators

For development, use the provided Docker Compose setup:

```bash
# Start Azure emulators
docker-compose up -d azurite eventhub-emulator

# Verify emulators are running
curl http://localhost:10000/devstoreaccount1
docker logs ckan-eventhub-emulator
```

### 3. Production Setup

For production, create an Azure Storage Account:

1. Create an Azure Storage Account in the Azure Portal
2. Get the account name and access key
3. Optionally create an Azure Event Hub namespace and hub

### 4. Configure CKAN

Add the following to your CKAN configuration file (`ckan.ini`):

```ini
# Enable the plugin
ckan.plugins = datastore datapusher native_cloud_storage

# Development configuration (with emulators)
ckanext.native_cloud_storage.azure.use_emulator = true
ckanext.native_cloud_storage.azure.container_name = ckan-storage
ckanext.native_cloud_storage.azure.eventhub_name = ckan-file-events

# Production configuration
# ckanext.native_cloud_storage.azure.use_emulator = false
# ckanext.native_cloud_storage.azure.account_name = your_storage_account
# ckanext.native_cloud_storage.azure.account_key = your_storage_key
# ckanext.native_cloud_storage.azure.container_name = ckan-storage
# ckanext.native_cloud_storage.azure.eventhub_connection_string = Endpoint=sb://...
# ckanext.native_cloud_storage.azure.eventhub_name = ckan-file-events
```

### 5. Restart CKAN

```bash
# Restart CKAN service (method depends on your deployment)
sudo systemctl restart ckan
# or
supervisorctl restart ckan
```

### 6. Verify Installation

```bash
# Check storage status via CKAN CLI
ckan -c /path/to/ckan.ini native-cloud-storage status

# Or use the validation script
python scripts/validate_setup.py
```

## Configuration Options

### Required Settings

| Setting | Description | Example |
|---------|-------------|---------|
| `ckan.plugins` | Add `native_cloud_storage` | `datastore datapusher native_cloud_storage` |

### Azure Storage Settings

| Setting | Description | Required | Default |
|---------|-------------|----------|---------|
| `ckanext.native_cloud_storage.azure.use_emulator` | Use emulator for development | No | `false` |
| `ckanext.native_cloud_storage.azure.account_name` | Azure Storage account name | Yes (prod) | - |
| `ckanext.native_cloud_storage.azure.account_key` | Azure Storage account key | Yes (prod) | - |
| `ckanext.native_cloud_storage.azure.connection_string` | Full connection string | Alternative | - |
| `ckanext.native_cloud_storage.azure.container_name` | Container for CKAN files | No | `ckan-storage` |

### Event Hub Settings (Optional)

| Setting | Description | Required | Default |
|---------|-------------|----------|---------|
| `ckanext.native_cloud_storage.azure.eventhub_connection_string` | Event Hub connection string | No | - |
| `ckanext.native_cloud_storage.azure.eventhub_name` | Event Hub name | No | `ckan-file-events` |

## Testing the Installation

### 1. Upload a File

1. Go to your CKAN instance
2. Create or edit a dataset
3. Add a resource by uploading a file
4. The file should be stored in Azure Blob Storage

### 2. Check Storage Status

```bash
ckan -c /path/to/ckan.ini native-cloud-storage status
```

Expected output:
```
Storage Status: connected
Storage Type: azure_blob
Container: ckan-storage
Emulator Mode: true
✓ Connection successful
```

### 3. Migrate Existing Files (Optional)

```bash
# Dry run to see what would be migrated
ckan -c /path/to/ckan.ini native-cloud-storage migrate --dry-run

# Actually migrate files
ckan -c /path/to/ckan.ini native-cloud-storage migrate
```

## Troubleshooting

### Common Issues

1. **"No module named 'azure'"**
   - Solution: Install Azure SDK packages: `pip install azure-storage-blob azure-eventhub azure-identity`

2. **"Connection failed" in status check**
   - Check Azure credentials
   - Verify emulator is running (development)
   - Check network connectivity (production)

3. **"Plugin not found"**
   - Ensure the extension is installed: `pip list | grep ckanext-native-cloud-storage`
   - Check CKAN plugins configuration
   - Restart CKAN after configuration changes

4. **Files not uploading to Azure**
   - Check CKAN logs for errors
   - Verify container exists and has correct permissions
   - Test storage connection: `ckan native-cloud-storage status`

### Debug Mode

Enable debug logging in CKAN configuration:

```ini
[logger_ckanext_native_cloud_storage]
level = DEBUG
handlers = console
qualname = ckanext.native_cloud_storage
```

### Getting Help

- Check the [README.md](README.md) for detailed documentation
- Review the [GitHub Issues](https://github.com/Skitionek/ckanext-native-cloud-storage/issues)
- Consult CKAN documentation: https://docs.ckan.org/
- Azure Storage documentation: https://docs.microsoft.com/azure/storage/