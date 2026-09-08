"""
app/store/sqlite.py
====================
모든 SQLite 저장소가 공유하는 연결/트랜잭션/마이그레이션 기반.

설계 근거는 두 가지다.

**다중 인스턴스(D5).** 앱을 두 개 띄우면 같은 registry.db/archive.db에 두
프로세스가 동시에 붙는다. 그래서
  - `journal_mode=WAL`: 읽는 쪽이 쓰는 쪽을 막지 않는다.
  - `busy_timeout`: 쓰기 경합이 나면 즉시 "database is locked"로 실패하지 않고 기다린다.
  - 쓰기는 항상 `BEGIN IMMEDIATE`: 기본값인 deferred 트랜잭션은 읽다가 나중에
    쓰기로 승격되는데, 두 프로세스가 동시에 승격을 시도하면 busy_timeout으로도
    풀 수 없는 교착(SQLITE_BUSY_SNAPSHOT)이 난다. 처음부터 쓰기 락을 잡으면
    그냥 순서대로 기다렸다 실행된다.

**스키마 마이그레이션.** 이전 프로젝트는 마이그레이션 프레임워크가 없어서 "기존
DB를 고치려면 새로 만들어야 한다"는 주석이 코드에 남아 있었다. 여기서는
`PRAGMA user_version` 기반으로 1일차부터 넣는다. 두 인스턴스가 동시에 시작해도
마이그레이션 전체가 하나의 IMMEDIATE 트랜잭션 안에서 돌기 때문에 한쪽만 적용하고
다른 쪽은 이미 올라간 버전을 보게 된다.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BUSY_TIMEOUT_MS = 15000


@dataclass(frozen=True)
class Migration:
    """version은 1부터 시작하는 연속된 정수. statements는 순서대로 실행된다."""
    version: int
    statements: tuple[str, ...]


class _Rows:
    """결과를 락 안에서 미리 다 읽어 둔 커서.

    커서를 그대로 돌려주면 호출부가 락 **밖에서** 행을 하나씩 당겨오게 되고, 그
    순간 다시 같은 연결을 만지게 된다. 그래서 읽기는 락 안에서 끝낸다.
    """

    __slots__ = ("_rows", "_index", "lastrowid", "rowcount")

    def __init__(self, rows, lastrowid, rowcount):
        self._rows, self._index = rows, 0
        self.lastrowid, self.rowcount = lastrowid, rowcount

    def __iter__(self):
        return iter(self._rows[self._index:])

    def fetchone(self):
        if self._index >= len(self._rows):
            return None
        self._index += 1
        return self._rows[self._index - 1]

    def fetchall(self):
        rest, self._index = self._rows[self._index:], len(self._rows)
        return rest

    def fetchmany(self, size=1):
        rest = self._rows[self._index:self._index + size]
        self._index += len(rest)
        return rest


class _SerializedConnection:
    """같은 연결을 여러 스레드가 쓰는 것을 안전하게 만든다.

    Job 워커가 스캔으로 Cache를 쓰는 동안 사용자가 Archive 수집을 누르는 것은
    정상적인 사용이다. 그때 SQLite 연결이 깨지면 "실패했는데 화면은 완료"가 된다.

    재진입 가능한 락을 쓴다 - `transaction()` 안에서 다시 `execute()`를 부르기 때문이다.
    """

    def __init__(self, conn):
        object.__setattr__(self, "_conn", conn)
        object.__setattr__(self, "_lock", threading.RLock())

    # -- 문장 실행 ------------------------------------------------------
    def execute(self, *args, **kwargs):
        with self._lock:
            cur = self._conn.execute(*args, **kwargs)
            return _Rows(cur.fetchall(), cur.lastrowid, cur.rowcount)

    def executemany(self, *args, **kwargs):
        with self._lock:
            cur = self._conn.executemany(*args, **kwargs)
            return _Rows(cur.fetchall(), cur.lastrowid, cur.rowcount)

    def executescript(self, *args, **kwargs):
        with self._lock:
            return self._conn.executescript(*args, **kwargs)

    # -- 트랜잭션 경계 --------------------------------------------------
    @property
    def lock(self):
        """`transaction()`이 트랜잭션 전체를 한 스레드에 묶기 위해 쓴다."""
        return self._lock

    @property
    def in_transaction(self):
        with self._lock:
            return self._conn.in_transaction

    def close(self):
        with self._lock:
            return self._conn.close()

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_conn"), name)

    def __setattr__(self, name, value):
        setattr(self._conn, name, value)


def connect(path, migrations=(), *, busy_timeout_ms=DEFAULT_BUSY_TIMEOUT_MS):
    """DB를 열고 PRAGMA를 세팅한 뒤 마이그레이션까지 끝난 연결을 돌려준다.

    `isolation_level=None`으로 파이썬의 암묵적 트랜잭션 관리를 끄고, 트랜잭션은
    이 모듈의 `transaction()`으로만 연다. `check_same_thread=False`는 Job 워커
    스레드에서 같은 연결을 쓰기 위한 것이다(프로세스 *내부* 스레드 안전성은
    호출부가 책임진다 - 프로세스 *간* 안전성은 WAL이 담당한다).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=busy_timeout_ms / 1000.0,
                           check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
    conn.execute("PRAGMA foreign_keys=ON")
    if migrations:
        migrate(conn, migrations)
    # **연결을 직렬화해서 돌려준다.** Job 워커와 사용자 동작이 같은 연결을
    # 동시에 만지면 커서와 트랜잭션 상태가 뒤섞인다.
    return _SerializedConnection(conn)


def _transaction_body(conn, immediate):
    """실제 BEGIN/COMMIT/ROLLBACK. 락은 `transaction()`이 잡는다."""
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


@contextmanager
def transaction(conn, immediate=True):
    """쓰기 트랜잭션. 중첩해서 열 수 없다(SQLite가 중첩 트랜잭션을 지원하지 않음).

    이미 트랜잭션이 열려 있으면 그대로 통과시켜서, 호출부가 `transaction()`을
    중첩해도 바깥쪽 하나만 커밋되도록 한다.
    """
    lock = getattr(conn, "lock", None)
    if lock is None:
        yield from _transaction_body(conn, immediate)
        return
    # **트랜잭션 전체를 한 스레드가 쥔다.** 문장 단위로만 직렬화하면 BEGIN과 COMMIT
    # 사이에 다른 스레드가 끼어들어 "커밋할 트랜잭션이 없다"가 된다.
    with lock:
        yield from _transaction_body(conn, immediate)


def user_version(conn) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def migrate(conn, migrations):
    """아직 적용되지 않은 마이그레이션만 순서대로 적용한다.

    두 인스턴스가 동시에 시작해도 안전하다 - 버전 확인과 적용이 하나의 IMMEDIATE
    트랜잭션 안에 있으므로, 진 쪽은 트랜잭션을 시작한 시점에 이미 올라간 버전을
    보고 아무것도 하지 않는다.
    """
    ordered = sorted(migrations, key=lambda m: m.version)
    expected = list(range(1, len(ordered) + 1))
    if [m.version for m in ordered] != expected:
        raise ValueError(f"마이그레이션 version은 1부터 연속이어야 합니다: {[m.version for m in ordered]}")

    with transaction(conn):
        current = user_version(conn)
        target = ordered[-1].version if ordered else 0
        if current >= target:
            return current
        for m in ordered:
            if m.version <= current:
                continue
            for stmt in m.statements:
                conn.execute(stmt)
        # PRAGMA는 파라미터 바인딩이 안 되므로 정수임을 확인하고 직접 넣는다.
        conn.execute(f"PRAGMA user_version={int(target)}")
        return target
