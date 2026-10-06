import hashlib
import json
from pathlib import Path
from unittest.mock import patch
import zipfile

from test_system import Base
from research_automation.result_review import audit_results, refresh_plots
from research_automation.pipeline import scan


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class SavedResultReviewTests(Base):
    def test_audit_does_not_create_database_or_touch_originals_when_no_results(self):
        source = self.sample()
        before = sha(source)
        output = audit_results(self.cfg)
        self.assertEqual(output['input_files'], 1)
        self.assertEqual(output['covered_inputs'], 0)
        self.assertFalse((self.cfg.paths['state'] / 'jobs.sqlite3').exists())
        self.assertEqual(sha(source), before)
        report = json.loads(Path(output['report']).with_name('audit.json').read_text(encoding="utf-8"))
        self.assertTrue(any(i['code']=='input_without_completed_result' for i in report['issues']))
        with zipfile.ZipFile(output['bundle']) as bundle:
            self.assertEqual(set(bundle.namelist()), {'audit.json','metrics.csv','report.md'})

    def test_audit_detects_missing_links_output_and_changed_input_without_rewriting(self):
        source = self.sample();entry = scan(self.cfg)['files'][0]
        result = Path(entry['result_path']);summary=json.loads(result.read_text(encoding="utf-8"))
        figure = summary['figures'][0]
        (result.parent / figure).unlink()
        (self.cfg.paths['vault'] / summary['vault_assets_relative_path'] / figure).unlink()
        source.write_text(source.read_text(encoding="utf-8")+'\n', encoding="utf-8")
        targets = [source, result, Path(entry['note']), self.cfg.paths['state']/'jobs.sqlite3']
        hashes = {path:sha(path) for path in targets}
        output = audit_results(self.cfg)
        detail = json.loads(Path(output['report']).with_name('audit.json').read_text(encoding="utf-8"))
        codes = {i['code'] for i in detail['issues']}
        self.assertTrue({'output_missing','note_link_missing','original_hash_changed','input_without_completed_result','metadata_review_needed'} <= codes)
        self.assertEqual(output['covered_inputs'],0)
        self.assertEqual(hashes,{path:sha(path) for path in targets})

    def test_plot_revision_uses_cache_preserves_user_note_values_and_database(self):
        source = self.sample();entry = scan(self.cfg)['files'][0]
        note=Path(entry['note']);note.write_text(note.read_text(encoding="utf-8")+'\n연구자가 수정한 본문\n', encoding="utf-8")
        prior=Path(entry['result_path']).parent
        targets=[p for p in prior.iterdir() if p.is_file()]+[source,note,self.cfg.paths['state']/'jobs.sqlite3']
        hashes={p:sha(p) for p in targets}
        with patch('research_automation.pipeline.analyze',side_effect=AssertionError('no numeric reanalysis')),patch('research_automation.ai.httpx.Client',side_effect=AssertionError('no HTTP')):
            output=refresh_plots(self.cfg,[entry['source']])
        self.assertEqual(output['completed'],1);self.assertFalse(output['refit'])
        self.assertEqual(hashes,{p:sha(p) for p in targets})
        folder=Path(output['files'][0]['folder'])
        self.assertNotEqual(folder,prior)
        self.assertTrue((folder/'overview_vd.png').is_file())
        revision=json.loads((folder/'revision.json').read_text(encoding="utf-8"))
        self.assertFalse(revision['refit']);self.assertEqual(revision['prior_curves_sha256'],sha(prior/'curves.csv'))

    def test_note_preview_uses_cache_preserves_all_prior_files_and_selects_only_one_source(self):
        from research_automation.note_preview import preview_notes
        source=self.sample();entry=scan(self.cfg)['files'][0]
        note=Path(entry['note']);note.write_text(note.read_text(encoding="utf-8")+'\n사용자 직접 편집\n', encoding="utf-8")
        prior=Path(entry['result_path']).parent
        targets=[p for p in prior.iterdir() if p.is_file()]+[source,note,self.cfg.paths['state']/'jobs.sqlite3']
        hashes={p:sha(p) for p in targets}
        with patch('research_automation.pipeline.analyze',side_effect=AssertionError('no legacy reanalysis')),patch('research_automation.pipeline.load_measurements',side_effect=AssertionError('no reparse')),patch('research_automation.science_exports.enrich_context',side_effect=AssertionError('no recertification')),patch('research_automation.ai.httpx.Client',side_effect=AssertionError('no HTTP')):
            result=preview_notes(self.cfg,[entry['source']])
        self.assertEqual(len(result['files']),1);self.assertFalse(result['refit']);self.assertEqual(result['api_calls'],0)
        self.assertEqual(hashes,{p:sha(p) for p in targets})
        assets=Path(result['files'][0]['assets'])
        for p in prior.iterdir():
            if p.is_file() and p.suffix in ('.csv','.json'):
                name='prior_'+p.name if p.name.startswith('fet_') or p.name in ('research_report.json','research_metrics.csv','figure2_manifest.json','metric_evidence.json') else p.name
                self.assertEqual(sha(p),sha(assets/name))
        text=Path(result['files'][0]['note']).read_text(encoding="utf-8")
        self.assertIn('## 연구 질문',text);self.assertIn('<summary>감사 상세',text)
        import re
        for link in re.findall(r'\[\[([^\]|]+)',text):self.assertTrue((self.cfg.paths['vault']/link).is_file(),link)
        self.assertTrue((assets/'fet_summary.csv').is_file())
