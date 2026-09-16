"""
storage/__init__.py
====================
Provider를 고르는 **유일한 분기점**.

호출부는 어떤 저장소인지 몰라야 한다. `storage.for_path(경로)` 하나만 부르면
드라이브 문자든 UNC든 MTP든 알아서 맞는 Provider가 온다. 이 분기를 여기 한 곳에
가둬 두지 않으면, 저장소 종류가 늘 때마다 앱 전체에 흩어진 생성 지점을 다시 찾아야
한다(`file_ops.select_engine()`이 CopyEngine에 대해 하는 일과 같다).

**경로 문자열 자체가 저장소 종류를 말한다.** 그래서 Adapter처럼 Provider를 인자로
받지 못하는 자리에서도, 손에 든 경로만으로 올바른 Provider를 얻을 수 있다.
"""

from storage.local import LocalStorageProvider  # noqa: F401
from storage.provider import DirEntry, Stat, StorageProvider, VolumeInfo  # noqa: F401


def for_path(path) -> StorageProvider:
    """경로에 맞는 Provider. **저장소 종류를 따지는 분기는 여기에만 둔다.**"""
    from storage import mtp

    if mtp.is_mtp_path(path):
        return mtp.provider()
    return LocalStorageProvider.for_path(path)
