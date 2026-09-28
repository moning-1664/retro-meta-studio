"""SQL ordering for descriptions grouped by their visible writing system.

Gamelists store one untagged description. This groups obvious Hangul, kana,
CJK, and Latin-script text; it does not claim to identify a natural language.
"""


def description_priority_sql(description_sql: str, priority: str) -> str:
    """Return a stable script-priority bucket for an untagged description."""
    if priority not in ("desc_ko", "desc_en", "desc_ja"):
        raise ValueError(f"Unknown description priority: {priority}")
    value = f"TRIM(COALESCE({description_sql}, ''))"
    hangul = f"({value} GLOB '*[가-힣ㄱ-ㅎㅏ-ㅣ]*')"
    # A title embedded in Japanese/Chinese text must not make it English.
    cjk = f"({value} GLOB '*[一-龯ぁ-ゟァ-ヿ]*')"
    japanese = f"({value} GLOB '*[ぁ-ゟァ-ヿ]*')"
    latin = f"({value} GLOB '*[A-Za-z]*' AND NOT {hangul} AND NOT {cjk})"
    if priority == "desc_ja":
        return (f"CASE WHEN {value} = '' THEN 4 WHEN {japanese} THEN 0"
                f" WHEN {cjk} AND NOT {hangul} THEN 1 WHEN {latin} THEN 2"
                f" WHEN {hangul} THEN 3 ELSE 3 END")
    first, second = (hangul, latin) if priority == "desc_ko" else (latin, hangul)
    return (f"CASE WHEN {value} = '' THEN 3 WHEN {first} THEN 0"
            f" WHEN {second} THEN 1 ELSE 2 END")
