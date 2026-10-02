"""Shared bridge response envelope and exception handling."""
import traceback
from app.store.registry import RegistryError
from app.workspace import WorkspaceError

def ok(data=None):
    return {"ok": True, "data": data}


def err(message):
    return {"ok": False, "error": str(message)}


def guarded(fn):
    """브릿지 메서드에서 새어나간 예외가 JS 쪽 Promise를 깨뜨리지 않게 한다.

    도메인 오류(Collection 없음, Storage에 System이 남아 있음 등)는 사용자에게
    그대로 보여줄 메시지이므로 조용히 돌려보낸다. 예상 못 한 예외만 traceback을
    남긴다 - 둘을 구분하지 않으면 정상 동작 중에도 로그가 traceback으로 뒤덮인다.
    """
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (WorkspaceError, RegistryError, KeyError, ValueError) as e:
            return err(e)
        except Exception as e:  # noqa: BLE001 - 사용자에게 보여줄 오류로 바꾼다
            traceback.print_exc()
            return err(e)
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper
