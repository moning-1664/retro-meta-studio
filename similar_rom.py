"""
similar_rom.py
================
유사롬(Comparable ROM) 판별 알고리즘.

설계 원칙 (사용자 확정):
  - 시스템이 다르면 애초에 비교 대상이 아님 (호출부에서 같은 system끼리만 넘겨야 함)
  - 자동 실행 안 함 - 사용자가 시스템을 선택하고 "유사롬 찾기"를 눌렀을 때만 그
    시스템 내에서 O(n^2) 비교를 수행 (전체 시스템을 한꺼번에 돌리면 너무 느려서
    성능상 의도적으로 스코프를 좁힘)
  - 점수제: 여러 기준의 유사도를 합산해서 임계값을 넘으면 "유사롬"으로 판단
  - 결과는 호출부(api.py)가 DB에 저장해서 나중에도 다시 볼 수 있게 함

점수 기준 (기본값, Settings에서 조정 가능):
  제목 유사도(정규화 후)      : 최대 35점
  스크린샷 SHA256 완전일치     : 20점 (이진 - 사실상 결정적 증거라 가장 높은 배점)
  파일명 유사도                : 최대 15점
  개발사명 유사도              : 최대 15점
  출시년도 동일                : 15점 (이진)
  합계 100점, 기본 임계값 60점 이상이면 유사롬으로 판단.
"""

import hashlib
import difflib
from pathlib import Path

from utils import normalize_title

DEFAULT_WEIGHTS = {
    "title": 35,
    "filename": 15,
    "developer": 15,
    "year": 15,
    "screenshot": 20,
}
DEFAULT_THRESHOLD = 60


def _similarity(a, b):
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _normalize_filename(filename):
    """확장자를 떼고 title과 같은 정규화 규칙(괄호정보/한글표기 제거 등)을 적용."""
    stem = Path(filename or "").stem
    return normalize_title(stem)


def sha256_of_file(path):
    """파일의 SHA256 해시. 없거나 못 읽으면 None."""
    try:
        p = Path(path)
        if not p.exists():
            return None
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def compute_pair_score(rom_a, rom_b, weights=None):
    """
    두 ROM 항목 간 유사도 점수(0~100)와 항목별 배점 breakdown을 반환.
    rom_a/rom_b: {romKey, title, filename, developer, releasedate, screenshot_hash}
    """
    weights = weights or DEFAULT_WEIGHTS
    breakdown = {}

    t_sim = _similarity(normalize_title(rom_a.get("title", "")), normalize_title(rom_b.get("title", "")))
    breakdown["title"] = round(t_sim * weights["title"], 2)

    f_sim = _similarity(_normalize_filename(rom_a.get("filename", "")), _normalize_filename(rom_b.get("filename", "")))
    breakdown["filename"] = round(f_sim * weights["filename"], 2)

    d_sim = _similarity((rom_a.get("developer") or "").strip().lower(), (rom_b.get("developer") or "").strip().lower())
    breakdown["developer"] = round(d_sim * weights["developer"], 2)

    year_a = (rom_a.get("releasedate") or "")[:4]
    year_b = (rom_b.get("releasedate") or "")[:4]
    breakdown["year"] = weights["year"] if (year_a and year_a == year_b) else 0

    hash_a, hash_b = rom_a.get("screenshot_hash"), rom_b.get("screenshot_hash")
    breakdown["screenshot"] = weights["screenshot"] if (hash_a and hash_b and hash_a == hash_b) else 0

    total = round(sum(breakdown.values()), 2)
    return total, breakdown


def find_similar_roms(roms, weights=None, threshold=None, progress_cb=None):
    """
    roms: [{romKey, title, filename, developer, releasedate, screenshot_path}, ...]
          (반드시 같은 system 내의 항목만 넘길 것 - 이 함수는 시스템을 구분하지 않는다)
    반환: [{members: [romKey, ...], pairs: [{a, b, score, breakdown}, ...]}]
          서로 임계값 이상으로 연결된 ROM들을 union-find로 그룹핑한 결과.
    """
    weights = weights or DEFAULT_WEIGHTS
    threshold = DEFAULT_THRESHOLD if threshold is None else threshold

    # 스크린샷 해시는 ROM당 한 번만 계산 (O(n)) - 이후 비교는 해시 문자열만 비교하면 되므로 저렴함
    for idx, r in enumerate(roms):
        if "screenshot_hash" not in r:
            r["screenshot_hash"] = sha256_of_file(r.get("screenshot_path")) if r.get("screenshot_path") else None

    n = len(roms)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    pair_results = []
    total_pairs = max(1, n * (n - 1) // 2)
    done = 0
    for i in range(n):
        for j in range(i + 1, n):
            score, breakdown = compute_pair_score(roms[i], roms[j], weights)
            if score >= threshold:
                union(i, j)
                pair_results.append({"a": roms[i]["romKey"], "b": roms[j]["romKey"], "score": score, "breakdown": breakdown})
            done += 1
            if progress_cb and done % 50 == 0:
                progress_cb(done, total_pairs, f"{roms[i].get('title') or roms[i]['romKey']} 비교 중")

    groups_map = {}
    for i in range(n):
        root = find(i)
        groups_map.setdefault(root, []).append(roms[i]["romKey"])

    groups = []
    for members in groups_map.values():
        if len(members) <= 1:
            continue
        member_set = set(members)
        pairs = [p for p in pair_results if p["a"] in member_set and p["b"] in member_set]
        groups.append({"members": members, "pairs": pairs})
    return groups
