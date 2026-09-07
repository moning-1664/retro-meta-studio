# v0.5 Database Shadow Mode

## Purpose

During the JSON -> SQLite migration, the application can compare the legacy JSON projection with the SQLite projection without changing the normal API contract.

## Modes

- `off`: no shadow comparison.
- `shadow`: compare and log mismatches; the application continues normally.
- `strict`: compare and raise `AssertionError` on a mismatch; intended for automated tests/development.

Configuration:

```json
{
  "database_debug": {
    "mode": "shadow"
  }
}
```

The API also exposes `get_database_debug()` and `set_database_debug(mode)`.

## Logging

Only mismatches are written to:

`logs/db_shadow_mismatch.log`

Each record is JSON Lines and includes the operation, mode, JSON-side semantic projection, and SQLite-side semantic projection.

## Comparison rules

The checker compares canonical semantic data rather than raw JSON/SQL representations. Dictionary key order and SQLite internal IDs are therefore ignored. Version records are keyed by `(rom_id, version_id)` in SQLite because legacy JSON version IDs are scoped to a ROM and may repeat across ROMs.

## Current scope

The current shadow layer covers the migration-relevant ROM, metadata-version, and ROM-level media projection used by the native MasterDB read path. GameListSet membership and SimilarGroup persistence will be added to the comparison scope when their native repository write/read paths are migrated.
