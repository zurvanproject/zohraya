"""Windows adapter for the exclusive flock calls used by native Tadash save.
Not a general fcntl implementation. Unsupported operations fail closed.
Byte 0 is reserved as the cooperating-process lock; closing the handle releases it.
"""
import msvcrt
import os
LOCK_EX = 2
LOCK_NB = 4
LOCK_UN = 8


def flock(file, operation):
    fd = file if isinstance(file, int) else file.fileno()
    if operation not in (LOCK_EX, LOCK_EX | LOCK_NB, LOCK_UN):
        raise ValueError("unsupported Windows flock operation")
    position = os.lseek(fd, 0, os.SEEK_CUR)
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        mode = (msvcrt.LK_UNLCK if operation == LOCK_UN else
                msvcrt.LK_NBLCK if operation & LOCK_NB else msvcrt.LK_LOCK)
        msvcrt.locking(fd, mode, 1)
    finally:
        os.lseek(fd, position, os.SEEK_SET)

