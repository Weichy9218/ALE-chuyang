"""Exec one checker with Landlock filesystem rules and no network syscalls."""
from __future__ import annotations

import ctypes
import errno
import os
import sys
from pathlib import Path

_CREATE_RULESET = 444
_ADD_RULE = 445
_RESTRICT_SELF = 446
_RULE_PATH_BENEATH = 1
_CREATE_VERSION = 1
_NO_NEW_PRIVS = 38

_EXECUTE = 1 << 0
_WRITE_FILE = 1 << 1
_READ_FILE = 1 << 2
_READ_DIR = 1 << 3
_REMOVE_DIR = 1 << 4
_REMOVE_FILE = 1 << 5
_MAKE_CHAR = 1 << 6
_MAKE_DIR = 1 << 7
_MAKE_REG = 1 << 8
_MAKE_SOCK = 1 << 9
_MAKE_FIFO = 1 << 10
_MAKE_BLOCK = 1 << 11
_MAKE_SYM = 1 << 12
_REFER = 1 << 13
_TRUNCATE = 1 << 14

_READ_ONLY = _EXECUTE | _READ_FILE | _READ_DIR
_READ_WRITE = (
    _READ_ONLY | _WRITE_FILE | _REMOVE_DIR | _REMOVE_FILE | _MAKE_CHAR
    | _MAKE_DIR | _MAKE_REG | _MAKE_SOCK | _MAKE_FIFO | _MAKE_BLOCK
    | _MAKE_SYM | _REFER | _TRUNCATE
)


class _RulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class _PathBeneathAttr(ctypes.Structure):
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


def _syscall(number: int, *args: object) -> int:
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    result = int(libc.syscall(number, *args))
    if result < 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))
    return result


def _add_path(ruleset_fd: int, path: str, access: int) -> None:
    resolved = Path(path).resolve(strict=True)
    if not resolved.is_dir():
        access &= ~_READ_DIR
    fd = os.open(resolved, os.O_PATH | os.O_CLOEXEC)
    try:
        attr = _PathBeneathAttr(access, fd)
        _syscall(
            _ADD_RULE,
            ruleset_fd,
            _RULE_PATH_BENEATH,
            ctypes.byref(attr),
            0,
        )
    finally:
        os.close(fd)


def _restrict_filesystem(executable: list[str], readable: list[str], scratch: str) -> None:
    abi = _syscall(_CREATE_RULESET, 0, 0, _CREATE_VERSION)
    handled = _READ_WRITE
    if abi < 2:
        handled &= ~_REFER
    if abi < 3:
        handled &= ~_TRUNCATE
    attr = _RulesetAttr(handled)
    ruleset_fd = _syscall(_CREATE_RULESET, ctypes.byref(attr), ctypes.sizeof(attr), 0)
    try:
        for path in executable:
            if path and Path(path).exists():
                _add_path(ruleset_fd, path, _READ_ONLY & handled)
        for path in readable:
            if path and Path(path).exists():
                _add_path(ruleset_fd, path, (_READ_FILE | _READ_DIR) & handled)
        for path in ("/dev/null", "/dev/urandom", "/dev/random"):
            if Path(path).exists():
                _add_path(ruleset_fd, path, (_READ_FILE | _WRITE_FILE) & handled)
        _add_path(ruleset_fd, scratch, handled)
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code))
        _syscall(_RESTRICT_SELF, ruleset_fd, 0)
    finally:
        os.close(ruleset_fd)


def _disable_network() -> None:
    lib = ctypes.CDLL("libseccomp.so.2", use_errno=True)
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
    lib.seccomp_rule_add.argtypes = [
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint,
    ]
    lib.seccomp_rule_add.restype = ctypes.c_int
    lib.seccomp_load.argtypes = [ctypes.c_void_p]
    lib.seccomp_load.restype = ctypes.c_int
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    lib.seccomp_release.restype = None
    context = lib.seccomp_init(0x7FFF0000)  # SCMP_ACT_ALLOW
    if not context:
        raise RuntimeError("seccomp_init failed")
    try:
        deny = 0x00050000 | errno.EPERM  # SCMP_ACT_ERRNO(EPERM)
        for name in (
            b"socket", b"connect", b"bind", b"listen",
            b"accept", b"accept4", b"sendto", b"sendmsg", b"sendmmsg",
            b"recvfrom", b"recvmsg", b"recvmmsg",
        ):
            number = lib.seccomp_syscall_resolve_name(name)
            if number >= 0 and lib.seccomp_rule_add(context, deny, number, 0) != 0:
                raise RuntimeError(f"seccomp_rule_add failed for {name.decode()}")
        if lib.seccomp_load(context) != 0:
            raise RuntimeError("seccomp_load failed")
    finally:
        lib.seccomp_release(context)


def main(argv: list[str]) -> int:
    try:
        separator = argv.index("--")
        if separator != 5 or len(argv) <= separator + 1:
            raise ValueError("expected INPUT SOFTWARE OUTPUT CHECKS SCRATCH -- COMMAND")
        input_path, software_path, output_path, checks_path, scratch = argv[:5]
        runtime = [
            "/usr", "/lib", "/lib64", "/opt",
            "/home/user/.local/bin", "/home/user/.cargo/bin",
            f"{input_path}/.venv", f"{input_path}/runtime_env/.venv",
            software_path, checks_path,
        ]
        configs = ["/etc/ld.so.cache", "/etc/alternatives", "/etc/R"]
        _restrict_filesystem(runtime, configs + [input_path, output_path], scratch)
        _disable_network()
        command = argv[separator + 1:]
        os.chdir(checks_path)
        os.environ.clear()
        os.environ.update({
            "PATH": "/home/user/.local/bin:/home/user/.cargo/bin:/usr/local/bin:/usr/bin:/bin",
            "HOME": scratch,
            "TMPDIR": scratch,
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "TZ": "UTC",
            "PYTHONHASHSEED": "0",
            "PYTHONNOUSERSITE": "1",
            "UV_CACHE_DIR": f"{scratch}/uv-cache",
            "UV_NO_SYNC": "1",
            "VERIFIER_INPUT": input_path,
            "VERIFIER_SOFTWARE": software_path,
            "VERIFIER_OUTPUT": output_path,
        })
        os.execvp(command[0], command)
    except Exception as exc:
        print(f"verifier sandbox error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 125
    return 125


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
