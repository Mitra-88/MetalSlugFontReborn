"""Sample profiler for the image generation path.

Run from the repo root:
    .venv/Scripts/python.exe Tools/sample_profiler.py

Reports cProfile hot spots, tracemalloc allocation hot spots, and process
memory growth over repeated renders (leak check). Benchmark here before and
after any performance change.
"""

import cProfile
import io
import pstats
import sys
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "Src"))

from image_generation import generate_image, get_font_paths

SHORT_TEXT = "Hello World!"
LONG_TEXT = "METAL SLUG IS PEAK! " * 100
FONT_PATHS = get_font_paths(1, "Blue")


def render(text, runs=1):
    for _ in range(runs):
        generate_image(text, "prof.png", FONT_PATHS, None, return_image=True)


def profile_hot_spots(text, label):
    profiler = cProfile.Profile()
    profiler.enable()
    render(text)
    profiler.disable()
    out = io.StringIO()
    pstats.Stats(profiler, stream=out).sort_stats("cumulative").print_stats(12)
    lines = out.getvalue().splitlines()
    print(f"--- cProfile: {label} ---")
    print("\n".join(line for line in lines[4:24] if line.strip()))


def profile_memory(text, label):
    tracemalloc.start()
    render(text)
    current, peak = tracemalloc.get_traced_memory()
    snapshot = tracemalloc.take_snapshot()
    top = snapshot.statistics("lineno")[:5]
    tracemalloc.stop()
    print(f"--- tracemalloc: {label} ---")
    print(f"python heap: current {current / 1e6:.1f} MB, peak {peak / 1e6:.1f} MB")
    for stat in top:
        print(f"  {stat.size / 1e6:6.2f} MB  {stat.traceback[0]}")


def process_memory_mb():
    if sys.platform != "win32":
        return None
    import ctypes
    import ctypes.wintypes as wt

    class PMC(ctypes.Structure):
        _fields_ = [
            ("cb", wt.DWORD),
            ("PageFaultCount", wt.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    k32 = ctypes.windll.kernel32
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    psapi = ctypes.windll.psapi
    psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(PMC),
        wt.DWORD,
    ]
    handle = k32.GetCurrentProcess()
    if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(pmc), pmc.cb):
        return None
    return pmc.WorkingSetSize / 1e6


def leak_check():
    print("--- repeated render growth (leak check, 300 renders) ---")
    start = process_memory_mb()
    marks = []
    for i in range(1, 301):
        render(LONG_TEXT)
        if i % 50 == 0:
            mb = process_memory_mb()
            if mb is not None:
                marks.append((i, mb))
    if start is None:
        print("process RSS unavailable on this platform, use tracemalloc sections")
        return
    print(f"start RSS {start:.1f} MB")
    for i, mb in marks:
        print(f"after {i:3d} renders: RSS {mb:.1f} MB")


if __name__ == "__main__":
    render(SHORT_TEXT, runs=2)
    profile_hot_spots(SHORT_TEXT, "typical text, warm cache")
    profile_hot_spots(LONG_TEXT, "2000 chars")
    profile_memory(LONG_TEXT, "2000 chars")
    leak_check()
