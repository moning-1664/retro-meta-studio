"""
storage/mtp_wpd.py
===================
`storage/mtp.py`의 MtpBackend를 Windows WPD(Windows Portable Devices) COM으로 구현한다.

**이 파일만 기기가 있어야 검증할 수 있다.** 그래서 COM 호출을 여기 한 곳에 가두고
나머지(경로 해석·안전한 쓰기·캐시)는 전부 `tests/test_mtp_provider.py`가 가짜
backend로 검증한다. 여기가 틀리면 고칠 곳도 여기 하나다.

확인 방법(기기를 USB로 연결하고 화면 잠금을 풀어 둔 상태에서):

    python -m storage.mtp_wpd                     # 연결된 기기 목록
    python -m storage.mtp_wpd "mtp://<키>/Internal shared storage/ES-DE/gamelists"

## 알아 둘 것

- **MTP에는 덮어쓰기가 없다.** 지우고 새로 만드는 것만 된다 - 안전장치(원본 백업 후
  복구)는 상위(MtpProvider.write_bytes)에 있다.
- **object_id는 세션 안에서만 유효하다.** USB를 다시 꽂으면 전부 바뀐다.
- **COM은 아파트(apartment)에 묶인다.** 작업이 워커 스레드에서 돌기 때문에, 모든 호출을
  여기서 만든 전용 스레드 하나로 몰아 직렬화한다 - 안 그러면 스레드마다 CoInitialize를
  해야 하고 인터페이스 포인터를 넘길 수 없다.
"""

from __future__ import annotations

import hashlib
import logging
import queue
import re
import sys
import threading

from storage.mtp import MtpBackend, MtpDeviceInfo, MtpError, MtpObject

log = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# WPD 상수 - 타입 라이브러리에 없고 헤더에만 있는 값이라 직접 적는다.
# ----------------------------------------------------------------------
_FMT_OBJECT = "{EF6B490D-5CD8-437A-AFFC-DA8B60EE4A3C}"    # WPD_OBJECT_PROPERTIES_V1
_FMT_STORAGE = "{01A3057A-74D6-4E80-BEA7-DC4C212CE50A}"   # WPD_STORAGE_OBJECT_PROPERTIES_V1
_FMT_DEVICE = "{26D4979A-E643-4626-9E2B-736DC0C92FDC}"    # WPD_DEVICE_PROPERTIES_V1
_FMT_CLIENT = "{204D9F0C-2292-4080-9F42-40664E70F859}"    # WPD_CLIENT_INFORMATION_PROPERTIES_V1
_FMT_RESOURCE = "{E81E79BE-34F0-41BF-B53F-F1A06AE87842}"  # WPD_RESOURCE_ATTRIBUTES / DEFAULT

_PID_OBJECT_PARENT_ID = 3
_PID_OBJECT_NAME = 4
_PID_OBJECT_FORMAT = 6
_PID_OBJECT_CONTENT_TYPE = 7
_PID_OBJECT_SIZE = 11
_PID_OBJECT_ORIGINAL_FILE_NAME = 12
_PID_STORAGE_CAPACITY = 4
_PID_STORAGE_FREE = 5
_PID_DEVICE_SERIAL = 9
_PID_CLIENT_NAME = 2

_CONTENT_FOLDER = "{27E2E392-A111-48E0-AB0C-E17705A05F85}"
_CONTENT_FUNCTIONAL = "{99ED0160-17FF-4C44-9D98-1D7A6F941921}"
_FORMAT_UNSPECIFIED = "{30000000-AE6C-4804-98BA-C57B46965FE7}"

_DEVICE_OBJECT_ID = "DEVICE"
_STGM_READ = 0
_STGM_WRITE = 0x00000001
_DELETE_NO_RECURSION = 0
_CHUNK = 256 * 1024


#: 기기 한 번 호출에 허용하는 시간. MTP는 기기가 잠들거나 케이블이 흔들리면 **응답
#: 없이 멈춘다** - 기다리는 쪽을 막아 두면 앱 전체가 굳는다. gamelist 하나를 읽고
#: 쓰는 데 이보다 오래 걸릴 일은 없다.
_CALL_TIMEOUT = 120.0


#: HRESULT RPC_E_CHANGED_MODE - 이 스레드가 이미 다른 방식(STA)으로 COM을 초기화했다.
_RPC_E_CHANGED_MODE = 0x80010106


def _coinitialize():
    """이 스레드를 COM용으로 초기화한다.

    **`import comtypes`는 그 스레드를 암묵적으로 STA로 초기화한다**(comtypes가 import할 때
    `CoInitializeEx(None, COINIT_APARTMENTTHREADED)`를 부른다). 그 뒤에 MTA로 다시 초기화하면
    Windows가 RPC_E_CHANGED_MODE로 거절하는데, 예전에는 이 오류가 "comtypes가 필요합니다"라는
    엉뚱한 안내로 바뀌어 나갔다 - 기기가 탐색기에는 보이는데 앱에서는 목록이 비고 로그도
    남지 않던 원인이다(실사용 피드백).

    그래서 (1) import 전에 MTA를 요청해 두고, (2) 그래도 이미 초기화돼 있으면 그대로 쓴다 -
    COM 호출은 모두 이 스레드 하나에서만 일어나므로 어느 아파트든 상관없다.
    """
    sys.coinit_flags = 0   # COINIT_MULTITHREADED. comtypes가 import 중에 읽는다
    import comtypes
    try:
        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
    except OSError as e:
        if (getattr(e, "winerror", None) or 0) & 0xFFFFFFFF != _RPC_E_CHANGED_MODE:
            raise
        log.info("COM 스레드가 이미 초기화돼 있어 그대로 씁니다(RPC_E_CHANGED_MODE)")


class _ComThread:
    """COM 호출을 전용 스레드 하나로 직렬화한다(아파트 문제를 피하는 가장 단순한 방법).

    **이 스레드가 죽어도 부르는 쪽은 멈추지 않아야 한다.** 초기화(comtypes import,
    CoInitialize)가 실패하면 그 사실을 기억해 두고 이후 호출을 즉시 거절한다 - 그러지
    않으면 comtypes가 없는 환경에서 첫 호출이 영원히 기다린다(실제로 그렇게 멈췄다).
    """

    def __init__(self, initialize=None, on_restart=None):
        #: 테스트가 COM 대신 다른 초기화를 끼울 수 있게 열어 둔다(기기도 comtypes도 없이
        #: "초기화 실패"와 "응답 없음"을 재현하기 위해서다).
        self._initialize = initialize or _coinitialize
        #: 스레드를 새로 세울 때 부른다 - 옛 아파트에서 만든 COM 포인터를 버리라는 신호다.
        self._on_restart = on_restart
        self._lock = threading.Lock()
        self._stuck = False
        self._spawn()

    def _spawn(self):
        """일할 스레드와 그 스레드 전용 큐를 새로 세운다.

        **큐를 스레드에 인자로 넘기는 것이 중요하다.** self._jobs를 읽게 두면, 굳었던
        옛 스레드가 나중에 풀렸을 때 그때의 self._jobs - 즉 **새 큐** - 에서 일감을
        꺼내 간다. 두 스레드가 서로 다른 COM 아파트에서 같은 큐를 나눠 먹게 되는데,
        이건 이 클래스가 존재하는 이유(아파트 하나로 직렬화) 자체를 무너뜨린다.
        """
        self._jobs = queue.Queue()
        self._ready = threading.Event()
        state = {"error": None}
        self._state = state
        self._thread = threading.Thread(
            target=self._loop, args=(self._jobs, self._ready, state),
            name="mtp-com", daemon=True)
        self._thread.start()

    def _loop(self, jobs, ready, state):
        try:
            self._initialize()
        except Exception as e:  # noqa: BLE001
            log.exception("MTP COM 스레드 초기화 실패")
            state["error"] = e
            ready.set()
            return
        ready.set()
        while True:
            func, done, box = jobs.get()
            try:
                box.append(("ok", func()))
            except Exception as e:  # noqa: BLE001 - 호출한 스레드로 그대로 옮겨 준다
                box.append(("error", e))
            finally:
                done.set()

    def _restart(self):
        """굳은 스레드를 버리고 새로 세운다.

        옛 스레드는 응답 없는 COM 호출 안에 갇혀 있어 깨울 방법이 없다 - daemon이라
        프로세스가 끝날 때 함께 사라진다. 여기서 하는 일은 **그쪽을 쳐다보지 않는 것**이다.
        """
        self._stuck = False
        if self._on_restart:
            self._on_restart()
        self._spawn()

    def run(self, func, timeout=_CALL_TIMEOUT):
        with self._lock:
            # 지난 호출이 timeout으로 끝났다면 그 스레드는 아직 그 호출 안에 갇혀 있다.
            # 그 위에 일감을 더 쌓으면 뒤에 줄만 서다가 똑같이 timeout이 난다 - 기기를
            # 다시 꽂아도 앱을 껐다 켜기 전에는 MTP가 영영 안 되던 이유가 이것이다.
            if self._stuck:
                self._restart()
            jobs, ready, state = self._jobs, self._ready, self._state

        ready.wait(10)
        if state["error"] is not None:
            # 원인을 그대로 알린다. 예전에는 무슨 오류든 "comtypes가 필요합니다"로 답해서
            # 설치된 사람에게 엉뚱한 일을 시켰다.
            cause = state["error"]
            if isinstance(cause, ImportError):
                message = ("MTP 연결에는 comtypes가 필요합니다. `pip install comtypes` 후 "
                           "다시 시도해주세요.")
            else:
                message = f"MTP(COM)를 초기화하지 못했습니다: {cause}"
            raise MtpError(message) from cause
        done, box = threading.Event(), []
        jobs.put((func, done, box))
        if not done.wait(timeout):
            self._stuck = True   # 다음 호출이 스레드를 새로 세운다
            raise MtpError(
                "기기가 응답하지 않습니다. 화면 잠금을 풀고 USB 연결을 '파일 전송(MTP)'으로 "
                "둔 뒤 다시 시도해주세요.")
        kind, value = box[0]
        if kind == "error":
            raise value
        return value


def _require_comtypes():
    try:
        import comtypes  # noqa: F401
        import comtypes.client  # noqa: F401
    except ImportError as e:
        # 빌드된 exe에서 이 길로 오면 대개 "comtypes가 안 깔렸다"가 아니라
        # **번들에서 빠졌다**는 뜻이다(build_web.bat의 --hidden-import 참고) -
        # 화면 안내와 다른 진짜 원인을 로그에는 남겨 둔다.
        log.warning("comtypes를 불러오지 못했습니다(frozen=%s): %s",
                    getattr(sys, "frozen", False), e)
        raise MtpError(
            "MTP 연결에는 comtypes가 필요합니다. `pip install comtypes` 후 다시 시도해주세요."
        ) from e


# ----------------------------------------------------------------------
# IPortableDeviceManager 직접 호출 (기기 열거 전용)
# ----------------------------------------------------------------------
_CLSID_PORTABLE_DEVICE_MANAGER = "{0AF10CEC-2ECD-4B92-9581-34F6AE0637F3}"
_IID_PORTABLE_DEVICE_MANAGER = "{A1567595-4C2F-4574-A6FA-ECEF917B9A40}"
_CLSCTX_INPROC_SERVER = 1
#: IPortableDeviceManager의 vtable 위치(IUnknown 0-2 다음).
_VT_RELEASE, _VT_GET_DEVICES, _VT_REFRESH, _VT_FRIENDLY_NAME = 2, 3, 4, 5


def _guid(text):
    import ctypes
    value = (ctypes.c_byte * 16)()
    ole32 = ctypes.WinDLL("ole32.dll")
    ole32.CLSIDFromString.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p]
    ole32.CLSIDFromString.restype = ctypes.c_long
    hr = ole32.CLSIDFromString(text, ctypes.byref(value))
    if hr != 0:
        raise OSError(f"CLSIDFromString 실패: 0x{hr & 0xFFFFFFFF:08X}")
    return value


def _raw_enumerate() -> list[tuple[str, str]]:
    """(기기 ID, 표시 이름) 목록. 호출한 스레드는 이미 COM이 초기화돼 있어야 한다.

    새로 꽂은 기기가 목록에 잡히려면 RefreshDeviceList를 먼저 불러야 한다 - 안 부르면 앱이
    켜진 뒤에 꽂은 기기는 탐색기에는 보이는데 여기서는 0대로 나온다.
    """
    import ctypes
    ole32 = ctypes.WinDLL("ole32.dll")
    ole32.CoCreateInstance.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong,
                                       ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    ole32.CoCreateInstance.restype = ctypes.c_long
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    clsid, iid = _guid(_CLSID_PORTABLE_DEVICE_MANAGER), _guid(_IID_PORTABLE_DEVICE_MANAGER)
    obj = ctypes.c_void_p()
    hr = ole32.CoCreateInstance(ctypes.byref(clsid), None, _CLSCTX_INPROC_SERVER,
                                ctypes.byref(iid), ctypes.byref(obj))
    if hr != 0 or not obj.value:
        raise MtpError(f"Windows 휴대용 장치(WPD)를 열지 못했습니다: 0x{hr & 0xFFFFFFFF:08X}")
    table = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents

    def method(slot, *argtypes):
        return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(table[slot])

    try:
        hr = method(_VT_REFRESH)(obj)
        log.info("WPD RefreshDeviceList -> 0x%08X", hr & 0xFFFFFFFF)
        get_devices = method(_VT_GET_DEVICES, ctypes.POINTER(ctypes.c_void_p),
                             ctypes.POINTER(ctypes.c_ulong))
        count = ctypes.c_ulong(0)
        hr = get_devices(obj, None, ctypes.byref(count))
        if hr != 0:
            raise MtpError(f"WPD 기기 수를 읽지 못했습니다: 0x{hr & 0xFFFFFFFF:08X}")
        if count.value == 0:
            return []
        ids = (ctypes.c_void_p * count.value)()
        hr = get_devices(obj, ids, ctypes.byref(count))
        if hr != 0:
            raise MtpError(f"WPD 기기 목록을 읽지 못했습니다: 0x{hr & 0xFFFFFFFF:08X}")
        friendly = method(_VT_FRIENDLY_NAME, ctypes.c_wchar_p, ctypes.c_void_p,
                          ctypes.POINTER(ctypes.c_ulong))
        found = []
        for pointer in list(ids)[:count.value]:
            if not pointer:
                continue
            device_id = ctypes.wstring_at(pointer)
            ole32.CoTaskMemFree(pointer)      # 문서: 호출자가 해제한다(복사한 뒤에)
            length = ctypes.c_ulong(0)
            name = ""
            if friendly(obj, device_id, None, ctypes.byref(length)) == 0 and length.value:
                buffer = ctypes.create_unicode_buffer(length.value)
                if friendly(obj, device_id, buffer, ctypes.byref(length)) == 0:
                    name = buffer.value
            found.append((device_id, name))
        return found
    finally:
        try:
            method(_VT_RELEASE)(obj)
        except Exception:  # noqa: BLE001 - 해제 실패가 결과를 바꾸지 않는다
            pass


class WpdBackend(MtpBackend):
    def __init__(self):
        self._com = _ComThread(on_restart=self._forget_com_state)
        self._api = None            # portabledeviceapi 타입 라이브러리 모듈
        self._types = None          # portabledevicetypes 모듈
        self._key_type = None       # PROPERTYKEY 구조체 타입(생성된 이름이 버전마다 다르다)
        self._device_ids: dict[str, str] = {}    # 기기키 -> WPD device id
        self._opened: dict[str, object] = {}     # WPD device id -> IPortableDevice

    def _forget_com_state(self):
        """COM 스레드를 새로 세울 때 그 전 아파트에서 만든 것을 전부 버린다.

        열어 둔 IPortableDevice는 **그것을 만든 아파트에 묶인 포인터**다. 스레드가
        바뀌었는데 그대로 쓰면 기기가 멀쩡해도 호출이 실패한다 - 다음 요청 때 기기를
        다시 열도록 잊는다. object_id도 세션 안에서만 유효하므로 함께 버린다.
        """
        self._api = None
        self._types = None
        self._key_type = None
        self._device_ids = {}
        self._opened = {}

    # --- COM 준비 --------------------------------------------------------
    def _load(self):
        if self._api is not None:
            return
        _require_comtypes()
        import comtypes.client

        # **패키징된 exe에서는 디스크에 캐시하지 않는다.** comtypes.client.GetModule은
        # 처음 부를 때 Windows 타입 라이브러리를 파이썬 래퍼 코드로 변환해 comtypes
        # 설치 폴더 밑(comtypes/gen)에 .py로 캐시해 둔다 - 다음 실행에서 다시 만들지
        # 않으려는 최적화다. 소스로 돌릴 때는 그 폴더가 진짜 site-packages라 문제
        # 없지만, PyInstaller onefile exe는 매번 새 임시 폴더에 풀리므로 캐시가 어차피
        # 안 남고, 일부 환경(백신이 임시 폴더 쓰기를 막는 경우)에서는 그 쓰기
        # 시도 자체가 실패해 "Windows Portable Devices를 불러오지 못했습니다"로
        # 보인다. gen_dir을 None으로 두면 디스크에 쓰지 않고 메모리에서만 코드를
        # 생성한다 - 매번 새로 만드느라 조금 느리지만(수십 ms) 확실하다.
        if getattr(sys, "frozen", False):
            comtypes.client.gen_dir = None

        try:
            self._api = comtypes.client.GetModule("portabledeviceapi.dll")
            self._types = comtypes.client.GetModule("portabledevicetypes.dll")
        except Exception as e:  # noqa: BLE001
            log.exception("WPD 타입 라이브러리 적재 실패(frozen=%s)", getattr(sys, "frozen", False))
            raise MtpError(f"Windows Portable Devices를 불러오지 못했습니다: {e}") from e
        log.info("WPD 타입 라이브러리 적재 완료")

        for name in ("_tagpropertykey", "tagPROPERTYKEY", "PROPERTYKEY", "_PROPERTYKEY"):
            self._key_type = getattr(self._types, name, None) or getattr(self._api, name, None)
            if self._key_type is not None:
                break
        if self._key_type is None:
            raise MtpError("WPD PROPERTYKEY 타입을 찾지 못했습니다(Windows 버전 확인 필요).")

    def _key(self, fmtid: str, pid: int):
        import comtypes
        key = self._key_type()
        key.fmtid = comtypes.GUID(fmtid)
        key.pid = pid
        return key

    def _values(self):
        import comtypes.client
        return comtypes.client.CreateObject(
            self._types.PortableDeviceValues, interface=self._api.IPortableDeviceValues)

    def _client_info(self):
        values = self._values()
        values.SetStringValue(self._key(_FMT_CLIENT, _PID_CLIENT_NAME), "RetroMeta Studio")
        return values

    def _device(self, device_key: str):
        """기기키로 열린 IPortableDevice를 얻는다. 필요하면 목록을 다시 훑는다."""
        device_id = self._device_ids.get(device_key)
        if device_id is None:
            self._scan_devices()
            device_id = self._device_ids.get(device_key)
        if device_id is None:
            raise MtpError(f"연결된 기기를 찾지 못했습니다: {device_key}")
        opened = self._opened.get(device_id)
        if opened is None:
            import comtypes.client
            opened = comtypes.client.CreateObject(
                self._api.PortableDevice, interface=self._api.IPortableDevice)
            try:
                opened.Open(device_id, self._client_info())
            except Exception as e:  # noqa: BLE001
                raise MtpError(
                    f"기기를 열지 못했습니다({device_key}). 화면 잠금을 풀고 USB 연결을 "
                    f"'파일 전송(MTP)'으로 두었는지 확인해주세요: {e}") from e
            self._opened[device_id] = opened
        return opened

    def _scan_devices(self) -> list[MtpDeviceInfo]:
        self._load()
        # 기기 목록은 IPortableDeviceManager를 **vtable로 직접** 부른다(아래 _raw_*).
        # comtypes 1.4의 GetDevices/GetDeviceFriendlyName은 [in, out] DWORD를 인자가 아니라
        # 반환값으로 바꿔서 예전 방식(`byref(count)`)이 TypeError로 죽는다 - 그 오류가
        # 기기 목록을 통째로 비게 했다. 문서화된 ABI를 직접 부르면 comtypes 버전과 무관하다.
        raw = _raw_enumerate()
        # Windows가 몇 대로 보는지를 그대로 남긴다 - 탐색기에 기기가 보이는데
        # 여기서 0이면 MTP(미디어 장치)가 아니라 다른 모드로 붙어 있다는 뜻이다
        # (충전 전용/사진 전송(PTP) 등). 그 구분을 로그 없이는 할 수 없다.
        log.info("WPD 기기 열거: %d대", len(raw))
        found = []
        self._device_ids = {}
        for device_id, name in raw:
            name = name or "Android Device"
            key = self._device_key(device_id, name)
            self._device_ids[key] = device_id
            log.info("WPD 기기: name=%s key=%s id=%s", name, key, device_id)
            found.append(MtpDeviceInfo(key=key, name=name, device_id=device_id))
        return found

    def _device_key(self, device_id: str, name: str) -> str:
        """경로에 쓸 기기 키. 일련번호를 쓰고, 못 읽으면 기기 ID를 요약해 대신한다.

        WPD 기기 ID(`\\\\?\\usb#vid_...`)를 그대로 쓸 수 없다 - 경로에 못 쓰는 문자가
        섞여 있고, 일련번호를 안 주는 기기에서는 포트를 바꿔 꽂으면 달라진다.

        **이 키는 반드시 재실행해도 같은 값이어야 한다.** Collection이 저장하는 경로가
        `mtp://<이 키>/...`라서, 같은 기기가 다음 실행에서 다른 키를 받으면 저장해 둔
        Collection이 통째로 다른 기기를 가리키게 된다. 예전에는 fallback이 파이썬
        내장 `hash()`였는데, 문자열 해시는 프로세스마다 시드가 달라(PEP 456) 앱을
        켤 때마다 값이 바뀌었다 - 그래서 시드를 타지 않는 SHA-256으로 요약한다.
        """
        serial = None
        try:
            import comtypes.client
            device = comtypes.client.CreateObject(
                self._api.PortableDevice, interface=self._api.IPortableDevice)
            device.Open(device_id, self._client_info())
            properties = device.Content().Properties()
            keys = comtypes.client.CreateObject(
                self._types.PortableDeviceKeyCollection,
                interface=self._api.IPortableDeviceKeyCollection)
            keys.Add(self._key(_FMT_DEVICE, _PID_DEVICE_SERIAL))
            values = properties.GetValues(_DEVICE_OBJECT_ID, keys)
            serial = values.GetStringValue(self._key(_FMT_DEVICE, _PID_DEVICE_SERIAL))
            self._opened[device_id] = device
        except Exception:  # noqa: BLE001 - 일련번호를 안 주는 기기가 있다
            serial = None
        if not serial:
            digest = hashlib.sha256(device_id.encode("utf-8")).hexdigest()[:10]
            serial = f"{name}-{digest}"
        raw = serial
        return re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-") or "device"

    # --- 객체 읽기 -------------------------------------------------------
    def _object_values(self, device, object_id):
        import comtypes.client
        properties = device.Content().Properties()
        keys = comtypes.client.CreateObject(
            self._types.PortableDeviceKeyCollection,
            interface=self._api.IPortableDeviceKeyCollection)
        for fmtid, pid in ((_FMT_OBJECT, _PID_OBJECT_NAME),
                           (_FMT_OBJECT, _PID_OBJECT_ORIGINAL_FILE_NAME),
                           (_FMT_OBJECT, _PID_OBJECT_CONTENT_TYPE),
                           (_FMT_OBJECT, _PID_OBJECT_SIZE)):
            keys.Add(self._key(fmtid, pid))
        return properties.GetValues(object_id, keys)

    def _describe(self, device, object_id) -> MtpObject:
        values = self._object_values(device, object_id)
        name = self._string(values, _FMT_OBJECT, _PID_OBJECT_ORIGINAL_FILE_NAME) \
            or self._string(values, _FMT_OBJECT, _PID_OBJECT_NAME) or object_id
        content_type = ""
        try:
            guid = values.GetGuidValue(self._key(_FMT_OBJECT, _PID_OBJECT_CONTENT_TYPE))
            content_type = f"{{{str(guid).strip('{}').upper()}}}"
        except Exception:  # noqa: BLE001
            content_type = ""
        size = 0
        try:
            size = int(values.GetUnsignedLargeIntegerValue(self._key(_FMT_OBJECT, _PID_OBJECT_SIZE)))
        except Exception:  # noqa: BLE001 - 폴더는 크기가 없다
            size = 0
        is_dir = content_type in (_CONTENT_FOLDER.upper(), _CONTENT_FUNCTIONAL.upper())
        # 수정 시각은 기기마다 형식이 제각각이라 읽지 않는다 - 0이면 상위가 "바뀐 것으로
        # 보고 다시 읽기"를 택하므로(스캔 시그니처) 안전한 쪽이다.
        return MtpObject(object_id=object_id, name=name, is_dir=is_dir, size=size, mtime_ns=0)

    def _string(self, values, fmtid, pid):
        """문자열 속성 하나. 기기가 그 속성을 안 주면 None - 예외를 밖으로 내지 않는다."""
        try:
            return values.GetStringValue(self._key(fmtid, pid)) or None
        except Exception:  # noqa: BLE001
            return None

    # --- MtpBackend ------------------------------------------------------
    def devices(self) -> list[MtpDeviceInfo]:
        return self._com.run(self._scan_devices)

    def children(self, device_key, object_id):
        def work():
            self._load()
            device = self._device(device_key)
            content = device.Content()
            parent = object_id if object_id is not None else _DEVICE_OBJECT_ID
            try:
                enumerator = content.EnumObjects(0, parent, None)
            except Exception as e:  # noqa: BLE001
                raise MtpError(f"목록을 읽지 못했습니다: {e}") from e
            out = []
            while True:
                ids, fetched = enumerator.Next(32)
                if not fetched:
                    break
                for child_id in list(ids)[:fetched]:
                    try:
                        out.append(self._describe(device, child_id))
                    except Exception:  # noqa: BLE001 - 하나가 이상해도 목록 전체를 버리지 않는다
                        continue
            return out
        return self._com.run(work)

    def read(self, device_key, object_id) -> bytes:
        def work():
            import ctypes
            self._load()
            device = self._device(device_key)
            stream, _optimal = device.Content().Transfer().GetStream(
                object_id, self._key(_FMT_RESOURCE, 0), _STGM_READ, ctypes.pointer(ctypes.c_ulong(0)))
            chunks = []
            while True:
                data = stream.RemoteRead(_CHUNK)
                payload = bytes(data[0])[:data[1]] if isinstance(data, tuple) else bytes(data)
                if not payload:
                    break
                chunks.append(payload)
            return b"".join(chunks)
        return self._com.run(work)

    def create(self, device_key, parent_id, name, data: bytes) -> str:
        def work():
            import ctypes
            import comtypes
            self._load()
            device = self._device(device_key)
            values = self._values()
            values.SetStringValue(self._key(_FMT_OBJECT, _PID_OBJECT_PARENT_ID),
                                  parent_id or _DEVICE_OBJECT_ID)
            values.SetStringValue(self._key(_FMT_OBJECT, _PID_OBJECT_NAME), name)
            values.SetStringValue(self._key(_FMT_OBJECT, _PID_OBJECT_ORIGINAL_FILE_NAME), name)
            values.SetUnsignedLargeIntegerValue(self._key(_FMT_OBJECT, _PID_OBJECT_SIZE), len(data))
            values.SetGuidValue(self._key(_FMT_OBJECT, _PID_OBJECT_FORMAT),
                                comtypes.GUID(_FORMAT_UNSPECIFIED))
            optimal = ctypes.c_ulong(0)
            stream, _cookie = device.Content().Transfer().CreateObjectWithPropertiesAndData(
                values, ctypes.pointer(optimal), None)
            view = memoryview(data)
            for start in range(0, len(data), _CHUNK):
                stream.RemoteWrite(view[start:start + _CHUNK].tobytes(), min(_CHUNK, len(data) - start))
            stream.Commit(0)
            return name
        return self._com.run(work)

    def create_folder(self, device_key, parent_id, name) -> str:
        def work():
            import comtypes
            self._load()
            device = self._device(device_key)
            values = self._values()
            values.SetStringValue(self._key(_FMT_OBJECT, _PID_OBJECT_PARENT_ID),
                                  parent_id or _DEVICE_OBJECT_ID)
            values.SetStringValue(self._key(_FMT_OBJECT, _PID_OBJECT_NAME), name)
            values.SetStringValue(self._key(_FMT_OBJECT, _PID_OBJECT_ORIGINAL_FILE_NAME), name)
            values.SetGuidValue(self._key(_FMT_OBJECT, _PID_OBJECT_CONTENT_TYPE),
                                comtypes.GUID(_CONTENT_FOLDER))
            return device.Content().CreateObjectWithPropertiesOnly(values, None)
        return self._com.run(work)

    def delete(self, device_key, object_id) -> None:
        def work():
            import comtypes.client
            self._load()
            device = self._device(device_key)
            ids = comtypes.client.CreateObject(
                self._types.PortableDevicePropVariantCollection,
                interface=self._api.IPortableDevicePropVariantCollection)
            variant = self._types.tag_inner_PROPVARIANT() if hasattr(self._types, "tag_inner_PROPVARIANT") else None
            if variant is None:
                raise MtpError("이 Windows에서는 삭제에 필요한 타입을 찾지 못했습니다.")
            variant.vt = 31   # VT_LPWSTR
            variant.data.pwszVal = object_id
            ids.Add(variant)
            device.Content().Delete(_DELETE_NO_RECURSION, ids, None)
        return self._com.run(work)

    def storage_info(self, device_key, object_id):
        def work():
            import comtypes.client
            self._load()
            device = self._device(device_key)
            properties = device.Content().Properties()
            keys = comtypes.client.CreateObject(
                self._types.PortableDeviceKeyCollection,
                interface=self._api.IPortableDeviceKeyCollection)
            keys.Add(self._key(_FMT_STORAGE, _PID_STORAGE_CAPACITY))
            keys.Add(self._key(_FMT_STORAGE, _PID_STORAGE_FREE))
            try:
                values = properties.GetValues(object_id, keys)
                capacity = int(values.GetUnsignedLargeIntegerValue(
                    self._key(_FMT_STORAGE, _PID_STORAGE_CAPACITY)))
                free = int(values.GetUnsignedLargeIntegerValue(
                    self._key(_FMT_STORAGE, _PID_STORAGE_FREE)))
                return (capacity, free)
            except Exception:  # noqa: BLE001 - 용량은 Unknown이어도 된다(스펙 §5)
                return (None, None)
        return self._com.run(work)


def _self_check(argv):
    """`python -m storage.mtp_wpd [경로]` - 기기가 있어야 의미가 있는 확인용."""
    from storage.mtp import MtpProvider, join_path

    backend = WpdBackend()
    devices = backend.devices()
    if not devices:
        print("연결된 MTP 기기가 없습니다. USB를 '파일 전송(MTP)'으로 두고 화면 잠금을 풀어주세요.")
        return 1
    print("연결된 기기:")
    for device in devices:
        print(f"  키={device.key}  이름={device.name}")
        print(f"     (WPD id: {device.device_id})")

    provider = MtpProvider(backend)
    path = argv[1] if len(argv) > 1 else join_path(devices[0].key, [])
    print(f"\n{path} 목록:")
    entries = provider.scandir(path)
    if not entries:
        print("  (비어 있거나 읽지 못했습니다)")
    for entry in entries:
        kind = "폴더" if entry.is_dir else f"{entry.size:,} bytes"
        print(f"  {entry.name}  [{kind}]")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_self_check(sys.argv))
