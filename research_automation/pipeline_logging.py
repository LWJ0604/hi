"""Lightweight logging resources; GUI startup need not import scientific libraries."""
from contextlib import contextmanager
from contextvars import ContextVar
import logging
from logging.handlers import RotatingFileHandler

_log_owner = ContextVar('research_pipeline_log_owner', default=None)


class PipelineLogOwner:
    """Own only handlers created inside this GUI controller's worker scope."""
    def __init__(self):
        self.handlers = []

    @contextmanager
    def activate(self):
        token = _log_owner.set(self)
        try:
            yield
        finally:
            _log_owner.reset(token)

    def close(self):
        for log, handler in self.handlers:
            log.removeHandler(handler)
            handler.close()
        self.handlers.clear()


def logger(cfg):
    owner = _log_owner.get()
    name = 'research-automation.' + str(cfg.path)
    log = logging.getLogger(name if owner is None else name + '.gui-' + str(id(owner)))
    if not log.handlers:
        log.setLevel(logging.INFO)
        handler = RotatingFileHandler(cfg.paths['logs'] / 'pipeline.log', maxBytes=5_000_000,
                                      backupCount=5, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        log.addHandler(handler)
        if owner is not None:
            owner.handlers.append((log, handler))
    return log
