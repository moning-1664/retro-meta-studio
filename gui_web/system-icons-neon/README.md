# System Icons — Neon Outline (보류)

2026-09-12에 시도했던 네온 아웃라인 스타일 System 아이콘 팩. 지금은 쓰지 않지만(사용자 결정 - 최종
스타일은 `system-icons-50/`으로 확정됨), 나중에 다시 쓸 수 있을 것 같아 별도 폴더로 남겨 둔다.

파일명 규칙은 `system-icons-50/`과 같다(`gui_web/system-icons-pack.js`의 `candidates()`가 만드는
이름 그대로) - 그래서 나중에 쓰기로 하면 교체는 `system-icons-pack.js`의 `BASE` 상수를
`"system-icons-neon/"`으로 바꾸는 것만으로 된다(별칭/접미사 매칭 로직은 그대로 재사용된다).

47개 System만 있고 `system-icons-50/`의 전체 세트(88개)보다 적다 - 나머지는 이 스타일로
만들어지지 않았다. 쓰기로 결정하면 빠진 System은 새로 그리거나 폴백(SVG)에 맡겨야 한다.
