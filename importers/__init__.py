"""
importers/__init__.py
======================
Frontend 이름 -> 해당 importer 모듈 dispatch.
"""

from . import es_de, daijisho, pegasus, emulationstation, launchbox

REGISTRY = {
    "es-de": es_de,
    "daijisho": daijisho,
    "pegasus": pegasus,
    "emulationstation": emulationstation,
    "launchbox": launchbox,
}


def get_importer(frontend):
    importer = REGISTRY.get(frontend)
    if not importer:
        raise ValueError(f"지원하지 않는 Frontend입니다: {frontend}")
    return importer
