"""Workspace 서비스 테스트 - Registry/Cache/Adapter/Provider가 실제로 맞물리는지."""

import tempfile
import unittest
from pathlib import Path

from app.model.collection import STORAGE_INTERNAL
from app.store.registry import RegistryStore
from app.workspace import Workspace, WorkspaceError
from tests.test_es_de_adapter import build_esde_tree


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="rms_ws_"))
        self.root = build_esde_tree(self.dir / "esde")
        self.registry = RegistryStore(self.dir / "registry.db", instance_id="inst-a")
        self.ws = Workspace(self.registry, cache_dir=self.dir / "cache")

    def tearDown(self):
        self.ws.close()
        self.registry.close()

    def test_create_registers_detected_systems_on_internal(self):
        col = self.ws.create_collection("My ES-DE", "es-de", self.root, target="windows")
        self.assertEqual([s.system for s in col.systems], ["ps2"])
        self.assertEqual(col.storage_of_system("ps2").storage_id, STORAGE_INTERNAL)

    def test_create_rejects_a_path_that_is_not_the_frontend(self):
        empty = self.dir / "empty"
        empty.mkdir()
        with self.assertRaises(WorkspaceError):
            self.ws.create_collection("Nope", "es-de", empty)

    def test_scan_then_query_rows(self):
        col = self.ws.create_collection("My ES-DE", "es-de", self.root)
        result = self.ws.scan(col.id)
        self.assertEqual(result["roms"], 2)

        rows = self.ws.rows(col.id, search="final")
        self.assertEqual([r["title"] for r in rows], ["Final Fantasy X"])
        self.assertEqual(self.ws.row_count(col.id), 3)
        self.assertEqual(self.ws.storage_usage(col.id), {STORAGE_INTERNAL: 3110})

    def test_scan_notifies_other_instances(self):
        other = RegistryStore(self.dir / "registry.db", instance_id="inst-b")
        try:
            col = self.ws.create_collection("My ES-DE", "es-de", self.root)
            seq = other.latest_change_seq()
            self.ws.scan(col.id)
            kinds = [c["kind"] for c in other.changes_since(seq)]
            self.assertIn("collection.scan", kinds)
        finally:
            other.close()

    def test_closing_keeps_cache_for_a_fast_reopen(self):
        col = self.ws.create_collection("My ES-DE", "es-de", self.root)
        self.ws.scan(col.id)
        self.ws.close_collection(col.id)
        self.assertEqual(self.ws.open_ids, [])

        # 다시 열면 캐시가 그대로 있어야 한다 - 이게 Collection 재오픈이 빠른 이유다.
        self.assertEqual(self.ws.row_count(col.id), 3)

    def test_open_limit_is_ten(self):
        for i in range(10):
            col = self.registry.create_collection(f"C{i}", "es-de", self.root)
            self.ws.open(col.id)
        eleventh = self.registry.create_collection("C10", "es-de", self.root)
        with self.assertRaises(WorkspaceError) as ctx:
            self.ws.open(eleventh.id)
        self.assertIn("10개", str(ctx.exception))

        # 하나 닫으면 다시 열 수 있다.
        self.ws.close_collection(self.ws.open_ids[0])
        self.ws.open(eleventh.id)


if __name__ == "__main__":
    unittest.main()
