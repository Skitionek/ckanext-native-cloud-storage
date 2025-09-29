# ckanext-native-cloud-storage

A CKAN extension for native cloud storage integration with Azure Blob Storage and Azure Event Hub support. This extension provides seamless file storage in Azure cloud with development support for Azure Storage Emulator (Azurite) and Event Hub Emulator.

## Features

- **Azure Blob Storage Integration**: Store CKAN files directly in Azure Blob Storage
- **Azure Event Hub Integration**: Send file operation events to Azure Event Hub
- **Emulator Support**: Development support with Azure Storage Emulator (Azurite) and Event Hub Emulator
- **File Migration**: Migrate existing local files to Azure storage
- **Secure Access**: SAS token generation for secure file access
- **Admin Interface**: Storage status monitoring and migration tools

## Requirements

- CKAN >= 2.9
- Python >= 3.7
- Azure Storage Account (production) or Azure Storage Emulator (development)
- Azure Event Hub (optional, for file events)

## Installation

1. **Clone or install the extension:**
   ```bash
   pip install ckanext-native-cloud-storage
   ```
   
   Or from source:
   ```bash
   git clone https://github.com/Skitionek/ckanext-native-cloud-storage.git
   cd ckanext-native-cloud-storage
   pip install -e .
   pip install -r requirements.txt
   ```

2. **Add the plugin to your CKAN configuration:**
   ```ini
   ckan.plugins = ... native_cloud_storage
   ```

3. **Configure Azure Storage settings** (see Configuration section below)

4. **Restart CKAN**

## Configuration

### Production Configuration

Add the following settings to your CKAN configuration file (`ckan.ini`):

```ini
# Azure Storage Account Configuration
ckanext.native_cloud_storage.azure.account_name = your_storage_account
ckanext.native_cloud_storage.azure.account_key = your_storage_key
ckanext.native_cloud_storage.azure.container_name = ckan-storage

# Optional: Azure Event Hub for file events
ckanext.native_cloud_storage.azure.eventhub_connection_string = Endpoint=sb://...
ckanext.native_cloud_storage.azure.eventhub_name = ckan-file-events
```

### Development Configuration (with Emulators)

For development, you can use Azure Storage Emulator and Event Hub Emulator:

```ini
# Use emulators for development
ckanext.native_cloud_storage.azure.use_emulator = true
ckanext.native_cloud_storage.azure.container_name = ckan-storage
ckanext.native_cloud_storage.azure.eventhub_name = ckan-file-events
```

## Development Setup with Emulators

This extension includes Docker Compose setup for running Azure emulators locally:

1. **Start the emulators:**
   ```bash
   docker-compose up -d azurite eventhub-emulator
   ```

2. **Verify emulators are running:**
   ```bash
   # Check Azurite (Storage Emulator)
   curl http://localhost:10000/devstoreaccount1
   
   # Check Event Hub Emulator
   docker logs ckan-eventhub-emulator
   ```

3. **Full development environment:**
   ```bash
   # Start all services including CKAN
   docker-compose up -d
   
   # Access CKAN at http://localhost:5000
   ```

### Manual Emulator Setup

If you prefer to run emulators manually:

**Azurite (Azure Storage Emulator):**
```bash
npm install -g azurite
azurite --silent --location /tmp/azurite --debug /tmp/azurite/debug.log
```

**Azure Event Hub Emulator:**
```bash
docker run -it --rm -p 5672:5672 mcr.microsoft.com/azure-messaging/eventhubs-emulator:latest
```

## Usage

### File Uploads

Once configured, all CKAN file uploads will automatically use Azure Blob Storage:

1. Upload dataset resources through the web interface
2. Files are stored in Azure Blob Storage
3. File URLs point to Azure Blob Storage (with SAS tokens for security)
4. File events are sent to Event Hub (if configured)

### Admin Actions

The extension provides admin-only actions for storage management:

**Check Storage Status:**
```python
# Via CKAN API
import ckan.plugins.toolkit as toolkit
result = toolkit.get_action('storage_status')({}, {})
print(result)
```

**Migrate Existing Files:**
```python
# Dry run to see what would be migrated
result = toolkit.get_action('storage_migrate')({}, {'dry_run': True})

# Actually migrate files
result = toolkit.get_action('storage_migrate')({}, {'dry_run': False})
```

### Command Line Interface

Access storage management via CKAN CLI:

```bash
# Check storage status
ckan -c /path/to/ckan.ini native-cloud-storage status

# Migrate files (dry run)
ckan -c /path/to/ckan.ini native-cloud-storage migrate --dry-run

# Migrate files (actual migration)
ckan -c /path/to/ckan.ini native-cloud-storage migrate
```

## Configuration Options

| Setting | Description | Default | Required |
|---------|-------------|---------|----------|
| `ckanext.native_cloud_storage.azure.use_emulator` | Use Azure Storage Emulator | `false` | No |
| `ckanext.native_cloud_storage.azure.account_name` | Azure Storage Account name | - | Yes (production) |
| `ckanext.native_cloud_storage.azure.account_key` | Azure Storage Account key | - | Yes (production) |
| `ckanext.native_cloud_storage.azure.connection_string` | Full connection string | - | Alternative to name/key |
| `ckanext.native_cloud_storage.azure.container_name` | Storage container name | `ckan-storage` | No |
| `ckanext.native_cloud_storage.azure.eventhub_connection_string` | Event Hub connection string | - | No |
| `ckanext.native_cloud_storage.azure.eventhub_name` | Event Hub name | `ckan-file-events` | No |

## Testing

Run the test suite:

```bash
# Install test dependencies
pip install -e .[dev]

# Run tests
pytest ckanext/native_cloud_storage/tests/

# Run tests with coverage
pytest --cov=ckanext.native_cloud_storage ckanext/native_cloud_storage/tests/
```

## Architecture

The extension consists of:

- **Plugin (`plugin.py`)**: Main CKAN plugin implementing IUploader and IActions
- **Storage (`storage.py`)**: Azure Blob Storage implementation with Event Hub integration
- **Tests**: Comprehensive test suite with mocking for Azure services
- **Docker Compose**: Development environment with emulators

### File Storage Flow

1. User uploads file via CKAN interface
2. Extension intercepts upload via IUploader interface
3. File is uploaded to Azure Blob Storage
4. SAS token is generated for secure access
5. File event is sent to Event Hub (optional)
6. CKAN stores Azure Blob URL as file location

### Event Hub Integration

File operations generate events sent to Azure Event Hub:
- `upload`: When a file is uploaded
- `delete`: When a file is deleted
- `migrate`: When files are migrated from local storage

Event payload includes:
```json
{
  "event_type": "upload",
  "blob_name": "resources/20231201_120000_123456_filename.pdf",
  "container_name": "ckan-storage",
  "timestamp": "2023-12-01T12:00:00.000Z",
  "source": "ckan_native_cloud_storage"
}
```

## Troubleshooting

### Common Issues

**Connection Errors:**
- Verify Azure Storage credentials
- Check network connectivity to Azure
- For emulators, ensure they are running and accessible

**Permission Errors:**
- Verify Azure Storage Account permissions
- Check SAS token generation settings
- Ensure container exists and is accessible

**File Upload Issues:**
- Check CKAN file upload limits
- Verify container permissions
- Review Azure Storage logs

### Debug Mode

Enable debug logging in CKAN configuration:
```ini
[logger_ckanext_native_cloud_storage]
level = DEBUG
handlers = console
qualname = ckanext.native_cloud_storage
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Run the test suite
6. Submit a pull request

## License

MIT License - see LICENSE file for details.

## Support

- GitHub Issues: [Report bugs and feature requests](https://github.com/Skitionek/ckanext-native-cloud-storage/issues)
- Documentation: [CKAN Extensions Guide](https://docs.ckan.org/en/latest/extensions/)
- Azure Documentation: [Azure Storage](https://docs.microsoft.com/azure/storage/) | [Azure Event Hubs](https://docs.microsoft.com/azure/event-hubs/)