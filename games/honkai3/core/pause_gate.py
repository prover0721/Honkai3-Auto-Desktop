"""Shared pause gate for all Honkai3 automation processes in this Windows session."""

import ctypes
from contextlib import contextmanager


_kernel32 = ctypes.windll.kernel32
_kernel32.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_wchar_p]
_kernel32.CreateEventW.restype = ctypes.c_void_p
_kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
_kernel32.CreateMutexW.restype = ctypes.c_void_p
_kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
_kernel32.WaitForSingleObject.restype = ctypes.c_ulong
_kernel32.SetEvent.argtypes = [ctypes.c_void_p]
_kernel32.ResetEvent.argtypes = [ctypes.c_void_p]
_kernel32.ReleaseMutex.argtypes = [ctypes.c_void_p]

_RUN_EVENT = _kernel32.CreateEventW(None, True, True, "Local\\GameHub_Honkai3_Run_v1")
_INPUT_MUTEX = _kernel32.CreateMutexW(None, False, "Local\\GameHub_Honkai3_Input_v1")
if not _RUN_EVENT or not _INPUT_MUTEX:
    raise OSError("无法建立崩坏3自动化暂停同步对象")

_WAIT_OBJECT_0 = 0
_WAIT_ABANDONED = 0x80
_WAIT_TIMEOUT = 0x102
_INFINITE = 0xFFFFFFFF


def _lock_input():
    result = _kernel32.WaitForSingleObject(_INPUT_MUTEX, _INFINITE)
    if result not in (_WAIT_OBJECT_0, _WAIT_ABANDONED):
        raise OSError(f"等待崩坏3输入锁失败: {result}")


def is_paused() -> bool:
    return _kernel32.WaitForSingleObject(_RUN_EVENT, 0) == _WAIT_TIMEOUT


def pause() -> None:
    # Wait for an in-flight mouse down/up pair before reporting pause complete.
    _lock_input()
    try:
        if not _kernel32.ResetEvent(_RUN_EVENT):
            raise OSError("暂停崩坏3自动化失败")
    finally:
        _kernel32.ReleaseMutex(_INPUT_MUTEX)


def resume() -> None:
    _lock_input()
    try:
        if not _kernel32.SetEvent(_RUN_EVENT):
            raise OSError("恢复崩坏3自动化失败")
    finally:
        _kernel32.ReleaseMutex(_INPUT_MUTEX)


def wait_until_resumed() -> None:
    result = _kernel32.WaitForSingleObject(_RUN_EVENT, _INFINITE)
    if result != _WAIT_OBJECT_0:
        raise OSError(f"等待崩坏3自动化恢复失败: {result}")


@contextmanager
def input_permit():
    """Allow one complete input action; pause waits for it to finish."""
    while True:
        wait_until_resumed()
        _lock_input()
        if _kernel32.WaitForSingleObject(_RUN_EVENT, 0) == _WAIT_OBJECT_0:
            break
        _kernel32.ReleaseMutex(_INPUT_MUTEX)
    try:
        yield
    finally:
        _kernel32.ReleaseMutex(_INPUT_MUTEX)
