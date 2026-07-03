"""AC-X-k: the log file rotates by size rather than growing without bound."""

import logging

from meetingnotes.logging.setup import LOG_NAME, configure_logging


def test_ac_x_k_log_rotation(tmp_path):
    logs = tmp_path / "logs"
    configure_logging(logs, max_bytes=2_000, backup_count=2)
    logger = logging.getLogger("meetingnotes.rotation")

    for i in range(200):
        logger.info("filler record number %d to push the file past its size limit", i)

    current = logs / LOG_NAME
    rotated = logs / (LOG_NAME + ".1")
    assert rotated.exists(), "rotation occurred"
    assert current.stat().st_size <= 2_100, "the live file stays bounded"

    # Older lines moved into the rotated file: the earliest surviving record
    # in the live file is newer than those in the rotated one.
    def first_index(path):
        first = path.read_text().splitlines()[0]
        return int(first.rsplit("number ", 1)[1].split(" ")[0])

    assert first_index(rotated) < first_index(current)
    # Nothing grew without bound: only the configured backups exist.
    assert not (logs / (LOG_NAME + ".3")).exists()
