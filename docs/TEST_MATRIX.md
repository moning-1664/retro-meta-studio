# Test Matrix

지시서의 TC를 실제 저장소 상태에 대입한 표다. **`NOT TESTED`를 `PASS`로 적지 않는다.**

- `PASS` — 자동 테스트로 실제 검증됨(파일/DB 결과까지 확인)
- `NOT TESTED` — 아직 검증하지 못함
- `LIMIT` — 알고 있으며 의도적으로 허용하는 한계

Level: **U**nit / **I**ntegration(실제 filesystem·DB) / **G**UI / **E2E** / **D**ata-safety

---

## 1. Partial Media Scan (P0-A)

| TC | Level | 테스트 | 상태 |
|---|---|---|---|
| covers만 스캔 → videos/wheel 유지 | I·D | `PartialScanKeepsUnscannedMediaTests.test_scanning_covers_only_keeps_the_other_types` | PASS |
| 스캔한 타입은 실제로 갱신 | I | `.test_the_scanned_type_is_actually_refreshed` | PASS |
| 스캔한 타입 안에서 삭제된 파일은 사라짐 | I | `.test_a_removed_file_of_a_scanned_type_does_disappear` | PASS |
| full → partial → full 동일 결과 | I | `.test_full_scan_after_partial_scan_matches_a_plain_full_scan` | PASS |
| 대상 타입에 파일 0개여도 나머지 유지 | I | `.test_a_partial_scan_of_a_type_with_no_files_keeps_the_rest` | PASS |
| 부분 스캔 **도중 예외** 시 캐시 보존 | I | — | NOT TESTED |

## 2. Plan / Conflict Safety

| TC | Level | 테스트 | 상태 |
|---|---|---|---|
| PLAN-SAFETY-001 Plan 당시 target 없음 → 이후 생성 | D | `TargetAppearingAfterThePlanTests.test_a_target_created_after_the_plan_is_not_overwritten` | PASS |
| 〃 성공으로 보고하지 않음 | D | `.test_the_entry_does_not_claim_success` | PASS |
| 승인은 **파일 단위**(커버 승인이 ROM에 번지지 않음) | D | `ApprovalIsPerFileTests.test_a_rom_that_appeared_later_is_not_overwritten` | PASS |
| 승인한 것은 그대로 실행 | D | `.test_the_approved_cover_is_still_overwritten` | PASS |
| PLAN-SAFETY-002 target 교체 → 중단 | D | `OverwriteTargetIsRecheckedTests.test_a_replaced_target_stops_the_apply` | PASS |
| PLAN-SAFETY-003 변화 없음 → 정상 overwrite | D | `.test_an_untouched_target_applies_normally` | PASS |
| PLAN-SAFETY-004 source 변경 → 중단 | D | `SourceChangeDetectionTests.test_a_resized_source_is_rejected` | PASS |
| PLAN-SAFETY-005 동일 크기 source 교체 | D | `.test_a_same_size_source_replacement_is_rejected` | PASS |
| target 삭제됨 → stale | D | `OverwriteTargetIsRecheckedTests.test_a_deleted_target_is_also_stale` | PASS |
| 검증 우회해도 Apply가 막음 | D | `.test_the_stale_target_is_not_overwritten_even_if_apply_runs` | PASS |
| **동일 tick 제자리 덮어쓰기** | D | `.test_the_known_limit_is_written_down` | **LIMIT** |

## 3. Media Snapshot

| TC | Level | 테스트 | 상태 |
|---|---|---|---|
| MEDIA-SAFETY-001 원본 커버 교체 감지 | D | `SourceMediaSnapshotTests.test_a_replaced_cover_is_detected` | PASS |
| MEDIA-SAFETY-002 동일 크기 커버 교체 | D | `.test_a_same_size_cover_replacement_is_detected` | PASS |
| 안 바뀐 media는 통과 | D | `.test_an_untouched_media_is_fine` | PASS |

**정책**: 원본 media가 **없어진 것**은 빼고 진행(D3), **바뀐 것**은 항목 전체를 멈춘다.
사용자가 고르지 않은 그림을 조용히 복사하지 않기 위해서다.

## 4. Delete Safety

| TC | Level | 테스트 | 상태 |
|---|---|---|---|
| DELETE-001 media 교체 후 삭제 → 중단 | D | `DeleteChecksMediaTests.test_a_changed_cover_stops_the_delete` | PASS |
| DELETE-002 동일 크기 media 교체 | D | `.test_a_same_size_cover_replacement_is_detected` | PASS |
| media 이미 사라짐 → 막지 않음 | D | `.test_a_cover_that_vanished_does_not_block_the_delete` | PASS |
| ROM 변경 후 삭제 → 중단 | D | `validator._validate_delete` / `test_plan.py` | PASS |
| 정상 delete | D | `.test_an_untouched_delete_is_valid` | PASS |

## 5. Overwrite Rollback

| TC | Level | 테스트 | 상태 |
|---|---|---|---|
| ROLLBACK-001 정상 완료, backup 없음 | D | `OverwriteRollbackRestoresOriginalTests.test_a_successful_overwrite_leaves_the_new_file_and_no_backup` | PASS |
| ROLLBACK-002 metadata 실패 → **원본 내용 복구** | D | `.test_a_failure_after_the_copy_restores_the_original` | PASS |
| 〃 상태가 완료가 아님 | D | `.test_the_entry_is_reported_as_failed_not_applied` | PASS |
| ROLLBACK-003 copy 실패 → 원본 유지 | D | `.test_a_copy_failure_leaves_the_original_intact` | PASS |
| ROLLBACK-004 backup 실패 → 시작 안 함 | D | `applier._backup_replaced` | PASS |
| ROLLBACK-005 restore 실패 → PARTIAL | D | `RestoreFailureIsNotPlainFailureTests.test_a_failed_restore_is_reported_as_partial` | PASS |
| 실패 후 `.rms-backup` 잔여물 없음 | D | `.test_no_backup_file_is_left_behind_after_a_failure` | PASS |

## 6. Transaction Semantics

| 실패 지점 | 파일 상태 | backup | 최종 status |
|---|---|---|---|
| 승인 없는 target 발견 | 아무것도 안 함 | 없음 | FAILED |
| backup 실패 | 아무것도 안 함 | 되돌림 | FAILED |
| ROM/media copy 실패 | 새 파일 삭제 + 원본 복구 | 삭제 | FAILED |
| gamelist 쓰기 실패 | 새 파일 삭제 + 원본 복구 | 삭제 | FAILED |
| 〃 + 복구 실패 | 원본 없음 | 남음 | **PARTIAL** |
| media 링크 쓰기 실패 | 파일은 그대로 둠 | 삭제 | **PARTIAL** |

**PARTIAL = 사용자가 손봐야 한다.** 정상 완료처럼 보이지 않는다.

## 7. Capacity

| TC | Level | 테스트 | 상태 |
|---|---|---|---|
| 실제 여유 공간보다 큰 계획 → 차단 | I | `CapacityUsesActualFreeSpaceTests.test_a_plan_larger_than_the_free_space_is_blocked` | PASS |
| Cache가 거짓말해도 실제 기준 판정 | I | `.test_a_small_plan_is_not_blocked_by_a_stale_cache` | PASS |
| UI 숫자 의미 구분 | G | — | NOT TESTED |

`planBytes`(Cache 기반 예상) 와 차단 판정(`free_bytes` 기반)은 **서로 다른 값**이다.

## 8. Storage

| TC | Level | 테스트 | 상태 |
|---|---|---|---|
| STORAGE-003 미등록 System이 External | I | `NewSystemStorageTests.test_a_new_system_on_the_external_storage_is_external` | PASS |
| Internal 판정 | I | `.test_a_new_system_inside_the_collection_root_is_internal` | PASS |
| 기존 배치를 스캔이 덮지 않음 | I | `.test_an_existing_mapping_is_not_overwritten_by_detection` | PASS |
| STORAGE-004 중첩 root longest-match | U | `StoragePathBoundaryTests.test_the_longest_matching_root_still_wins` | PASS |
| STORAGE-005 `D:\ROM` vs `D:\ROM_BACKUP` | U | `.test_a_sibling_with_the_same_prefix_does_not_match` | PASS |

## 9. Phase 8 Provider Regression

| TC | Level | 테스트 | 상태 |
|---|---|---|---|
| PROVIDER-001 4개 Adapter 왕복 | I | `*RoundTripTests.test_what_we_write_comes_back` | PASS |
| 한 필드만 고쳐도 나머지 보존 | I | `.test_editing_one_field_leaves_the_others_alone` | PASS |
| 두 번 저장해도 안정 | I | `.test_a_second_save_is_stable` | PASS |
| PROVIDER-002 unknown 필드 보존(ES-DE) | I | `UnknownFieldsSurviveTests.test_es_de_keeps_unknown_tags` | PASS |
| 〃 (Pegasus) | I | `.test_pegasus_keeps_unknown_keys` | PASS |
| PROVIDER-003 write 실패가 디스크에 안 닿음 | I | `.test_a_dead_provider_writes_nothing_to_disk` | PASS |
| 〃 read 실패가 crash 아님 | I | `.test_a_dead_provider_reads_as_empty_not_as_a_crash` | PASS |
| Adapter 누락 방지 | U | `EveryAdapterIsCoveredTests` | PASS |
| Adapter가 파일을 직접 안 엶(정적) | U | `NoDirectFileAccessInAdaptersTests` | PASS |

## 10. Frontend Conversion

| TC | Level | 테스트 | 상태 |
|---|---|---|---|
| FMT-002 ES-DE → Pegasus | I | `test_convert_integration` 다수 | PASS |
| FMT-003 Pegasus → ES-DE | I | `test_es_de_to_pegasus_and_back` | PASS |
| FMT-004 **3회 왕복 손실 비누적** | I | `test_repeated_round_trips_do_not_keep_losing_fields` | PASS |
| 〃 media도 3회 왕복 생존 | I | `test_media_also_survives_repeated_round_trips` | PASS |
| ES-DE ↔ EmulationStation | I | `test_es_de_to_emulationstation_and_back` | PASS |
| LaunchBox 제목 기준 media | I | `test_launchbox_apply_places_media_and_reads_it_back` | PASS |

### Metadata Loss Matrix

| Field | ES-DE | Pegasus | LaunchBox | EmulationStation |
|---|---|---|---|---|
| name / desc / genre | Y | Y | Y | Y |
| developer / publisher | Y | Y | Y | Y |
| releasedate / players / rating | Y | Y | Y | Y |
| **region** | Y | **N** | Y | Y |
| 3dboxes media | Y | — | — | **N** |
| frontend_raw | 자기 것만 | 자기 것만 | 자기 것만 | 자기 것만 |

`supported_fields` / `AdapterContractTests`가 이 표를 코드로 강제한다. **Pegasus 경유
시 region 소실은 의도된 것**이며 Convert 미리보기가 사전에 알린다
(`test_preview_matches_what_actually_happens`).

## 11. 실제 ES-DE 데이터

| TC | 상태 |
|---|---|
| 27 gamelist / 1,558 게임 태그 단위 차이 0 | PASS |
| 14,282개 값 단위 차이 0 | PASS |
| 원본 `gamelists/` sha256 전후 동일 | PASS |
| alternativeEmulator 보존 | PASS (`WriteBackPreservesTheFileTests`) |
| unescaped `&` 복구 | PASS |
| malformed 다중 루트 XML | PASS |
| rating 형식 보존 | PASS |
| 없던 태그 생성 안 함 | PASS |
| 중복 media type | PASS |

**원본은 읽기 전용.** 검증 스크립트가 전후 sha256으로 증명한다.

## 12. 아직 검증하지 못한 것 (NOT TESTED)

| 영역 | TC | 왜 아직인가 |
|---|---|---|
| Cache ↔ 외부 filesystem | CACHE-EXT-001~004 (외부 추가/삭제/rename 후 Refresh) | 스캔 경로는 있으나 "외부 변경 → Refresh → 일치" 전용 TC 없음 |
| Collection Load | COL-001~006 (metadata only / partial media / 깨진 gamelist) | 일부는 기존 테스트에 흩어져 있으나 매트릭스로 정리되지 않음 |
| Archive | ARCHIVE-002~004 (동일 game 충돌 시 current 결정 규칙) | 정책은 `docs/ARCHIVE_REVISION_POLICY.md`로 확정되고 Phase A(+일부 C)가 구현됨(커밋 `b9b92eb`) - VALUE/ABSENT/CLEARED 구분과 field-level BestEffort Import(정책 §10-12, Phase D)는 메타데이터 편집 UI까지 건드리는 별도 작업이라 미착수. TC 자체도 아직 매트릭스로 정리되지 않음 |
| Collection → Collection | CC-001~003 (Exact/Similar/Unrelated 붙여넣기) | Match 단위 테스트는 있으나 붙여넣기 workflow TC 없음 |
| Identity | ID-001~005 (region/system/한글 정규화) | `test_match.py`가 일부 덮으나 매트릭스 미정리 |
| Media | MEDIA-001~005 (전 타입, preview, drag 교체) | GUI 상호작용 |
| Plan GUI | GUI-PLAN-001~007 (drag, 100개 선택, Delete 키) | GUI 상호작용 |
| Cross-App | MULTI-001~003 (두 인스턴스 동시 작업) | 실제 앱 2개 실행 필요 |
| Cancel Safety | 모든 destructive 작업의 Cancel 경로 | GUI 상호작용 |
| Restart Recovery | REC-001~002 | 앱 재시작 필요 |
| E2E-01~10 | 전체 사용자 여정 | 현재 Playwright는 **목업 모드**라 실제 filesystem에 닿지 않음 |

> **현재 Playwright 62개는 목업 API 위에서 도는 UI 테스트다.** 화면 로직은 검증하지만
> "GUI 성공 메시지 = 실제 파일 결과"는 **검증하지 않는다.** 그 연결은 위 E2E 항목이며
> 아직 NOT TESTED다.
