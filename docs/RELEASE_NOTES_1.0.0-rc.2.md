# Tinix Social Studio 1.0.0-rc.2

This release adds recoverable Chrome profile transfer for the single-user, Chrome-only workflow.

Highlights:

- Per-account Import, Export, Backup and Restore actions in WebUI.
- Independent copies only; no live profile sharing between projects.
- Chrome process detection for source and destination user-data directories.
- Account maintenance lock prevents jobs from being created or claimed during profile operations.
- Staged copies, Chrome structure validation and automatic pre-replacement backups.
- Symlink/junction rejection plus cache and lock-file exclusion.
- Per-operation audit history with copied file/byte counts and error records.

Schema history is append-only through v11. The upgrade creates a pre-migration SQLite backup. Exported profiles and profile backups contain active login sessions and must be treated as sensitive local data.
