"""Archive Revision 정책 실증 (Phase 7.22, `docs/ARCHIVE_REVISION_POLICY.md` TC-A1~A5).

**코드를 먼저 추적했다.** `app/store/archive.py`의 실제 구현은 이렇다.

    content_hash(fields, frontend_raw)  <- Metadata(+frontend_raw)만 해싱한다
    archive_records                     <- (identity, source) 단위로 revision 관리,
                                            content_hash가 같으면 새 행을 만들지 않는다
    archive_media / archive_rom_sources <- `ON CONFLICT ... DO UPDATE` = **그 자리에서
                                            덮어쓴다.** revision 개념이 아예 없다.

정책 문서 §6("Media Revision")과 §7·§17(`media_fingerprint`)은 Media도 Metadata와
같은 수준으로 revision을 갖기를 요구하지만, **실제 구현은 Media를 revision하지
않는다** - `(identity, media_type, source)`당 슬롯 하나뿐이고 매번 최신 값으로
덮어쓴다. 이 파일의 TC-A3가 바로 그 간극을 가리킨다.

각 TC는 Archive DB(`api.archive`)를 직접 열어 revision 개수·content_hash·
preferred_revisions까지 확인하고, Archive → Collection 뒤에는 실제 파일과
gamelist.xml까지 다시 읽는다.
"""

import unittest
import xml.etree.ElementTree as ET

from bridge.api import Api
from tests.fixtures import build_custom_esde_tree, scan, temp_root, wait_idle, write_file


class ArchiveRevisionCase(unittest.TestCase):
    """Source Collection 하나에서 반복해서 Export하며 Revision 이력을 쌓는 공통 준비."""

    def setUp(self):
        self.dir = temp_root("rms_arev_")
        self.root = build_custom_esde_tree(self.dir / "src", "ps2", [
            {"filename": "FFX.iso", "title": "Final Fantasy X", "genre": "RPG",
             "developer": "Square"},
        ])
        write_file(self.root / "downloaded_media" / "ps2" / "covers" / "FFX.png", b"cover-A" * 10)

        self.api = Api(registry_path=self.dir / "registry.db", cache_dir=self.dir / "cache")
        self.addCleanup(self.api.close)
        self.cid = self.api.create_collection("Src", "es-de", str(self.root))["data"]["id"]
        self._rescan()

    def _rescan(self):
        job = self.api.start_scan(self.cid, True)["data"]["jobId"]
        wait_idle(self.api)
        return job

    def _uid(self, filename="FFX.iso"):
        return next(r["romUid"] for r in self.api.list_rows(self.cid, limit=50)["data"]["rows"]
                   if r["file"] == filename)

    def _identity_id(self):
        rows = self.api.archive_rows(limit=50)["data"]["rows"]
        return rows[0]["romIdentityId"]

    def _export(self):
        return self.api.archive_ingest(self.cid, [self._uid()])["data"]

    def _revisions(self, identity_id=None):
        """Archive DB를 직접 연다 - `sources_of()`가 아니라 **이 출처의 전체 이력**을
        보는 `revisions_of()`를 쓴다. sources_of는 출처당 최신 하나만 주므로
        Revision 개수를 세는 데는 쓸 수 없다."""
        identity_id = identity_id or self._identity_id()
        return self.api.archive.revisions_of(identity_id, self.cid)


# ======================================================================
# TC-A1 — 동일 Export 중복 방지
# ======================================================================
class TCA1_NoDuplicateOnIdenticalExport(ArchiveRevisionCase):
    def test_the_first_export_creates_one_revision(self):
        result = self._export()
        self.assertEqual(result["revised"], 1)
        self.assertEqual(len(self._revisions()), 1)

    def test_exporting_the_identical_state_again_creates_nothing(self):
        self._export()
        first = self._revisions()[0]

        result = self._export()
        self.assertEqual(result["revised"], 0, "변경이 없는데 새 Revision을 셌다")
        self.assertEqual(result["unchanged"], 1)

        revisions = self._revisions()
        self.assertEqual(len(revisions), 1, "동일 상태인데 Revision이 늘었다")
        self.assertEqual(revisions[0]["record_id"], first["record_id"],
                         "새 행을 만들지 않았다면 record_id도 그대로여야 한다")

    def test_the_fingerprint_is_identical_across_identical_exports(self):
        self._export()
        h1 = self._revisions()[0]["content_hash"]
        self._export()
        h2 = self._revisions()[0]["content_hash"]
        self.assertEqual(h1, h2)

    def test_three_identical_exports_still_leave_one_revision(self):
        for _ in range(3):
            self._export()
        self.assertEqual(len(self._revisions()), 1)

    def test_export_event_count_is_not_confused_with_revision_count(self):
        """§18: Export 횟수와 Revision 개수는 다른 개념이다."""
        for _ in range(3):
            result = self._export()
        # `ingested`는 Export를 부른 횟수만큼 항상 1이다(Export Event) - Revision이
        # 늘지 않아도 "내가 이번에 이 항목을 내보냈다"는 사실 자체는 매번 참이다.
        self.assertEqual(result["ingested"], 1)
        self.assertEqual(len(self._revisions()), 1, "Revision은 상태가 바뀔 때만 는다")


# ======================================================================
# TC-A2 — Metadata만 변경
# ======================================================================
class TCA2_MetadataOnlyChange(ArchiveRevisionCase):
    def _edit_source_genre(self, genre):
        """Collection 파일의 genre를 바꾸고 다시 스캔해 Cache에 반영한다."""
        self.api.save_fields(self.cid, self._uid(), {"genre": genre})
        self._rescan()

    def test_changing_one_field_creates_a_new_revision(self):
        self._export()
        r1 = self._revisions()[0]

        self._edit_source_genre("Action RPG")
        result = self._export()

        self.assertEqual(result["revised"], 1, "필드 하나가 바뀌었는데 Revision을 안 만들었다")
        revisions = self._revisions()
        self.assertEqual(len(revisions), 2)
        self.assertNotEqual(revisions[0]["record_id"], r1["record_id"])

    def test_the_old_revision_is_untouched(self):
        self._export()
        r1_before = dict(self._revisions()[0])

        self._edit_source_genre("Action RPG")
        self._export()

        revisions = {r["record_id"]: r for r in self._revisions()}
        r1_after = revisions[r1_before["record_id"]]
        self.assertEqual(r1_after["fields"]["genre"], "RPG",
                         "기존 Revision의 내용이 바뀌었다 - immutable이 깨졌다")
        self.assertEqual(r1_after["content_hash"], r1_before["content_hash"])

    def test_the_new_revision_carries_the_changed_field(self):
        self._export()
        self._edit_source_genre("Action RPG")
        self._export()

        latest = max(self._revisions(), key=lambda r: r["revision"])
        self.assertEqual(latest["fields"]["genre"], "Action RPG")

    def test_media_state_is_unaffected_by_a_metadata_only_change(self):
        self._export()
        self._edit_source_genre("Action RPG")
        self._export()

        media = self.api.archive.media_refs(self._identity_id())
        covers = next(m for m in media if m["media_type"] == "covers")
        self.assertEqual(covers["size"], len(b"cover-A" * 10))


# ======================================================================
# TC-A3 — Media만 변경 (**정책과 실제 구현이 갈리는 지점**)
# ======================================================================
class TCA3_MediaOnlyChange(ArchiveRevisionCase):
    def _replace_cover(self, data):
        write_file(self.root / "downloaded_media" / "ps2" / "covers" / "FFX.png", data)
        self._rescan()

    def test_the_media_reference_is_updated_after_re_export(self):
        """이건 통과한다 - 문제는 그 갱신 방식이다(아래 테스트들)."""
        self._export()
        self._replace_cover(b"cover-B" * 10)
        self._export()

        media = self.api.archive.media_refs(self._identity_id())
        covers = next(m for m in media if m["media_type"] == "covers")
        self.assertEqual(covers["size"], len(b"cover-B" * 10))

    def test_a_media_only_change_does_not_create_a_new_metadata_revision(self):
        """**IMPLEMENTATION BUG.** 정책 §6/§39 요약: "Media가 다르면 Revision을
        분리한다." 그런데 `content_hash`는 fields+frontend_raw만 해싱하므로,
        Metadata가 그대로면 Media가 바뀌어도 `put_record`는 같은 fingerprint로
        보고 새 행을 만들지 않는다. 이 테스트는 **정책 위반을 실증하는 것이 목적**이라
        실패를 "고쳐야 할 결과"로 남겨 둔다 - assertion을 완화해 통과시키지 않는다.
        """
        self._export()
        before = len(self._revisions())

        self._replace_cover(b"cover-B" * 10)
        result = self._export()

        # 정책대로라면 여기서 새 Revision이 생겨야 한다(revised == 1).
        # 실제로는 Metadata가 그대로라 content_hash가 같아 revised == 0이다.
        self.assertEqual(result["revised"], 1,
                         "POLICY VIOLATION: Media만 바뀌었는데 Revision이 생기지 않았다 "
                         "(content_hash가 Metadata만 보기 때문)")
        self.assertEqual(len(self._revisions()), before + 1)

    def test_the_old_media_reference_is_not_recoverable_after_overwrite(self):
        """**IMPLEMENTATION BUG.** `archive_media`는 `(identity, type, source)`당
        슬롯이 하나뿐이라 `ON CONFLICT DO UPDATE`로 그 자리에서 덮어쓴다. cover-A를
        가리키던 기록 자체가 사라지므로, "Revision A는 cover-A를 그대로 유지한다"는
        정책(§6, Invariant 1)을 지킬 방법이 없다 - Revision이라는 개념 자체가 Media에는
        없다.
        """
        self._export()
        self._replace_cover(b"cover-B" * 10)
        self._export()

        media = self.api.archive.media_refs(self._identity_id())
        self.assertEqual(len(media), 1, "media_type당 기록이 하나뿐이다 - 이력이 없다")
        self.assertEqual(media[0]["size"], len(b"cover-B" * 10),
                         "cover-A를 가리키던 이전 기록이 완전히 사라졌다")


# ======================================================================
# TC-A4 — Preferred Revision 우선순위
# ======================================================================
class TCA4_PreferredPriority(ArchiveRevisionCase):
    def setUp(self):
        super().setUp()
        # R1: 최초 상태
        self._export()
        self.r1 = self._revisions()[0]
        # R2: developer만 바꾼다
        self.api.save_fields(self.cid, self._uid(), {"developer": "Square Enix"})
        self._rescan()
        self._export()
        self.r2 = max(self._revisions(), key=lambda r: r["revision"])
        # R3: description을 더한다 - 이게 Latest가 된다
        self.api.save_fields(self.cid, self._uid(), {"desc": "스피라를 여행하는 이야기"})
        self._rescan()
        self._export()
        self.r3 = max(self._revisions(), key=lambda r: r["revision"])

    def test_there_really_are_three_distinct_revisions(self):
        self.assertEqual(len(self._revisions()), 3)
        self.assertEqual({self.r1["record_id"], self.r2["record_id"], self.r3["record_id"]},
                         {r["record_id"] for r in self._revisions()})

    def test_without_a_preferred_pick_latest_wins(self):
        detail = self.api.archive_detail(self._identity_id())["data"]
        self.assertEqual(detail["fields"].get("developer"), "Square Enix")
        self.assertEqual(detail["fields"].get("desc"), "스피라를 여행하는 이야기")

    def test_setting_r2_as_preferred_overrides_latest(self):
        self.api.archive_set_preferred(self._identity_id(), self.r2["record_id"])
        detail = self.api.archive_detail(self._identity_id())["data"]
        self.assertEqual(detail["preferredRecordId"], self.r2["record_id"])
        self.assertEqual(detail["fields"], self.r2["fields"],
                         "Preferred를 지정했는데 그 Revision 전체가 쓰이지 않았다")

    def test_send_to_collection_uses_the_preferred_revision_not_latest(self):
        """실제 filesystem까지 확인한다 - Preferred가 Latest보다 우선해야 한다."""
        self.api.archive_set_preferred(self._identity_id(), self.r2["record_id"])

        dst_root = self.dir / "dst"
        build_custom_esde_tree(dst_root, "ps2", [])
        did = self.api.create_collection("Dst", "es-de", str(dst_root))["data"]["id"]
        wait_idle(self.api)
        self._wait_scan(did)

        r = self.api.archive_to_collection(did, [self._identity_id()])
        self.assertTrue(r["ok"], r.get("error"))
        # 대상에 ROM이 없었으므로 메타데이터가 바로 반영되지 않고 Plan에 올라간다
        # (§41 - 파일이 옮겨져야 하므로). Apply까지 해야 실제로 파일과 gamelist가 생긴다.
        job = self.api.start_apply(did)["data"]["jobId"]
        wait_idle(self.api)

        gl = ET.parse(dst_root / "gamelists" / "ps2" / "gamelist.xml").getroot()
        game = gl.find("game")
        self.assertIsNotNone(game, "Apply했는데 gamelist에 항목이 없다")
        self.assertEqual(game.findtext("developer"), "Square Enix",
                         "R2(Preferred)의 developer가 반영돼야 한다")
        # R2에는 description이 없다(R3에서 추가됐다) - Latest를 억지로 섞으면 안 된다.
        self.assertIn((game.findtext("desc") or ""), ("", None),
                      "R2에 없는 필드가 채워졌다 - Preferred를 무시하고 Latest가 섞였다")

    def _wait_scan(self, cid):
        job = self.api.start_scan(cid, True)["data"]["jobId"]
        wait_idle(self.api)
        return job


# ======================================================================
# TC-A5 — Preferred 해제 후 Latest fallback
# ======================================================================
class TCA5_ClearPreferredFallsBackToLatest(ArchiveRevisionCase):
    def setUp(self):
        super().setUp()
        self._export()
        self.r1 = self._revisions()[0]
        self.api.save_fields(self.cid, self._uid(), {"developer": "Square Enix"})
        self._rescan()
        self._export()
        self.r2 = max(self._revisions(), key=lambda r: r["revision"])

        self.api.archive_set_preferred(self._identity_id(), self.r1["record_id"])

    def test_preferred_is_honoured_before_clearing(self):
        # fixture의 최초 developer는 "Square"다(R2에서 "Square Enix"로 바뀐다).
        detail = self.api.archive_detail(self._identity_id())["data"]
        self.assertEqual(detail["fields"].get("developer"), "Square",
                         "R1(Preferred)의 원래 developer가 나와야 한다")

    def test_clearing_preferred_falls_back_to_latest(self):
        r = self.api.archive_clear_preferred(self._identity_id())
        self.assertTrue(r["ok"])

        detail = self.api.archive_detail(self._identity_id())["data"]
        self.assertIsNone(detail["preferredRecordId"])
        self.assertEqual(detail["fields"].get("developer"), "Square Enix",
                         "Preferred를 지웠는데 Latest(R2)로 돌아오지 않았다")

    def test_the_filesystem_reflects_the_fallback_after_clearing(self):
        self.api.archive_clear_preferred(self._identity_id())

        dst_root = self.dir / "dst2"
        build_custom_esde_tree(dst_root, "ps2", [])
        did = self.api.create_collection("Dst2", "es-de", str(dst_root))["data"]["id"]
        job = self.api.start_scan(did, True)["data"]["jobId"]
        wait_idle(self.api)

        r = self.api.archive_to_collection(did, [self._identity_id()])
        self.assertTrue(r["ok"], r.get("error"))
        self.api.start_apply(did)
        wait_idle(self.api)

        gl = ET.parse(dst_root / "gamelists" / "ps2" / "gamelist.xml").getroot()
        game = gl.find("game")
        self.assertIsNotNone(game, "Apply했는데 gamelist에 항목이 없다")
        self.assertEqual(game.findtext("developer"), "Square Enix")


if __name__ == "__main__":
    unittest.main()
