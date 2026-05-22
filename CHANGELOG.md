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

- Redid the storage implementation around Azure Data Lake Gen2 client patterns inspired by `azure-data-lake-fs`, while keeping CKAN uploader interfaces compatible.
- Switched primary file-event publishing from Event Hub settings to Service Bus queue settings, with Event Hub fallback for backward compatibility.

### Fixed

- Updated configuration examples, admin UI labels, and README terminology to match Data Lake Gen2 semantics (`file_system_name`) and queue-based event configuration.

[Unreleased]: https://github.com/Skitionek/ckanext-native-cloud-storage
