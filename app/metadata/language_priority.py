"""SQL ordering for descriptions grouped by their visible writing system.

Gamelists store one untagged description. This groups obvious Hangul and
Latin-script text; it does not claim to identify a natural language.
"""


def description_priority_sql(description_sql: str, priority: str) -> str:
    """Return a stable ascending bucket expression for desc_ko/desc_en."""
    if priority not in ("desc_ko", "desc_en"):
        raise ValueError(f"Unknown description priority: {priority}")
    value = f"TRIM(COALESCE({description_sql}, ''))"
    hangul = f"({value} GLOB '*[가-힣ㄱ-ㅎㅏ-ㅣ]*')"
    # A title embedded in Japanese/Chinese text must not make it English.
    cjk = f"({value} GLOB '*[一-龯ぁ-ゟァ-ヿ]*')"
    latin = f"({value} GLOB '*[A-Za-z]*' AND NOT {hangul} AND NOT {cjk})"
    first, second = (hangul, latin) if priority == "desc_ko" else (latin, hangul)
    return (f"CASE WHEN {value} = '' THEN 3 WHEN {first} THEN 0"
            f" WHEN {second} THEN 1 ELSE 2 END")
