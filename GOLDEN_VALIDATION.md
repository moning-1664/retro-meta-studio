# Golden Validation — Native Media Export Worker

이 문서는 "Media Export를 네이티브 워커로 위임" 기능(PR #7,
`claude/native-media-export-worker`)이 실제로 AhnLab M1875 없이 완료됨을
확인한 **실측 시나리오와 그 재현 방법**을 기록한다. 이 파일이 있는 이유는
향후 이 경로(`import_engine.py::_copy_media_to_masterdb`,
`media_copy_worker.py`, `native/media_copy_worker.c`)를 수정할 때, 단위
테스트만으로는 잡을 수 없는 회귀(패키징된 EXE가 실제로 안랩에 걸리는지)
를 같은 방법으로 재확인할 수 있게 하기 위함이다.

## 확정된 결과 (2026-09-04)

```
완료: imported=0 duplicates_skipped=1051 unmatched=0 errors=0 elapsed=181.7s
[exited with code 0]
```

- ES-DE Local: 실제 media 14,705개 파일, 13.87GB
- 1051개 ROM(media 5,126개) 전부 처리
- exit code 0, orphan `.tmp` 없음, AhnLab Quarantine 폴더 비어있음
- **AhnLab 이벤트 로그 직접 확인(사용자)**: 이 실행 동안 M1875 신규
  탐지 없음

이전(패치 전) 버전은 같은 데이터셋에서 매번 특정 지점(누적 media 약
1만 개 근방, 또는 mkdir/삭제/rename을 부모가 직접 하던 구버전에서는 더
이른 지점)에서 `Ransom/MDP.Event.M1875`로 강제 종료됐다 - 자세한 원인
규명 과정은 별도 브랜치(`claude/ahn-workaround-branch-vpmr9l`)의
`copybench/INCIDENT_T015_pyinstaller.md` 참고.

## Phase 2 — MasterDB → Local 방향 (2026-09-04)

Phase 2(`claude/native-export-to-local-worker`, `export_engine.py`/
`exporters/*`의 ROM/media 복사를 native worker에 위임)를 반대 방향으로
같은 방법으로 검증했다: 실제 MasterDB(`C:\Users\moning\Downloads\DB`,
ROM 989개)를 **새로 만든 빈 Local**(`headless_export_to_local.py`,
`dist_headless2\headless_export_to_local.exe`)로 Export.

대상 Local은 물리 ROM 파일이 있어야 `export_masterdb_to_local()`이
매칭하므로(§`export_engine.py` docstring 참고 - Export는 Local에 실제
존재하는 ROM에 한해 채운다), MasterDB의 989개 rom_filename과 동일한
이름의 빈(0바이트) placeholder 파일을 시스템별 폴더에 미리 만들어서
"물리 ROM이 있는 빈 Local"을 구성했다. ROM 바이트 자체는 이번 검증
대상이 아니므로(`copy_rom=False`) 만들지 않았다 - media/metadata 복사
경로가 이번에 새로 native worker로 옮겨진 부분이다.

```
완료: exported=989 skipped_no_match=0 skipped_conflict=0 skipped_korean_dup=0 not_implemented=False errors=0 elapsed=51.6s
[exited with code 0]
```

- ROM 989개 전부 매칭/처리, media 5,124개 파일 실제 복사(4.91GB)
- exit code 0, orphan `.tmp` 없음
- AhnLab Quarantine 폴더: 이 머신엔 별도 격리 폴더가 생성되지 않는
  구성이라 폴더 자체가 없음(항목 0개와 동일하게 취급)
- **AhnLab 이벤트 로그 직접 확인(사용자)**: 이 실행 동안 M1875/M1870
  신규 탐지 없음

### 재현 방법 (Phase 2)

1. `native\build_worker.bat`으로 워커 빌드(Phase 1과 공유, 이번엔 소스
   변경 없음).
2. MasterDB 989개 rom_filename과 동일한 빈 파일을 새 Local의
   `roms\<system>\` 아래 생성(스크립트로 자동화 - 수동 준비 불필요,
   실제 ROM 바이트는 필요 없음).
3. ```
   pyinstaller --onefile --add-binary "native\MediaCopyWorker.exe;native" ^
       --distpath dist_headless2 --workpath build_headless2 --specpath build_headless2 ^
       headless_export_to_local.py
   ```
4. `dist_headless2\config.json`에 `masterdb.root`(기존 MasterDB)와
   `locals[0]`(2번에서 만든 새 Local)을 채운 뒤
   `dist_headless2\headless_export_to_local.exe` 실행.
5. exit code / orphan `.tmp` / AhnLab 이벤트 로그를 Phase 1과 동일하게
   확인.

## 재현 방법 (Phase 1)

이 시나리오는 `main.py`(GUI)와 별개로 만든 `headless_export.py`를
독립적으로 PyInstaller 패키징해서 돌린다 - GUI 자동화 없이 실제 프로덕션
코드 경로(`import_engine.py`/`media_copy_worker.py`)를 그대로 검증하기
위함이다.

1. **네이티브 워커 빌드** (컴파일러 필요 - MSVC `cl.exe` 또는 MinGW `gcc`):
   ```
   native\build_worker.bat
   ```
   `native\MediaCopyWorker.exe`가 생성됐는지 확인.

2. **headless_export.exe 빌드** (worker를 `--add-binary`로 번들링):
   ```
   pyinstaller --onefile --add-binary "native\MediaCopyWorker.exe;native" ^
       --distpath dist_headless --workpath build_headless --specpath build_headless ^
       headless_export.py
   ```

3. **`dist_headless\config.json` 작성** — `locals[0]`에 media가 충분히
   많은(가능하면 수천~1만 개 이상) 실제 Local 하나, `masterdb.root`에
   기존 MasterDB 경로를 채운다(스키마는 `config.default_config()` 참고).
   골든 데이터셋으로 쓸 만한 후보가 없다면, ES-DE 같은 frontend의
   `downloaded_media` 폴더가 큰 백업을 아무거나 하나 등록해도 된다 -
   중요한 건 media 파일 개수가 수천 단위 이상이어야 이전에 관찰된
   임계치 근방을 실제로 지나가 본다는 것이다.

4. **실행**:
   ```
   dist_headless\headless_export.exe
   ```
   실행 전후로 다음을 확인한다:
   - 프로세스가 exit code 0으로 끝나는지 (`echo %ERRORLEVEL%`)
   - MasterDB `media\` 아래에 `*.tmp` 잔재가 없는지
     (`Get-ChildItem -Recurse -Filter *.tmp`)
   - AhnLab Safe Transaction 이벤트 로그(트레이 아이콘 -> 이벤트 로그
     또는 메인 화면)에 실행 시간대의 새 M1875/M1870 항목이 없는지 -
     **이게 최종 판정 기준**이다. 위 세 가지(exit 0/tmp 없음/Quarantine
     비어있음)는 강한 정황 증거지만, 실제 확정은 항상 이 로그로 했다.

## 주의

- `dist_headless\`/`build_headless\`는 `.gitignore`에 포함되어 있다 -
  커밋하지 않는다.
- 이 검증은 **실제 AhnLab Safe Transaction이 설치된 Windows 머신**에서만
  의미가 있다. AhnLab이 없는 환경(CI 등)에서는 exit code/orphan tmp
  체크만으로 "정상 완료됐다"는 정도만 확인 가능하고, M1875 회피 자체는
  검증할 수 없다.
- media type 개수가 너무 적은(수백 개 이하) Local로는 이전에 관찰된
  임계치 근방을 지나가 보지 못해서 이 검증의 의미가 약해진다 - 가능한
  한 실제로 큰 데이터셋을 쓸 것.
