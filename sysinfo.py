"""Physical memory available to this machine — read locally, never sent anywhere.

Used by :mod:`budget` to decide how much geometry a click may build.  Nothing here is
network access and nothing is written to disk, so no manifest permission is involved
(``[permissions]`` has no hardware entry at all).

Two platform notes that cost real debugging time:

* **Windows Blender's Python has no ``os.sysconf``** — the POSIX branch is not merely
  "untested" there, it raises ``AttributeError``.  Hence the explicit ctypes branch.
* Use **available physical** memory, not the page-file number.  Windows happily reports
  ~68 GB "available" on a 64 GB box because it counts the page file, and swapping is
  exactly the failure mode we are trying to avoid.
"""

from __future__ import annotations

import ctypes
import os
import sys
import time

__all__ = ["available_bytes", "total_bytes", "read", "clear_cache"]

#: Reading the counters is a syscall; the panel calls this on every redraw.
CACHE_SECONDS = 1.0

#: Undocumented test hooks (see the plan, §10): let a 64 GB machine behave like a 3 GB one.
ENV_FAKE_RAM = "FRACTALFAMILY_FAKE_RAM_MB"

_CACHE = {"stamp": 0.0, "avail": None, "total": None}


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _windows():
    """``(available, total)`` in bytes, or ``(None, None)``."""
    status = _MemoryStatusEx()
    status.dwLength = ctypes.sizeof(_MemoryStatusEx)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None, None
    return float(status.ullAvailPhys), float(status.ullTotalPhys)


def _posix():
    """``(available, total)`` in bytes, or ``(None, None)`` (macOS / Linux)."""
    try:
        page = os.sysconf("SC_PAGE_SIZE")
        avail = os.sysconf("SC_AVPHYS_PAGES") * page
        total = os.sysconf("SC_PHYS_PAGES") * page
        return float(avail), float(total)
    except (AttributeError, ValueError, OSError):
        pass
    try:  # Linux without sysconf support
        values = {}
        with open("/proc/meminfo", "rb") as handle:
            for line in handle:
                key, _, rest = line.partition(b":")
                values[key.strip()] = rest.split()[0]
        return (float(values[b"MemAvailable"]) * 1024.0,
                float(values[b"MemTotal"]) * 1024.0)
    except (OSError, KeyError, IndexError, ValueError):
        return None, None


def _fake():
    """Simulated machine size from the environment (testing only)."""
    text = os.environ.get(ENV_FAKE_RAM)
    if not text:
        return None
    try:
        megabytes = float(text)
    except ValueError:
        return None
    if megabytes <= 0:
        return None
    total = megabytes * 1048576.0
    # "Free" is what is left after the rest of the system: pretend 60% is in use.
    return total * 0.4, total


def read(force: bool = False):
    """``(available_bytes, total_bytes)``; either may be ``None`` when unknown."""
    now = time.monotonic()
    if not force and _CACHE["avail"] is not None and now - _CACHE["stamp"] < CACHE_SECONDS:
        return _CACHE["avail"], _CACHE["total"]

    fake = _fake()
    if fake is not None:
        avail, total = fake
    else:
        reader = _windows if sys.platform == "win32" else _posix
        try:
            avail, total = reader()
        except Exception:  # a broken platform must not take the add-on down
            avail, total = None, None

    _CACHE.update(stamp=now, avail=avail, total=total)
    return avail, total


def available_bytes(force: bool = False):
    """Bytes of *available physical* memory, or ``None`` if the platform is unknown."""
    return read(force)[0]


def total_bytes(force: bool = False):
    """Bytes of installed physical memory, or ``None``."""
    return read(force)[1]


def clear_cache() -> None:
    """Drop the cache (called when a Generate is about to be evaluated)."""
    _CACHE.update(stamp=0.0, avail=None, total=None)
