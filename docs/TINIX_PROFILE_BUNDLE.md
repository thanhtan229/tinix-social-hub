# Tinix Profile Bundle v1

A portable profile is a directory ending in `.tinix-profile`:

```text
Account-name.tinix-profile/
├── manifest.json
└── chrome-profile/
```

Required manifest fields are `bundle_format: "tinix-profile"`, `format_version: 1`, `account_name` and `platform`. Optional provenance fields include `source_app`, `source_app_version`, `source_account_id`, `username` and `exported_at`.

The bundle transfers account identity metadata and a copied Chrome session. It never includes passwords, 2FA secrets, email passwords or cookie fields read from an application database. Chrome must be closed before Import or Export.
