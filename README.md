# ckanext-native-cloud-storage

A CKAN extension for native cloud storage integration with Azure Data Lake Storage Gen2 and Azure Service Bus Queue support. This extension provides seamless file storage in Azure cloud with development support for Azure Storage Emulator (Azurite) and Service Bus Queue Emulator.

## Features

- **Azure Data Lake Storage Gen2 Integration**: Store CKAN files directly in Azure Data Lake Storage Gen2
- **Azure Service Bus Queue Integration**: Send file operation events to Azure Service Bus Queue
- **Emulator Support**: Development support with Azure Storage Emulator (Azurite) and Service Bus Queue Emulator
- **File Migration**: Migrate existing local files to Azure storage
- **Secure Access**: SAS token generation for secure file access
- **Admin Interface**: Storage status monitoring and migration tools

## Requirements

- CKAN >= 2.9
- Python >= 3.10
- Azure Storage Account (production) or Azure Storage Emulator (development)
- Azure Service Bus Queue (optional, for file events)

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
ckanext.native_cloud_storage.azure.file_system_name = ckan-storage

# Optional: Azure Service Bus Queue for file events
ckanext.native_cloud_storage.azure.servicebus_connection_string = Endpoint=sb://...
ckanext.native_cloud_storage.azure.servicebus_queue_name = ckan-file-events
```

### Development Configuration (with Emulators)

For development, you can use Azure Storage Emulator and Service Bus Queue Emulator:

```ini
# Use emulators for development
ckanext.native_cloud_storage.azure.use_emulator = true
ckanext.native_cloud_storage.azure.file_system_name = ckan-storage
ckanext.native_cloud_storage.azure.servicebus_queue_name = ckan-file-events
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

   # Check Service Bus Queue Emulator
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

**Azure Service Bus Queue Emulator (Event Hubs emulator compatible mode):**

```bash
docker run -it --rm -p 5672:5672 mcr.microsoft.com/azure-messaging/eventhubs-emulator:latest
```

## Usage

### File Uploads

Once configured, all CKAN file uploads will automatically use Azure Data Lake Storage Gen2:

1. Upload dataset resources through the web interface
2. Files are stored in Azure Data Lake Storage Gen2
3. File URLs point to Azure Data Lake Storage Gen2 (with SAS tokens for security)
4. File events are sent to Service Bus Queue (if configured)

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

| Setting                                                           | Description                         | Default            | Required                |
|-------------------------------------------------------------------|-------------------------------------|--------------------|-------------------------|
| `ckanext.native_cloud_storage.azure.use_emulator`                 | Use Azure Storage Emulator          | `false`            | No                      |
| `ckanext.native_cloud_storage.azure.account_name`                 | Azure Storage Account name          | -                  | Yes (production)        |
| `ckanext.native_cloud_storage.azure.account_key`                  | Azure Storage Account key           | -                  | Yes (production)        |
| `ckanext.native_cloud_storage.azure.connection_string`            | Full connection string              | -                  | Alternative to name/key |
| `ckanext.native_cloud_storage.azure.file_system_name`             | Storage file system name            | `ckan-storage`     | No                      |
| `ckanext.native_cloud_storage.azure.servicebus_connection_string` | Service Bus Queue connection string | -                  | No                      |
| `ckanext.native_cloud_storage.azure.servicebus_queue_name`        | Service Bus Queue name              | `ckan-file-events` | No                      |

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
- **Storage (`storage.py`)**: Azure Data Lake Storage Gen2 implementation with Service Bus Queue integration
- **Tests**: Comprehensive test suite with mocking for Azure services
- **Docker Compose**: Development environment with emulators

### File Storage Flow

1. User uploads file via CKAN interface
2. Extension intercepts upload via IUploader interface
3. File is uploaded to Azure Data Lake Storage Gen2
4. SAS token is generated for secure access
5. File event is sent to Service Bus Queue (optional)
6. CKAN stores Azure Data Lake URL as file location

### Service Bus Queue Integration

File operations generate events sent to Azure Service Bus Queue:

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
- Ensure file system exists and is accessible

**File Upload Issues:**

- Check CKAN file upload limits
- Verify file system permissions
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
- Azure Documentation: [Azure Storage](https://learn.microsoft.com/azure/storage/) | [Azure Service Bus Queues](https://learn.microsoft.com/azure/service-bus-messaging/)
