import hashlib
import json
from contextlib import closing
from pathlib import Path
import sqlite3
from unittest.mock import patch
import zipfile

from test_system import Base
from research_automation.reports import backup
from research_automation.gui_backend import load_jobs
from research_automation.result_review import read_jobs
from research_automation.result_evidence import evidence_items, support_text
from research_automation.store import Store


class WindowsResourceTests(Base):
    def test_backup_checksum_integrity_and_handles_closed(self):
        result = backup(self.cfg)
        archive_path = Path(result['backup'])
        checksum = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        self.assertEqual(checksum, result['sha256'])
        self.assertTrue(Path(str(archive_path)+'.sha256').read_text(encoding='utf-8').startswith(checksum))
        with zipfile.ZipFile(archive_path) as archive:
            db = self.root/'copied.sqlite3'; db.write_bytes(archive.read('state/jobs.sqlite3'))
        with closing(sqlite3.connect(db)) as connection:
            self.assertEqual(connection.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        db.unlink()
        self.assertFalse(any(p.is_dir() and p.name.startswith('tmp') for p in self.cfg.paths['state'].iterdir()))
        archive_path.unlink(); Path(str(archive_path)+'.sha256').unlink()

    def test_checksum_failure_does_not_publish_archive(self):
        with patch('research_automation.reports.atomic_text', side_effect=OSError('simulated write failure')):
            with self.assertRaises(OSError): backup(self.cfg)
        self.assertEqual(list(self.cfg.paths['backups'].iterdir()), [])

    def test_second_publish_failure_rolls_back_archive(self):
        import os
        replace = os.replace
        def fail_checksum(source, target):
            if str(target).endswith('.zip.sha256'): raise PermissionError('simulated permission error')
            return replace(source, target)
        with patch('research_automation.reports.os.replace', side_effect=fail_checksum):
            with self.assertRaises(PermissionError): backup(self.cfg)
        self.assertEqual(list(self.cfg.paths['backups'].iterdir()), [])

    def test_readers_release_database_before_return(self):
        store=Store(self.cfg); store.close()
        self.assertEqual(read_jobs(self.cfg), []); self.assertEqual(load_jobs(self.cfg), [])
        path=self.cfg.paths['state']/'jobs.sqlite3'
        renamed=path.with_suffix('.moved'); path.rename(renamed); renamed.unlink()

    def test_evidence_preserves_null_polarity_and_original_stress(self):
        summary={'groups':[{'group_id':'block1', 'direction':'reverse', 'original_sweep':[-40,40],
                    'rr_series':[{'value':None,'reason':'denominator_below_detection_limit',
                    'evaluation_abs_vd_v':1,'positive_current':{'source_points':[{'source_row':7}]},
                    'negative_current':{'source_points':[{'source_row':3}]}}]}]}
        before=json.dumps(summary)
        item=evidence_items(summary)[0]
        self.assertIn('denominator_below_detection_limit',support_text(item))
        self.assertEqual(item['original_sweep'],[-40,40]); self.assertIsNone(item['support']['value'])
        self.assertEqual(json.dumps(summary),before)
