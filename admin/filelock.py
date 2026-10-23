"""Trava de arquivo não bloqueante, Linux (fcntl) e Windows (msvcrt)."""
import sys


class LockBusy(RuntimeError):
    pass


class FileLock:
    def __init__(self, path):
        self.path = str(path)
        self._fh = None

    def __enter__(self):
        self._fh = open(self.path, "a+")
        try:
            if sys.platform == "win32":
                import msvcrt
                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._fh.close()
            self._fh = None
            raise LockBusy(f"trava ocupada: {self.path}")
        return self

    def __exit__(self, *exc):
        if self._fh:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    self._fh.seek(0)
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            finally:
                self._fh.close()
                self._fh = None
        return False
