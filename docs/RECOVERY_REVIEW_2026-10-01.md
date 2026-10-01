# Recovery and Archive import review

## Confirmed defects and fixes

- Collection recovery previously did not identify the process owning a running operation. New journals store PID, process creation identity, and a timestamp refreshed on journal writes. Recovery skips a live owner; an inaccessible owner is treated conservatively as live. The timestamp is diagnostic, not a timeout allowing rollback of a live process.
- Failed restoration is persisted as `recovery_failed`, with the preceding recovery stage and error. Settings > Advanced > file recovery exposes Retry, Open backup folder, and Close record (retain backup). Closing stops automatic recovery and releases the pending-operation block without deleting files or backups.
- Archive restore keeps the existing database and shared snapshot safety checks. Retry restores the interrupted stage rather than bypassing those checks.
- Collection journal writes flush and fsync the temporary JSON before replacing the record.
- A new committed Collection operation removes the owned `.rms-backup.rms-redo` files of invalidated Redo records. Retained Undo backups are not removed.
- Archive import builds a normalized-system/full-filename index once. Language tags no longer implicitly join different filenames. Explicitly selected targets and previously user-confirmed links remain valid. Cross-system metadata imports do not fill a target ROM using the source ROM.
- The Archive import preparation UI uses a cancellable background job with per-item progress.

## Scope still open

- Backup automatic retention is now an opt-in Advanced setting. Default is disabled; proposed controls start at 20 operation records and 10 GB per Collection/Archive. Either limit may be zero (unlimited), but both cannot be unlimited while enabled. Changes take effect on the next successful file operation.
- Retention preserves the newest committed Undo per kind, valid Redo, all pending/failed recovery, closed records retained by user choice, related-Collection operations, and externally modified sidecars. Active/failed recovery postpones cleanup for the entire scope. Protected backups may exceed the configured soft limits.
- Automatic cleanup uses cached approximate sizes to avoid walking all backups after every operation. It verifies candidate records and owned sidecars again before deleting. Removal counts/errors/remaining-limit warnings are shown through operation status and logged.
- History state queries now use a rebuildable local `status-index.sqlite`. Original operation JSON remains authoritative. A per-record size/mtime/file-ID check detects normal external changes; legacy or changed records are indexed lazily. Full file maps stay in their operation JSON.
- Backup sizes are cached per record and invalidated on journal updates. The UI labels the total approximate because an external backup deletion does not necessarily update the operation record.
- Archive commits invalidate previous Redo records before removing only owned sidecars whose path and captured file state still match. Externally changed Redo files are retained. Cleanup permission failures are logged without failing the completed operation. Undo database/file backups are retained.
- ROM size/modified-date information in the conflict UI is optional and not added here.
- Existing journals lacking process ownership cannot identify a live process from an older app version.
- Actual NAS restoration and power-loss durability require device validation. fsync of the JSON does not guarantee every copied ROM or backup file has been flushed.

## Validation

- Targeted recovery/Archive/paste tests: 66 passed.
- Additional safety and 2,000-row import/cancellation tests: 6 passed.
- Final Archive recovery/history/wiring regression run: 43 passed (20.90 seconds), including the additional Archive Retry regression.
- Recovery actions are tested through Settings in the browser bridge mock.
- Full backend rerun: 1,475 passed, 1 skipped, 1 xfailed, 42 subtests passed (228.32 seconds). The subsequent Archive history retry regression is covered in the final targeted run.
- Related UI final run: 71 passed (18.7 seconds). An earlier UI run completed assertions but hung while stopping its automatic test server; the final run used an explicitly managed server and exited successfully.
- JavaScript syntax and whitespace checks passed. Logs are recorded under `logs/recovery-*.log`.

## Follow-up index and Archive Redo validation

- Related backend tests: 108 passed (36.73 seconds), including legacy indexing, deleted-index rebuilding, unavailable-index fallback, external record changes, cached-size invalidation, Redo preservation on external changes, and cleanup failure.
- Local synthetic benchmark: 100 operation records, 1,000 file-map entries each, 10 latest-status queries. Raw JSON reading took 1.4476 seconds; indexed reading took 0.1255 seconds (11.53x). This is not a NAS benchmark.
- Follow-up logs: `logs/history-index-*.log`.
- Follow-up related UI: 7 passed (5.3 seconds). Additional Collection cleanup/status-index tests: 36 passed; the final index-only run including corrupt-index fallback: 7 passed.
- Full backend follow-up: 1,485 passed, 1 skipped, 1 xfailed, 42 subtests passed (239.04 seconds). The final index-only rerun also passed after closing failed SQLite connections explicitly.

## Opt-in backup retention validation

- Related backend: 94 passed; retention-only including Archive scope: 16 passed.
- Full backend: 1,503 passed, 1 skipped, 1 xfailed, 42 subtests passed (244.80 seconds).
- Settings/recovery UI: 18 passed (8.3 seconds), including disabled defaults, saving count/size limits, rejecting two unlimited limits, and cleanup/limit-overflow notices.
- Deletion candidates are rechecked against their authoritative record status. Automatic cleanup shares its initial eligibility listing across deletions to avoid repeatedly listing every record.
- Final targeted rerun after that optimization: 54 passed (11.20 seconds).
- Logs: `logs/retention-*.log`. Backups still have no automatic deletion until the user enables the setting. Network/device validation remains separate.

## ROM conflict preview

Collection and Archive replacement previews now show ROM size and modification time on a compact line per side. Metadata-only, new-file and same-path operations omit the comparison. File contents are not read or hashed; unavailable source timestamps remain unknown.

Validation: targeted Python tests 65 passed; conflict UI tests 3 passed; JavaScript syntax and whitespace checks passed. Actual NAS and MTP rendering were not verified.

## Follow-up review: durable Archive events and recovery exits

- Archive writes per-file capture, publication expectation, temporary path, rename and restoration changes to fsynced `events.jsonl`. Full atomic `operation.json` checkpoints remain at stage boundaries. Sequence numbers make replay idempotent if interruption occurs between checkpoint publication and log truncation. Torn final event is ignored; complete corrupt events or sequence gaps block restoration. Existing records without event logs remain readable.
- Every file mutation still follows a durable recovery record. No file contents are hashed by the journal. Per-event fsync latency remains; the change removes growing whole-record serialization and index rewrites per file.
- Archive imports compare full filenames with casefold, preserve the actual target filename, and fill a missing ROM for case-only differences. Language variants remain distinct unless a target was explicitly selected or linked.
- Removed unused `_language_matches` and its obsolete helper tests. Normalization unit tests remain; import behavior is tested via `to_collection`.
- Closed recovery records allow confirmed manual backup deletion but remain excluded from automatic cleanup.
- With automatic cleanup disabled, total backups across both journal roots warn at 20 GiB. No deletion is enabled by default. Size estimates use the existing cached accounting.
- Unknown process ownership offers confirmed manual recovery. Known living owners remain protected. Archive retains file checks and digest CAS. Collection refuses unverifiable destination/index/backup states; this restriction persists on subsequent retries. Other affected Collection locks are acquired before recovery.

Validation: full Python suite at the initial follow-up snapshot: 1518 passed, 1 skipped, 1 xfailed, 42 subtests passed (263.98 s). Additional tests and the final focused run are recorded below. UI settings/history/copy-paste: 42 passed. One initial UI test incorrectly selected the primary button for a danger confirmation; corrected the test to select the confirmation by accessible name and reran all 42 successfully. No product button changes were needed.

Local synthetic timing during concurrent regression runs: 500 records append 1.473 s / rewrite 3.212 s; 1000 append 2.867 s / rewrite 8.838 s; 2000 append 7.201 s / rewrite 29.745 s; 5000 append 7.180 s (rewrite not measured). Event bytes grew from 129172 (500) to 1306673 (5000). These include actual fsync but exclude ROM copying, NAS latency and power-loss validation. Scheduling and filesystem variability prevent treating these timings as an exact scaling model.

Final focused Python suite after all follow-up changes: 86 passed (19.72 s). Includes interrupted copy restored from event replay without final checkpoint, persisted manual-recovery safeguards on retry, Archive manual-owner override rejecting changed live DB, rename replay and backup totals across Collections. JavaScript syntax and git diff whitespace checks passed. Actual NAS, elevated-PID reuse and abrupt power loss remain unverified.
