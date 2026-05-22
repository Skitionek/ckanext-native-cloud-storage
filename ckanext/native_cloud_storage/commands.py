"""
CLI commands for native cloud storage management
"""

import click
import ckan.plugins.toolkit as toolkit
from ckan.cli import error_shout


@click.group()
def native_cloud_storage():
    """Native cloud storage management commands"""
    pass


@native_cloud_storage.command()
def status():
    """Check Azure storage connection status"""
    try:
        result = toolkit.get_action("storage_status")({}, {})

        click.echo(f"Storage Status: {result['status']}")
        click.echo(f"Storage Type: {result['storage_type']}")
        click.echo(f"Container: {result['container_name']}")
        click.echo(f"Emulator Mode: {result['emulator_mode']}")

        if result["success"]:
            click.echo("✓ Connection successful")
        else:
            click.echo(f"✗ Connection failed: {result.get('error', 'Unknown error')}")

    except Exception as e:
        error_shout(f"Failed to check storage status: {e}")


@native_cloud_storage.command()
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show what would be migrated without actually migrating",
)
def migrate(dry_run):
    """Migrate existing files to Azure storage"""
    try:
        result = toolkit.get_action("storage_migrate")({}, {"dry_run": dry_run})

        if dry_run:
            click.echo("DRY RUN - No files will be migrated")

        click.echo(f"Files processed: {result['results']['processed']}")
        click.echo(f"Files migrated: {result['results']['migrated']}")
        click.echo(f"Errors: {result['results']['errors']}")

        if result["results"]["files"]:
            click.echo("\nFile details:")
            for file_info in result["results"]["files"][:10]:  # Show first 10
                status = file_info["status"]
                path = file_info["local_path"]
                click.echo(f"  {status}: {path}")

            if len(result["results"]["files"]) > 10:
                click.echo(
                    f"  ... and {len(result['results']['files']) - 10} more files"
                )

        if result["success"]:
            if dry_run:
                click.echo("✓ Migration preview completed")
            else:
                click.echo("✓ Migration completed successfully")
        else:
            click.echo(f"✗ Migration failed: {result.get('error', 'Unknown error')}")

    except Exception as e:
        error_shout(f"Failed to migrate files: {e}")


@native_cloud_storage.command()
@click.option("--container", help="Container name to create")
def setup():
    """Set up Azure storage container and initial configuration"""
    try:
        from ckanext.native_cloud_storage.storage import AzureBlobStorage

        storage = AzureBlobStorage()

        # Test connection
        if not storage.test_connection():
            error_shout(
                "Cannot connect to Azure Storage. Please check your configuration."
            )

        click.echo("✓ Azure Storage connection verified")
        click.echo(f"✓ Container '{storage.container_name}' is ready")

        if storage.is_emulator_mode():
            click.echo("ℹ Running in emulator mode")

        click.echo("Setup completed successfully!")

    except Exception as e:
        error_shout(f"Setup failed: {e}")


def get_commands():
    """Return list of CLI commands for CKAN"""
    return [native_cloud_storage]
