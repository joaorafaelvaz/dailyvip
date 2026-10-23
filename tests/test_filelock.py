import pytest


def test_trava_exclusiva(tmp_path):
    from admin.filelock import FileLock, LockBusy
    p = tmp_path / "x.lock"
    with FileLock(p):
        with pytest.raises(LockBusy):
            with FileLock(p):
                pass
    with FileLock(p):   # liberada
        pass
