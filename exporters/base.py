"""
exporters/base.py
==================
Frontend별 Exporter 공통 인터페이스 및 유틸.

각 frontend 모듈은 아래 함수를 구현한다:
    write_metadata_fields(metadata_path, system, rom_filename, fields) -> None
        MasterDB의 fields를 Local의 실제 metadata 파일에 기록(신규 추가 또는 기존 항목 갱신).

    write_media(media_path, system, rom_filename, media_dict, copy_video=True) -> None
        MasterDB에 저장된 media 파일들을 Local의 media 구조에 맞게 복사.
        media_dict: db 스키마의 'media' 필드 { mediatype: path 또는 [path,...] }
"""

from pathlib import Path

import file_ops

# es-de/emulationstation 공통 media 폴더명 (importers.base.ES_DE_MEDIA_FOLDER_MAP과 동일)
ES_DE_MEDIA_FOLDER_MAP = {
    "3dboxes": "3dboxes",
    "covers": "covers",
    "marquees": "marquees",
    "miximages": "miximages",
    "screenshots": "screenshots",
    "videos": "videos",
    "wheel": "wheel",
}

# pegasus mediatype -> 기본 asset 파일명
PEGASUS_ASSET_FILENAME = {
    "covers": "boxFront",
    "screenshots": "screenshot",
    "marquees": "marquee",
    "miximages": "background",
    "wheel": "logo",
    "videos": "video",
}


def _as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def copy_media_es_style(media_path, system, rom_filename, media_dict, copy_video=True, batch=None):
    """<media_path>/downloaded_media/<system>/<mediatype>/<rom_stem>.ext 구조로 복사
    (es-de/emulationstation 공용). media_path는 metadata_path와 동일한 '루트' 폴더.

    [별도 프로세스 위임] mkdir + 실제 바이트 복사를 native worker에 맡긴다
    (file_ops.copy_files) - 이 함수 자신은 "무엇을 어디로 복사할지"
    계획(존재 확인, 목적지 경로 계산)만 세운다. media type마다 목적지
    폴더가 다르므로(covers/screenshots/... 각각 별도 하위폴더) 이 ROM
    한 개 분량의 모든 media type을 다 모아서 워커를 한 번만 호출한다.
    실패한 개별 파일은 조용히 건너뛴다 - 기존 동작(그 파일만 continue)과
    동일, 한 파일 실패가 다른 파일에 영향 없음.

    [체감 속도, batch] batch(file_ops.MediaCopyBatch)가 주어지면 이 ROM의
    pair들을 즉시 복사하지 않고 거기에 쌓기만 한다 - 호출부(export_engine.py)가
    여러 ROM 분량을 모아서 한 번에 flush()하면, ROM마다 워커 프로세스를
    새로 spawn하지 않아도 된다. batch가 없으면(기본값) 예전처럼 이 ROM
    분량만 즉시 복사한다."""
    stem = Path(rom_filename).stem
    dest_dirs = []
    pairs = []
    for mediatype, folder in ES_DE_MEDIA_FOLDER_MAP.items():
        if mediatype == "videos" and not copy_video:
            continue
        srcs = _as_list(media_dict.get(mediatype))
        if not srcs:
            continue
        dest_dir = Path(media_path) / "downloaded_media" / system / folder
        dest_dirs.append(dest_dir)
        for i, src in enumerate(srcs):
            src_path = Path(src)
            if not src_path.exists():
                continue
            suffix = src_path.suffix
            dest_name = f"{stem}{suffix}" if len(srcs) == 1 else f"{stem}_{i}{suffix}"
            pairs.append((src_path, dest_dir / dest_name))
    if pairs:
        if batch is not None:
            batch.add(dest_dirs, pairs)
        else:
            file_ops.copy_files(dest_dirs, pairs)


def copy_media_pegasus_style(media_path, system, rom_filename, media_dict, copy_video=True, batch=None):
    """media_path/<system>/media/<rom_stem>/<assetname>.ext 구조로 복사.

    [별도 프로세스 위임] copy_media_es_style()과 동일 - mkdir + 복사를
    워커에 위임. pegasus는 media type이 다 같은 dest_dir 밑에 모이므로
    디렉터리는 하나뿐이다. batch 파라미터도 copy_media_es_style()과 동일."""
    stem = Path(rom_filename).stem
    dest_dir = Path(media_path) / system / "media" / stem
    pairs = []
    for mediatype, asset_name in PEGASUS_ASSET_FILENAME.items():
        if mediatype == "videos" and not copy_video:
            continue
        srcs = _as_list(media_dict.get(mediatype))
        if not srcs:
            continue
        src_path = Path(srcs[0])
        if not src_path.exists():
            continue
        pairs.append((src_path, dest_dir / f"{asset_name}{src_path.suffix}"))
    if pairs:
        if batch is not None:
            batch.add(dest_dir, pairs)
        else:
            file_ops.copy_files(dest_dir, pairs)
