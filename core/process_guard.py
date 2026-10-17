"""Own a Windows service tree, including grandchildren, for an Electron lifetime.

The guard joins a kill-on-close job BEFORE spawning anything. Only it owns the
job handle. Both forced guard termination and parent death release the tree.
"""
import ctypes
from ctypes import wintypes as w
import os
import subprocess
import sys


class Limits(ctypes.Structure):
    _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                ("flags", w.DWORD), ("minimum", ctypes.c_size_t), ("maximum", ctypes.c_size_t),
                ("active", w.DWORD), ("affinity", ctypes.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]


class Counters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [("basic", Limits), ("io", Counters), ("process_memory", ctypes.c_size_t),
                ("job_memory", ctypes.c_size_t), ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]


def supervise(parent_pid, command):
    if os.name != "nt":
        return subprocess.call(command)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "OpenProcess": ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
        "CreateJobObjectW": ([ctypes.c_void_p, w.LPCWSTR], w.HANDLE),
        "GetCurrentProcess": ([], w.HANDLE),
        "SetInformationJobObject": ([w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD], w.BOOL),
        "AssignProcessToJobObject": ([w.HANDLE, w.HANDLE], w.BOOL),
        "WaitForSingleObject": ([w.HANDLE, w.DWORD], w.DWORD),
        "CloseHandle": ([w.HANDLE], w.BOOL),
    }
    for name, (args, result) in signatures.items():
        function = getattr(kernel, name)
        function.argtypes, function.restype = args, result
    owner = kernel.OpenProcess(0x00100000, False, parent_pid)  # SYNCHRONIZE, not termination rights.
    if not owner:
        raise ctypes.WinError(ctypes.get_last_error())
    # Leave this non-inheritable handle open until process exit. Closing it while
    # still running would also terminate this guard, which belongs to the job.
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    limits = ExtendedLimits()
    limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if kernel.WaitForSingleObject(owner, 0) == 0:
            return 0
        child = subprocess.Popen(command, stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        while child.poll() is None:
            status = kernel.WaitForSingleObject(owner, 100)
            if status == 0:
                return 0
            if status != 258:  # WAIT_TIMEOUT
                raise ctypes.WinError(ctypes.get_last_error())
        return child.returncode
    finally:
        kernel.CloseHandle(owner)


if __name__ == "__main__":
    try:
        sys.exit(supervise(int(sys.argv[1]), sys.argv[2:]))
    except Exception as error:
        print("WileyAI process guard: " + str(error), file=sys.stderr, flush=True)
        sys.exit(1)
