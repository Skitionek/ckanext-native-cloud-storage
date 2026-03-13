from setuptools import setup, find_packages

version = '0.1.0'

setup(
    name='ckanext-native-cloud-storage',
    version=version,
    description="CKAN extension for native cloud storage with Azure support",
    long_description='''
    A CKAN extension that provides native cloud storage capabilities with
    support for Azure Blob Storage and Azure Event Hub integration.
    Includes development support for Azure Storage Emulator and Event Hub Emulator.
    ''',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
    ],
    keywords='CKAN Azure Cloud Storage',
    author='CKAN Extension Developer',
    author_email='',
    url='https://github.com/Skitionek/ckanext-native-cloud-storage',
    license='MIT',
    packages=find_packages(exclude=['ez_setup', 'examples', 'tests']),
    namespace_packages=['ckanext'],
    include_package_data=True,
    zip_safe=False,
    install_requires=[
        'azure-storage-blob>=12.0.0',
        'azure-eventhub>=5.0.0',
        'azure-identity>=1.0.0',
        'ckan>=2.9.0',
    ],
    extras_require={
        'dev': [
            'pytest>=6.0.0',
            'pytest-cov>=2.10.0',
            'flake8>=3.8.0',
            'black>=20.8b1',
        ]
    },
    entry_points={
        'ckan.plugins': [
            'native_cloud_storage = ckanext.native_cloud_storage.plugin:NativeCloudStoragePlugin',
        ],
        'ckan.click_commands': [
            'native_cloud_storage = ckanext.native_cloud_storage.commands:get_commands',
        ],
        'babel.extractors': [
            'ckan = ckan.lib.extract:extract_ckan',
        ],
    },
    message_extractors={
        'ckanext': [
            ('**.py', 'python', None),
            ('**.js', 'javascript', None),
            ('**/templates/**.html', 'ckan', None),
        ],
    }
)