import tempfile
from pathlib import Path

from engine_alpha.core.paths import REPORTS, LOGS, DATA


def _check_dir(path: Path) -> None:
    assert path.exists(), f"Path missing: {path}"
    with tempfile.NamedTemporaryFile(dir=path, delete=True) as tmp:
        tmp.write(b"ok")
        tmp.flush()


def test_reports_logs_data_writable():
    for path in (REPORTS, LOGS, DATA):
        _check_dir(path)
