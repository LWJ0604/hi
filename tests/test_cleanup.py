"""Close only file handlers owned by a test's temporary directory."""
import logging
from pathlib import Path


def close_test_logs(root):
    root = Path(root).resolve()
    for logger in list(logging.Logger.manager.loggerDict.values()):
        if not isinstance(logger, logging.Logger):
            continue
        for handler in list(logger.handlers):
            if isinstance(handler, logging.FileHandler) and root in Path(handler.baseFilename).resolve().parents:
                handler.close()
                logger.removeHandler(handler)
