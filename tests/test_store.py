"""Phase 0 저장소 기반 테스트.

특히 다중 인스턴스(D5) 관련 동작 - 두 인스턴스가 같은 DB에 붙었을 때의 변경 전파와
잠금 - 을 실제로 두 개의 Store 객체를 만들어 검증한다.
"""

import tempfile
import time
import unittest
from pathlib import Path

from app.model.collection import STORAGE_INTERNAL
from app.store.archive import ArchiveStore, RETENTION_LATEST_1, content_hash
from app.store.cache import CacheStore
from app.store.registry import RegistryError, RegistryStore
from app.store.sqlite import Migration, connect, migrate, user_version


class SqliteFoundationTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="rms_sqlite_"))

    def test_migrations_apply_once_and_set_user_version(self):
        migrations = (
            Migration(1, ("CREATE TABLE a (x INTEGER)",)),
            Migration(2, ("CREATE TABLE b (y INTEGER)",)),
        )
        conn = connect(self.dir / "m.db", migrations)
        self.assertEqual(user_version(conn), 2)
        # 두 번째 호출은 아무것도 하지 않아야 한다(테이블 재생성 시도 시 예외가 난다).
        self.assertEqual(migrate(conn, migrations), 2)
        conn.close()

    def test_wal_is_enabled(self):
        conn = connect(self.dir / "w.db")
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(str(mode).lower(), "wal")
        conn.close()

    def test_migration_versions_must_be_contiguous(self):
        with self.assertRaises(ValueError):
            connect(self.dir / "bad.db", (Migration(1, ()), Migration(3, ())))


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="rms_reg_"))
        self.path = self.dir / "registry.db"
        self.store = RegistryStore(self.path, instance_id="inst-a")

    def tearDown(self):
        self.store.close()

    def test_create_collection_makes_internal_storage(self):
        col = self.store.create_collection("Android ES-DE", "es-de", r"E:\ESDE", target="android", arch="arm64")
        self.assertEqual(len(col.storages), 1)
        self.assertEqual(col.storages[0].storage_id, STORAGE_INTERNAL)
        self.assertEqual(col.target, "android")
        # 모르는 값은 추측하지 않고 Unknown(None)으로 남는다.
        self.assertIsNone(col.os)

    def test_system_belongs_to_exactly_one_storage(self):
        col = self.store.create_collection("C", "es-de", "R")
        self.store.add_storage(col.id, "ext-1", kind="external", label="SD", root_path=r"F:\roms")
        self.store.upsert_system(col.id, "PS2", "ext-1")
        self.store.upsert_system(col.id, "NDS", STORAGE_INTERNAL)

        reloaded = self.store.get_collection(col.id)
        self.assertEqual(reloaded.storage_of_system("PS2").storage_id, "ext-1")
        self.assertEqual([s.system for s in reloaded.systems_in(STORAGE_INTERNAL)], ["NDS"])

        # 같은 System을 다시 넣어도 행이 늘지 않고 Storage만 바뀐다.
        self.store.move_system(col.id, "PS2", STORAGE_INTERNAL)
        reloaded = self.store.get_collection(col.id)
        self.assertEqual(len(reloaded.systems), 2)
        self.assertEqual(reloaded.storage_of_system("PS2").storage_id, STORAGE_INTERNAL)

    def test_unknown_storage_is_rejected(self):
        col = self.store.create_collection("C", "es-de", "R")
        with self.assertRaises(RegistryError):
            self.store.upsert_system(col.id, "PS2", "does-not-exist")

    def test_storage_with_systems_cannot_be_removed(self):
        col = self.store.create_collection("C", "es-de", "R")
        self.store.add_storage(col.id, "ext-1", kind="external")
        self.store.upsert_system(col.id, "PS2", "ext-1")
        with self.assertRaises(RegistryError) as ctx:
            self.store.remove_storage(col.id, "ext-1")
        self.assertIn("PS2", str(ctx.exception))

        self.store.move_system(col.id, "PS2", STORAGE_INTERNAL)
        self.store.remove_storage(col.id, "ext-1")
        self.assertEqual(len(self.store.get_collection(col.id).storages), 1)

    def test_internal_storage_cannot_be_removed(self):
        col = self.store.create_collection("C", "es-de", "R")
        with self.assertRaises(RegistryError):
            self.store.remove_storage(col.id, STORAGE_INTERNAL)

    def test_rename_keeps_id_stable(self):
        col = self.store.create_collection("Old", "es-de", "R")
        self.store.update_collection(col.id, name="New")
        self.assertEqual(self.store.get_collection(col.id).name, "New")
        self.assertEqual(self.store.get_collection(col.id).id, col.id)

    def test_frontend_cannot_be_changed_directly(self):
        col = self.store.create_collection("C", "es-de", "R")
        with self.assertRaises(RegistryError):
            self.store.update_collection(col.id, frontend="pegasus")


class MultiInstanceTests(unittest.TestCase):
    """두 인스턴스가 같은 registry.db에 붙은 상황(D5, §9)."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="rms_multi_"))
        self.path = self.dir / "registry.db"
        self.a = RegistryStore(self.path, instance_id="inst-a")
        self.b = RegistryStore(self.path, instance_id="inst-b")

    def tearDown(self):
        self.a.close()
        self.b.close()

    def test_other_instance_sees_changes_but_not_its_own(self):
        seq_b = self.b.latest_change_seq()
        col = self.a.create_collection("Shared", "es-de", "R")

        seen_by_b = self.b.changes_since(seq_b)
        self.assertTrue(seen_by_b, "다른 인스턴스가 만든 변경이 보여야 한다")
        self.assertEqual(seen_by_b[0]["collection_id"], col.id)

        # 자기가 쓴 변경은 기본적으로 걸러진다 - 자기 UI를 자기가 다시 그리지 않도록.
        self.assertEqual(self.a.changes_since(seq_b), [])
        self.assertTrue(self.a.changes_since(seq_b, include_own=True))

    def test_b_reads_collection_written_by_a(self):
        col = self.a.create_collection("Shared", "es-de", "R")
        self.assertIsNotNone(self.b.get_collection(col.id))

    def test_apply_lock_is_exclusive_across_instances(self):
        self.assertTrue(self.a.acquire_lock("apply:c1", kind="apply"))
        self.assertFalse(self.b.acquire_lock("apply:c1", kind="apply"))
        # 소유자는 다시 잡아도 성공한다(재진입).
        self.assertTrue(self.a.acquire_lock("apply:c1"))

        self.a.release_lock("apply:c1")
        self.assertTrue(self.b.acquire_lock("apply:c1"))

    def test_stale_lock_is_taken_over(self):
        self.assertTrue(self.a.acquire_lock("apply:c1"))
        # 죽은 인스턴스를 흉내 - heartbeat가 오래된 락은 빼앗을 수 있어야 한다.
        self.assertFalse(self.b.acquire_lock("apply:c1", ttl_seconds=60))
        time.sleep(0.05)
        self.assertTrue(self.b.acquire_lock("apply:c1", ttl_seconds=0.01))
        self.assertEqual(self.b.lock_owner("apply:c1")["instance_id"], "inst-b")

    def test_release_does_not_steal_others_lock(self):
        self.assertTrue(self.a.acquire_lock("apply:c1"))
        self.b.release_lock("apply:c1")  # 소유자가 아니므로 무시되어야 한다
        self.assertEqual(self.a.lock_owner("apply:c1")["instance_id"], "inst-a")


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="rms_cache_"))
        self.cache = CacheStore.open_for_collection(self.dir, "col-1")

    def tearDown(self):
        self.cache.close()

    def _rows(self):
        return [
            {"filename": "FFX.iso", "title": "Final Fantasy X", "title_norm": "final fantasy x",
             "size": 100, "has_metadata": True, "has_media": True, "storage_id": "ext-1",
             "fields": {"name": "Final Fantasy X", "genre": "RPG"},
             "frontend_raw": {"unknown_tag": "keep-me"},
             "media": [{"media_type": "covers", "rel_path": "covers/FFX.png", "size": 10}]},
            {"filename": "MGS2.iso", "title": "Metal Gear Solid 2", "title_norm": "metal gear solid 2",
             "size": 200, "has_metadata": False, "has_media": False, "storage_id": "ext-1"},
        ]

    def test_replace_system_round_trips_metadata_and_media(self):
        self.cache.replace_system("PS2", self._rows())
        rows = self.cache.query_rows(systems=["PS2"])
        self.assertEqual([r["title"] for r in rows], ["Final Fantasy X", "Metal Gear Solid 2"])

        detail = self.cache.get_row(rows[0]["rom_uid"])
        self.assertEqual(detail["fields"]["genre"], "RPG")
        # Round-trip 보존(§50): 공통 모델로 못 옮기는 값이 그대로 남아 있어야 한다.
        self.assertEqual(detail["frontend_raw"]["unknown_tag"], "keep-me")
        self.assertEqual(detail["media"][0]["media_type"], "covers")

    def test_replace_system_is_atomic_replacement(self):
        self.cache.replace_system("PS2", self._rows())
        self.cache.replace_system("PS2", self._rows()[:1])
        self.assertEqual(self.cache.count_rows(systems=["PS2"]), 1)

    def test_query_supports_search_filter_and_paging(self):
        self.cache.replace_system("PS2", self._rows())
        self.assertEqual(len(self.cache.query_rows(search="metal")), 1)
        self.assertEqual(len(self.cache.query_rows(storage_ids=["ext-1"])), 2)
        self.assertEqual(len(self.cache.query_rows(storage_ids=["internal"])), 0)

        page = self.cache.query_rows(limit=1, offset=1)
        self.assertEqual(len(page), 1)
        self.assertEqual(page[0]["title"], "Metal Gear Solid 2")

    def test_storage_usage_groups_by_storage(self):
        self.cache.set_system_stats("PS2", "ext-1", rom_count=2, rom_bytes=300, media_bytes=50)
        self.cache.set_system_stats("NDS", "internal", rom_count=1, rom_bytes=10, media_bytes=5)
        self.assertEqual(self.cache.storage_usage(), {"ext-1": 350, "internal": 15})

    def test_reset_clears_everything(self):
        self.cache.replace_system("PS2", self._rows())
        self.cache.set_dir_sig("E:/roms/PS2", 123)
        self.cache.reset()
        self.assertEqual(self.cache.count_rows(), 0)
        self.assertIsNone(self.cache.get_dir_sig("E:/roms/PS2"))


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="rms_arc_"))
        self.archive = ArchiveStore(self.dir / "archive.db")
        self.game = self.archive.ensure_game("Final Fantasy X", "final fantasy x")
        self.rid = self.archive.ensure_rom_identity(self.game, "PS2", "final fantasy x", region="USA")

    def tearDown(self):
        self.archive.close()

    def test_identical_content_does_not_create_revision(self):
        fields = {"name": "Final Fantasy X", "genre": "RPG"}
        rev1, created1 = self.archive.put_record(self.rid, "col-a", fields)
        rev2, created2 = self.archive.put_record(self.rid, "col-a", dict(fields))
        self.assertEqual((rev1, created1), (1, True))
        self.assertEqual((rev2, created2), (1, False))
        self.assertEqual(len(self.archive.revisions_of(self.rid, "col-a")), 1)

    def test_changed_content_creates_new_revision(self):
        self.archive.put_record(self.rid, "col-a", {"name": "A"})
        rev, created = self.archive.put_record(self.rid, "col-a", {"name": "B"})
        self.assertEqual((rev, created), (2, True))
        self.assertEqual(self.archive.latest_record(self.rid, "col-a")["fields"]["name"], "B")

    def test_retention_limits_history(self):
        for i in range(5):
            self.archive.put_record(self.rid, "col-a", {"name": f"v{i}"}, retention=RETENTION_LATEST_1)
        self.assertEqual(len(self.archive.revisions_of(self.rid, "col-a")), 1)

    def test_sources_tracked_by_collection_id(self):
        self.archive.put_record(self.rid, "col-a", {"name": "from A"})
        self.archive.put_record(self.rid, "col-b", {"name": "from B"})
        sources = {s["source_collection_id"]: s["fields"]["name"] for s in self.archive.sources_of(self.rid)}
        self.assertEqual(sources, {"col-a": "from A", "col-b": "from B"})

    def test_content_hash_ignores_key_order(self):
        self.assertEqual(content_hash({"a": 1, "b": 2}), content_hash({"b": 2, "a": 1}))

    def test_media_ref_stores_path_only(self):
        self.archive.put_media_ref(self.rid, "covers", "col-a", r"E:\media\ffx.png", size=42)
        refs = self.archive.media_refs(self.rid)
        self.assertEqual(refs[0]["abs_path"], r"E:\media\ffx.png")
        self.assertEqual(refs[0]["size"], 42)


if __name__ == "__main__":
    unittest.main()
