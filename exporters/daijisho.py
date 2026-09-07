"""
exporters/daijisho.py
=======================
다이지쇼 실제 구조 확인 전까지 미구현. (importers/daijisho.py와 동일한 사유)
"""


def read_existing_fields(metadata_path, system, rom_filename, cache=None):
    raise NotImplementedError("다이지쇼 Export는 실제 폴더 구조 확인 후 구현 예정입니다.")


def write_metadata_fields(metadata_path, system, rom_filename, fields, cache=None):
    raise NotImplementedError("다이지쇼 Export는 실제 폴더 구조 확인 후 구현 예정입니다.")


def write_media(media_path, system, rom_filename, media_dict, copy_video=True, batch=None):
    raise NotImplementedError("다이지쇼 Export는 실제 폴더 구조 확인 후 구현 예정입니다.")
