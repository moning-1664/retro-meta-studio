"""Use one journal for nested Archive edits, including owned-file removal."""
import uuid
import logging
from app.archive.undo import current_transaction
from app.archive import shared_cache

ACTIONS = {
    "archive_edit", "archive_metadata_delete", "archive_set_favorite", "archive_delete",
    "archive_delete_owned", "archive_rom_delete", "archive_media_delete", "archive_media_paste",
    "archive_media_delete_selected", "archive_media_delete_system", "archive_delete_system",
    "archive_choose_version", "archive_set_preferred", "archive_clear_preferred",
    "archive_apply_title_affix", "archive_apply_disc_retag", "archive_cleanup_orphans",
    "archive_rename",
    "_archive_ingest_job",
    "_apply_scraped_archive_media",
}


def execute(api, method, args, kwargs):
    cfg = api._archive_config()
    if current_transaction() or not cfg.get("archiveDir"):
        return method(api, *args, **kwargs)
    values = args[0] if args else kwargs.get("rom_identity_ids", kwargs.get("rom_identity_id"))
    values = values if isinstance(values, (list, tuple)) else [values]
    systems = set()
    if method.__name__ == "_archive_ingest_job":
        systems.update(row["system"] for row in args[1].get_rows(args[2]).values())
        values = []
    for value in values:
        identity = api.archive.get_identity(str(value))
        if identity:
            systems.add(identity["system"])
        elif value:
            systems.add(str(value))
    with api._archive_lifecycle_lock, api.archive._conn.lock:
        shared = shared_cache.snapshot_path(cfg["archiveDir"])
        known = api.registry.get_setting("archive.shared_snapshot_hashes", {}) or {}
        digest = shared_cache.fingerprint(shared) if shared.is_file() else None
        if digest != known.get(cfg["archiveDir"]):
            raise ValueError("공유 Archive가 바뀌었습니다. 새로고침 후 다시 시도하세요.")
        tx = api._archive_journal.begin(uuid.uuid4().hex, api.archive, cfg, systems,
                                        allow_network=True, action=method.__name__)
        try:
            with tx.tracking():
                result = method(api, *args, **kwargs)
                if not result.get("ok") or (result.get("data") or {}).get("failures"):
                    raise ValueError(result.get("error") or "일부 항목을 처리하지 못해 변경을 복구했습니다.")
                published = api._publish_archive_snapshot(cfg)
                if published["status"] != "published":
                    raise ValueError("공유 Archive DB를 게시하지 못했습니다.")
            tx.commit(api.archive)
            result["data"]["undoOperationId"] = tx.data["id"]
            api._thumb_cache.clear()
            return result
        except BaseException:
            try:
                tx.failed(api.archive)
                tx.restore(api.archive)
                api._remember_archive_digest(cfg)
            except Exception as exc:
                api._archive_recovery_error = str(exc)
                logging.getLogger(__name__).exception("Archive rollback blocked operation=%s", tx.data["id"])
            raise
