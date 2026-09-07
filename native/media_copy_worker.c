/*
 * media_copy_worker.c
 * ====================
 * RetroMetadataManager의 프로덕션 media export worker. Python 인터프리터를
 * 전혀 포함하지 않는 독립 실행 파일이다.
 *
 * [v2, 2026-09-04] 처음엔 "CopyFileW만" 담당하고 mkdir/기존파일삭제/
 * rename은 Python(부모 프로세스)이 직접 했다. 그런데 실측 결과, 그렇게
 * 해도 부모 프로세스 자신이 ROM마다 반복하는 mkdir/삭제/rename 자체가
 * AhnLab 행동 기반 탐지(Ransom/MDP.Event.M1875)에 걸려 부모가 강제
 * 종료되는 게 재현됐다(실제 RetroMetadataManager 패키징 EXE + 14,705개
 * 실제 media로 검증 - 14:53/15:03/15:53/18:05 총 4회 M1875, headless_export.exe
 * 도 포함). 그래서 이제 mkdir/기존파일삭제/rename까지 전부 이 워커가
 * 하고, 부모 프로세스는 "무엇을 할지 계획만 세워서 job 파일로 넘기는"
 * 역할만 한다 - 실제 파일시스템 mutation은 이 프로세스에만 남긴다.
 *
 * 사용법:
 *   MediaCopyWorker.exe <job_file_path>
 *
 * job_file 문법 (UTF-8 텍스트, 한 줄에 명령 하나, TAB 구분):
 *   M<TAB><dir>
 *       <dir>을 재귀적으로 생성한다(이미 있으면 조용히 통과). 만나는
 *       즉시 실행 - group과 무관.
 *   G<TAB><아무거나>
 *       새 "그룹"의 시작을 표시한다. 그룹 = 원자적으로 함께 확정돼야
 *       하는 C/X/R 명령의 묶음(예: ROM 하나의 media type 하나). 이전
 *       그룹이 있었다면 먼저 flush(실행)한다. 두 번째 필드 값 자체는
 *       쓰지 않는다(가독성/디버깅용).
 *   C<TAB><index><TAB><src><TAB><tmp_dest>
 *       src -> tmp_dest로 CopyFileW. index는 "OK <index>"/"ERR <index>
 *       <code>" 출력으로 그대로 돌아간다(호출자가 원래 pair와 매칭).
 *       가장 최근 G로 시작한 그룹에 속한다.
 *   X<TAB><path>
 *       그 그룹의 모든 C가 성공하면(그룹 확정 시) 이 기존 파일을
 *       best-effort로 지운다(실패해도 무시 - 원래 Python 쪽 try/except
 *       OSError: pass와 동일).
 *   R<TAB><tmp_dest><TAB><final_dest>
 *       그룹이 확정되면 tmp_dest -> final_dest로 rename(MoveFileExW,
 *       MOVEFILE_REPLACE_EXISTING).
 *
 * "그룹 확정"의 정의: 그 그룹에 속한 C 명령이 전부 CopyFileW 성공 **그리고**
 * 그 그룹의 job 명령(M 제외) 중 파싱에 실패했거나 MAX_GROUP_ENTRIES를
 * 넘겨서 등록조차 못 된 것이 하나도 없어야 한다. 하나라도 실패/손상되면
 * 그 그룹은 확정되지 않고: 이미 성공한 C의 tmp_dest들만 정리(삭제)하고,
 * X/R은 전혀 실행하지 않는다(기존 파일은 그대로 유지 - 원래 Python 쪽의
 * "새 파일 복사 실패 -> 기존 파일 유지" 원자성 보장과 동일). [리뷰 반영,
 * P0] 처음엔 "손상된 명령은 조용히 무시"했는데, 그러면 실제로는 파일
 * 몇 개가 계획에서 빠졌는데도 "등록된 것만 전부 성공했으니 그룹 확정"
 * 으로 착각해 기존 파일을 지우고 rename까지 해버릴 수 있었다 - 지금은
 * 그런 손상 신호가 하나라도 있으면 그 그룹 전체를 실패로 처리한다.
 *
 * 출력(stdout, 매 줄마다 즉시 flush): 각 C 명령에 대해 "OK <index>" 또는
 * "ERR <index> <win32_error_code>" 한 줄씩. M/G/X/R 자체는 성공/실패를
 * 별도로 보고하지 않는다(호출자는 C의 성공 여부로 그 그룹이 확정됐는지
 * 스스로 판단할 수 있다 - 이 워커의 "전부 성공해야 확정" 규칙이 결정론적
 * 이기 때문). 종료 코드: 모든 C가 성공하면 0, 하나라도 실패/손상된 줄이
 * 있었으면 1.
 *
 * [정책] "워커 프로세스 자체가 실행에 실패/크래시/타임아웃"과 "개별 파일의
 * CopyFileW 실패"는 다르게 다뤄진다 - 후자는 워커가 정상적으로 살아서
 * ERR로 보고한 것이므로, 호출자(media_copy_worker.py)는 이걸 실제 복사
 * 실패로 취급하고 in-process fallback으로 재시도하지 않는다. fallback은
 * 워커를 아예 못 띄웠거나, 타임아웃/손상된 출력처럼 "그 pair의 결과
 * 자체를 못 받은" 경우에만 일어난다.
 */

#include <windows.h>
#include <shlobj.h>
#include <stdio.h>
#include <string.h>
#include <wchar.h>
#include <stdlib.h>

#define MAX_LINE_BYTES (1024 * 64) /* UTF-8 한 줄 최대 길이 */
#define ERR_LINE_TOO_LONG 0xFFFFFFFFUL /* job line이 버퍼보다 길 때 쓰는 sentinel 에러코드 */
#define MAX_GROUP_ENTRIES 1024 /* ROM 하나의 media type 하나에 이 정도면 넉넉함 */

static wchar_t *utf8_to_wide(const char *utf8, int len) {
    if (len <= 0) return NULL;
    int wlen = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, utf8, len, NULL, 0);
    if (wlen <= 0) return NULL;
    wchar_t *buf = (wchar_t *)malloc((size_t)(wlen + 1) * sizeof(wchar_t));
    if (!buf) return NULL;
    MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, utf8, len, buf, wlen);
    buf[wlen] = L'\0';
    return buf;
}

typedef struct {
    int idx;
    wchar_t *src;
    wchar_t *tmp;
    BOOL ok;
} CopyEntry;

static CopyEntry g_copies[MAX_GROUP_ENTRIES];
static int g_copy_count = 0;
static wchar_t *g_deletes[MAX_GROUP_ENTRIES];
static int g_delete_count = 0;
static wchar_t *g_rename_tmp[MAX_GROUP_ENTRIES];
static wchar_t *g_rename_final[MAX_GROUP_ENTRIES];
static int g_rename_count = 0;

static int g_any_failed = 0; /* 종료 코드용 - C 실패 또는 손상된 줄이 하나라도 있으면 1 */

/* [리뷰 반영, P0] 이 그룹에 속한 명령 중 하나라도 파싱에 실패했거나
   MAX_GROUP_ENTRIES를 넘겨서 버려졌으면 그 사실을 기록한다. C 명령
   일부가 조용히 누락된 채로 나머지가 전부 성공하면 "그룹 전체 성공"으로
   착각해 기존 파일을 지우고 rename까지 해버릴 수 있다 - 이건 job 데이터
   일부가 유실된 상태에서 최종 확정을 내리는 것이므로 반드시 막아야 한다.
   flush_group()이 이 플래그를 보고 all_ok를 강제로 거짓으로 만든다. */
static int g_group_corrupted = 0;

static void free_group(void) {
    for (int i = 0; i < g_copy_count; i++) { free(g_copies[i].src); free(g_copies[i].tmp); }
    for (int i = 0; i < g_delete_count; i++) free(g_deletes[i]);
    for (int i = 0; i < g_rename_count; i++) { free(g_rename_tmp[i]); free(g_rename_final[i]); }
    g_copy_count = 0;
    g_delete_count = 0;
    g_rename_count = 0;
    g_group_corrupted = 0;
}

static void flush_group(void) {
    if (g_copy_count == 0 && g_delete_count == 0 && g_rename_count == 0 && !g_group_corrupted) return;

    /* [리뷰 반영, P0] 그룹이 손상된 것으로 이미 판정됐으면, 개별 copy가
       전부 성공했더라도 확정(delete+rename)하지 않는다 - 우리가 놓친
       명령이 있을 수 있으므로 job 데이터를 전부 신뢰할 수 없다. */
    int all_ok = !g_group_corrupted;
    if (g_group_corrupted) g_any_failed = 1;
    for (int i = 0; i < g_copy_count; i++) {
        BOOL ok = FALSE;
        if (g_copies[i].src && g_copies[i].tmp) {
            ok = CopyFileW(g_copies[i].src, g_copies[i].tmp, FALSE);
            if (ok) {
                printf("OK %d\n", g_copies[i].idx);
            } else {
                DWORD err = GetLastError();
                printf("ERR %d %lu\n", g_copies[i].idx, err);
            }
        } else {
            printf("ERR %d 0\n", g_copies[i].idx);
        }
        g_copies[i].ok = ok;
        if (!ok) { all_ok = 0; g_any_failed = 1; }
    }

    if (all_ok) {
        /* 그룹 확정: 기존 파일 정리 후 rename. 개별 실패는 무시(best-effort -
           원래 Python의 try/except OSError: pass와 동일 취급). */
        for (int i = 0; i < g_delete_count; i++) {
            if (g_deletes[i]) DeleteFileW(g_deletes[i]);
        }
        for (int i = 0; i < g_rename_count; i++) {
            if (g_rename_tmp[i] && g_rename_final[i]) {
                MoveFileExW(g_rename_tmp[i], g_rename_final[i], MOVEFILE_REPLACE_EXISTING);
            }
        }
    } else {
        /* 그룹 미확정: 이번에 실제로 성공했던 복사분만 정리하고, 기존
           파일에는 손대지 않는다(X/R 실행 안 함). */
        for (int i = 0; i < g_copy_count; i++) {
            if (g_copies[i].ok && g_copies[i].tmp) DeleteFileW(g_copies[i].tmp);
        }
    }

    free_group();
}

int wmain(int argc, wchar_t *argv[]) {
    if (argc < 2) {
        fwprintf(stderr, L"usage: MediaCopyWorker.exe <job_file_path>\n");
        return 2;
    }

    FILE *f = _wfopen(argv[1], L"rb");
    if (!f) {
        fwprintf(stderr, L"job file open failed: %s\n", argv[1]);
        return 2;
    }

    /* 완전 무버퍼링 - 파이프로 리다이렉션되면 기본은 블록 버퍼링이라,
       부모가 진행 상황을 실시간으로 못 보고 프로세스가 죽으면 마지막
       몇 줄이 유실될 수 있다. */
    setvbuf(stdout, NULL, _IONBF, 0);

    char line[MAX_LINE_BYTES];

    while (fgets(line, sizeof(line), f)) {
        size_t len = strlen(line);

        /* 이 줄이 버퍼보다 길어서 fgets가 잘라낸 경우: 다음 실제 개행까지
           버려서 재동기화한다. 어떤 명령이었는지 알 수 없으므로 index별
           보고는 못 하고, 종료 코드만 실패로 남긴다(호출자 쪽에서 이
           명령이 대응하던 index는 "결과 없음"으로 남아 missing -> fallback
           경로를 그대로 탄다). */
        if (len == sizeof(line) - 1 && line[len - 1] != '\n') {
            int c;
            while ((c = fgetc(f)) != EOF && c != '\n') { /* discard */ }
            /* 이 줄이 현재 그룹 소속의 C/X/R이었을 수도 있으므로(어떤
               opcode였는지조차 알 수 없음) 현재 그룹을 안전하게
               손상시킨다. */
            g_any_failed = 1;
            g_group_corrupted = 1;
            continue;
        }

        while (len > 0 && (line[len - 1] == '\n' || line[len - 1] == '\r')) {
            line[--len] = '\0';
        }
        if (len == 0) continue; /* 빈 줄은 무해함 (명령 사이 개행 등) */
        if (line[1] != '\t') {
            /* [리뷰 반영, P0] "<opcode>\t..." 형식 자체가 아닌 줄 - 완전히
               손상된 job이다. 어느 그룹 소속인지도 알 수 없으므로 현재
               버퍼링 중인 그룹을 안전하게 실패시킨다. */
            g_any_failed = 1;
            g_group_corrupted = 1;
            continue;
        }

        char op = line[0];
        char *p = line + 2;

        if (op == 'M') {
            wchar_t *dir = utf8_to_wide(p, (int)strlen(p));
            if (dir) {
                SHCreateDirectoryExW(NULL, dir, NULL); /* 이미 있으면 그냥 무시됨 */
                free(dir);
            } else {
                /* mkdir이 안 됐어도 group 원자성과는 무관 - 뒤따르는 C가
                   자연스럽게 CopyFileW 실패로 이어져서 이미 안전하게
                   처리된다. 가시성을 위해 종료 코드만 실패로 남긴다. */
                g_any_failed = 1;
            }
        } else if (op == 'G') {
            flush_group(); /* 이전 그룹을 먼저 실행/정리하고 새 그룹 시작 */
        } else if (op == 'C') {
            char *t1 = strchr(p, '\t');
            char *t2 = t1 ? strchr(t1 + 1, '\t') : NULL;
            if (!t1 || !t2) {
                /* [리뷰 반영, P0] 형식이 깨진 C 줄 - index조차 알 수 없어
                   OK/ERR로 보고할 수도 없다. 이 그룹은 계획한 파일 중
                   일부를 놓친 것이므로, 나머지가 전부 성공해도 확정하면
                   안 된다. */
                g_any_failed = 1;
                g_group_corrupted = 1;
                continue;
            }
            *t1 = '\0';
            *t2 = '\0';
            char *idx_s = p;
            char *src_s = t1 + 1;
            char *tmp_s = t2 + 1;
            if (g_copy_count < MAX_GROUP_ENTRIES) {
                g_copies[g_copy_count].idx = atoi(idx_s);
                g_copies[g_copy_count].src = utf8_to_wide(src_s, (int)strlen(src_s));
                g_copies[g_copy_count].tmp = utf8_to_wide(tmp_s, (int)strlen(tmp_s));
                g_copies[g_copy_count].ok = FALSE;
                g_copy_count++;
            } else {
                /* [리뷰 반영, P0] MAX_GROUP_ENTRIES 초과 - 이 C는 배열에
                   등록되지 못했으므로 all_ok 판정(등록된 것만 순회)에
                   전혀 반영되지 않는다. 그대로 두면 "등록된 것만 전부
                   성공 -> 그룹 확정"이 되어, 실제로는 하나 이상의 파일이
                   빠진 채로 기존 파일을 지우고 rename할 수 있다. */
                printf("ERR %s 0\n", idx_s);
                g_any_failed = 1;
                g_group_corrupted = 1;
            }
        } else if (op == 'X') {
            if (g_delete_count < MAX_GROUP_ENTRIES) {
                g_deletes[g_delete_count++] = utf8_to_wide(p, (int)strlen(p));
            } else {
                /* 지울 예정이던 기존 파일 하나가 빠지면 확정 후에도 고아
                   파일이 남을 수 있다 - 그룹 확정을 막는다. */
                g_any_failed = 1;
                g_group_corrupted = 1;
            }
        } else if (op == 'R') {
            char *t1 = strchr(p, '\t');
            if (!t1) {
                /* [리뷰 반영, P0] rename 대상 하나가 통째로 유실됨 - 그대로
                   두면 그 media 파일은 tmp인 채로 남고도 그룹이 확정될
                   수 있다(다른 C/R이 전부 성공하면). */
                g_any_failed = 1;
                g_group_corrupted = 1;
                continue;
            }
            *t1 = '\0';
            char *tmp_s = p;
            char *final_s = t1 + 1;
            if (g_rename_count < MAX_GROUP_ENTRIES) {
                g_rename_tmp[g_rename_count] = utf8_to_wide(tmp_s, (int)strlen(tmp_s));
                g_rename_final[g_rename_count] = utf8_to_wide(final_s, (int)strlen(final_s));
                g_rename_count++;
            } else {
                g_any_failed = 1;
                g_group_corrupted = 1;
            }
        } else {
            /* 인식 못 하는 opcode - 이 job 포맷은 Python(media_copy_worker.py)
               과 이 워커가 항상 같이 빌드/배포되는 닫힌 프로토콜이라 전방
               호환을 봐줄 이유가 없다. 손상된 job으로 간주해 안전하게
               실패시킨다. */
            g_any_failed = 1;
            g_group_corrupted = 1;
        }
    }

    flush_group(); /* 마지막 그룹 처리 */
    fclose(f);
    return g_any_failed ? 1 : 0;
}
