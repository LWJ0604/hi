"""Read-only change inventory before any scan; no API, DB writes or notes."""
import hashlib
import sqlite3
from contextlib import closing
from . import __version__,code_fingerprint
from .metadata_review import fingerprint
from .util import digest


def preview(cfg,sources=None):
    from .pipeline import candidates
    database=cfg.paths['state']/'jobs.sqlite3'; old=[]
    if database.exists():
        with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as connection:
            connection.row_factory=sqlite3.Row;old=[dict(row) for row in connection.execute('SELECT * FROM jobs')]
    rows=[]
    for source in candidates(cfg):
        relative=source.relative_to(cfg.paths['inbox']).as_posix()
        if sources is not None and relative not in sources:continue
        source_hash=digest(source)
        identity=f'{relative}\n{source_hash}\n{cfg.fingerprint}\n{__version__}\n{code_fingerprint()}\n{fingerprint(cfg,relative,source_hash)}'
        if cfg.data['benchmark']['enabled']:
            import json
            from .benchmark_batch import dependencies
            identity+='\n'+json.dumps(dependencies(cfg,source),sort_keys=True)
        job=hashlib.sha256(identity.encode()).hexdigest()
        previous=[row for row in old if row['source']==relative and row['source_hash']==source_hash]
        unchanged=any(row['id']==job and row['status']=='completed' for row in previous)
        rows.append({'source_relative_path':relative,'source_sha256':source_hash,'proposed_job_id':job,
            'action':'unchanged' if unchanged else 'new_versioned_result','previous_notes_preserved':len(previous),
            'new_note_root':f'Experiments/v{__version__}','new_asset_root':f'Attachments/v{__version__}'})
    return {'version':__version__,'read_only':True,'external_api_calls':0,'overwrite_existing_notes':False,'files':rows}
