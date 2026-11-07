"""Run an offline review command with Linux network syscalls denied."""
import ctypes
import ctypes.util
import errno
import os
import sys

library = ctypes.util.find_library('seccomp')
if not library:
    raise SystemExit('libseccomp unavailable; refusing unguarded test execution')
lib = ctypes.CDLL(library, use_errno=True)
lib.seccomp_init.argtypes = [ctypes.c_uint32]
lib.seccomp_init.restype = ctypes.c_void_p
lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
lib.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
lib.seccomp_rule_add.restype = ctypes.c_int
lib.seccomp_load.argtypes = [ctypes.c_void_p]
lib.seccomp_load.restype = ctypes.c_int
lib.seccomp_release.argtypes = [ctypes.c_void_p]
context = lib.seccomp_init(0x7fff0000)
if not context:
    raise SystemExit('seccomp initialization failed')
try:
    for syscall in ('socket', 'connect', 'sendto', 'sendmsg', 'sendmmsg', 'socketcall'):
        number = lib.seccomp_syscall_resolve_name(syscall.encode())
        if number >= 0:
            result = lib.seccomp_rule_add(context, 0x00050000 | errno.EPERM, number, 0)
            if result != 0:
                raise SystemExit('seccomp rule failed: ' + syscall)
    if lib.seccomp_load(context) != 0:
        raise SystemExit('seccomp load failed')
finally:
    lib.seccomp_release(context)
environment = dict(os.environ)
for name in ('OPENAI_API_KEY','OPENAI_BASE_URL','GITHUB_TOKEN','GH_TOKEN','GH_HOST_TOKEN',
             'ANTHROPIC_API_KEY','GOOGLE_API_KEY','GEMINI_API_KEY'):
    environment.pop(name, None)
os.execve(sys.executable, [sys.executable, *sys.argv[1:]], environment)
