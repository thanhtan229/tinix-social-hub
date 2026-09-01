# Tinix Social Studio 1.0.0-rc.3

This release introduces the portable Tinix profile bundle shared with Tinix FB Down.

- Export creates a `.tinix-profile` directory containing `manifest.json` and `chrome-profile/`.
- Manifest preserves account name, platform, source app/version and source account identifier.
- Import creates an account automatically; pre-creating an account is no longer required.
- Passwords, 2FA secrets and database cookie fields are not exported.
- Chrome cache and lock files are excluded; live profiles and symlink/junction content are rejected.
