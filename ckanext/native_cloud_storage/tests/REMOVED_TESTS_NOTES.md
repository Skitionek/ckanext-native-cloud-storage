# Vacuous tests removed from test_basic.py

Audited 2026-09-13. The following tests were removed because they asserted
nothing that could ever fail, or reimplemented production logic locally
instead of exercising `AzureBlobStorage`. Kept: `test_emulator_config_parsing`
(it actually instantiates `AzureBlobStorage` and checks real attribute values).

## test_imports
Body was only `assert True` after a comment. It never imported anything and
could not fail. Behavior that still needs coverage: importing
`ckanext.native_cloud_storage.storage` (and any Azure SDK dependencies) does
not raise — e.g. a real `import ckanext.native_cloud_storage.storage` at
module scope, or via `importlib.import_module`, asserting the module/class is
importable.

## test_blob_name_generation_logic
Reimplemented a local, simplified version of filename sanitization
(`filename.replace(" ", "_").replace("/", "_")`) instead of calling
`AzureBlobStorage._generate_blob_name` (see `storage.py:256`), then asserted
tautologies against its own local variables (`"_" in safe_filename` where
`safe_filename` was computed in the same test, and
`expected_pattern in expected_pattern`, a self-comparison that always holds).
It tested nothing about the real implementation. Behavior that still needs
coverage: call `AzureBlobStorage._generate_blob_name` (mocking
`AzureBlobStorage.__init__` dependencies as needed) with filenames containing
spaces/slashes and assert the actual returned blob name matches the real
sanitization + path format the production code produces.

## test_configuration_keys
Asserted only that hardcoded string literals (written by the test itself)
were non-None and non-empty — a tautology about the test's own data, not
about the extension. It did not check that these keys are recognized/used by
`AzureBlobStorage` or exposed via `config_declaration.yaml` (if present).
Behavior that still needs coverage: assert each of these configuration keys
is actually read by `AzureBlobStorage.__init__` (e.g. via `config.get` calls
in `storage.py`), or reconcile with `config_declaration.yaml` if the plugin
declares its config schema there.
