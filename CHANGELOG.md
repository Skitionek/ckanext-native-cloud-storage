# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Port automation practices from [Skitionek/template](https://github.com/Skitionek/template):
  - CodeQL Advanced security scanning (GitHub Actions + Python)
  - MegaLinter with smart flavor detection and auto-fix PRs
  - Copilot auto-fix on CI failure
  - Dependabot auto-merge for patch/minor updates
  - Auto-approve MegaLinter fix PRs
  - Dependabot configuration for GitHub Actions and pip
  - Docker build and publish reusable action
  - CODEOWNERS, FUNDING.yml, copilot-instructions.md
  - `.cspell.json` spell-checking config

### Changed

- Migrated file storage from Azure Blob Storage APIs to Azure Data Lake Storage Gen2 filesystem APIs while preserving CKAN uploader compatibility.
- Switched primary file-event notification configuration to Azure Service Bus Queue settings, with Event Hub fallback for backward compatibility.
- Raised the project Python baseline to 3.10 in package metadata and installation docs.
- Marked DevSkim and KICS MegaLinter checks as non-blocking: DevSkim findings are ManualReview notes on legitimate local-emulator connection strings; KICS findings are all in the `.devcontainer/` development submodule.

### Fixed

- Updated configuration examples, admin UI labels, and README terminology to match Data Lake Gen2 semantics (`file_system_name`) and queue-based event configuration.
- Fixed Python lint issues by applying Black formatting, cleaning unused imports/variables, and adding repository Flake8 settings.

[Unreleased]: https://github.com/Skitionek/ckanext-native-cloud-storage
