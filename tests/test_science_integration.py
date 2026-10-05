import copy,hashlib,json,re,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from research_automation.config import Config,DEFAULT
from research_automation import __version__
from research_automation.pipeline import scan
from research_automation.change_preview import preview
from research_automation.metadata_review import save_override
from research_automation.review_recompute import metadata_recompute
from research_automation.analysis import split_sweeps


class ResearchIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);options=copy.deepcopy(DEFAULT)
        options['ingest']['stable_seconds']=.01
        (self.root/'config.json').write_text(json.dumps(options));self.cfg=Config(self.root/'config.json');self.cfg.ensure_dirs()
    def tearDown(self):self.temp.cleanup()
    def measurement(self,name='Id-Vd_dark.csv'):
        path=self.cfg.paths['inbox']/'drain-fold/2026-09-23'/name;path.parent.mkdir(parents=True,exist_ok=True)
        x=np.linspace(-2,2,41)
        pd.DataFrame({'DrainV (V)':x,'DrainI (A)':np.where(x<0,5e-9*x,1e-9*x),'GateV (V)':1.}).to_csv(path,index=False)
        return path
    def test_versioned_notes_links_rr_voltage_and_metadata_not_pass(self):
        source=self.measurement();before=source.read_bytes();result=scan(self.cfg)
        self.assertEqual(result['counts']['completed'],1)
        entry=result['files'][0];summary=json.loads(Path(entry['result_path']).read_text());note=Path(entry['note']).read_text()
        self.assertIn(f'Experiments/v{__version__}/',entry['note']);self.assertIn('평가 \\|Vd\\|',note)
        self.assertNotEqual(summary['research_context']['metadata_status'],'confirmed')
        metrics=pd.read_csv(Path(entry['result_path']).parent/'observable_metrics.csv')
        rr=metrics[metrics['metric']=='rectification_ratio'];self.assertEqual(rr['evaluation_abs_vd_v'].tolist(),[.5,1.,1.5,2.])
        self.assertTrue((rr['unit']=='1').all());self.assertAlmostEqual(rr.iloc[1]['value'],.2)
        for link in re.findall(r'\[\[([^\]|]+)',note):self.assertTrue((self.cfg.paths['vault']/link).exists())
        self.assertEqual(source.read_bytes(),before)
    def test_override_reuses_numeric_values_preserves_user_body_and_other_files(self):
        one=self.measurement();self.measurement('Id-Vd_withlight.csv')
        result=scan(self.cfg);entry=next(e for e in result['files'] if e['source'].endswith('dark.csv'))
        note=Path(entry['note']);note.write_text(note.read_text()+'\n연구자 직접 쓴 판단\n');before=note.read_bytes()
        rp=Path(entry['result_path']);summary=json.loads(rp.read_text());hash_before=hashlib.sha256(one.read_bytes()).hexdigest()
        save_override(self.cfg,summary['source_relative_path'],summary['source_sha256'],{'measurement_date':'2026-09-23'},'사용자가 실제 측정일 확인; 시간은 미상')
        with patch('research_automation.pipeline.analyze',side_effect=AssertionError('metadata update must not refit')):
            updated=metadata_recompute(self.cfg,rp,['measurement_date'])
        new=json.loads(Path(updated['result_path']).read_text());self.assertTrue(new['recalculation']['reused_numeric_analysis'])
        self.assertEqual(note.read_bytes(),before);self.assertTrue(rp.exists())
        self.assertEqual(hashlib.sha256(one.read_bytes()).hexdigest(),hash_before)
        self.assertEqual(new['research_context']['fields']['measurement_date']['status'],'confirmed')
        self.assertEqual(scan(self.cfg)['counts']['unchanged'],2)
    def test_read_only_preview_and_selected_source_only(self):
        a=self.measurement();self.measurement('Id-Vd_withlight.csv')
        plan=preview(self.cfg);self.assertEqual(len(plan['files']),2);self.assertFalse((self.cfg.paths['state']/'jobs.sqlite3').exists())
        output=scan(self.cfg,sources=[a.relative_to(self.cfg.paths['inbox']).as_posix()])
        self.assertEqual(output['counts']['completed'],1);self.assertFalse(plan['overwrite_existing_notes'])
    def test_turning_points_gate_reset_dwell_and_acquisition_order_preserved(self):
        x=np.r_[np.arange(-4,5),np.arange(3,-5,-1),np.arange(-4,5)]
        f=pd.DataFrame({'vg':x,'id':x*1e-9,'source_row':np.arange(len(x))+2,'acquisition_order':np.arange(len(x)),'segment_id':0})
        branches=split_sweeps(f,'vg');self.assertEqual([b[0] for b in branches],['forward','reverse','forward'])
        for _,b in branches:self.assertTrue(np.all(np.diff(b['acquisition_order'])==1))
        reset=pd.DataFrame({'vg':np.r_[np.arange(-4,5),np.arange(-4,5)],'id':1.})
        self.assertEqual([b[0] for b in split_sweeps(reset,'vg')],['forward','forward'])
    def test_same_input_science_is_reproducible_and_offline(self):
        self.measurement()
        with patch('research_automation.ai.httpx.Client',side_effect=AssertionError('external HTTP forbidden')):
            first=scan(self.cfg);second=scan(self.cfg)
        self.assertEqual(second['counts']['unchanged'],1)
        self.assertEqual(json.loads(Path(first['files'][0]['result_path']).read_text())['interpretation']['status'],'disabled')
    def test_units_confirmation_restores_held_metrics_without_refit(self):
        source=self.measurement()
        source.write_text(source.read_text().replace('DrainV (V)','DrainV').replace('DrainI (A)','DrainI').replace('GateV (V)','GateV'))
        entry=scan(self.cfg)['files'][0];rp=Path(entry['result_path']);before=json.loads(rp.read_text())
        self.assertIsNone(before['groups'][0]['rr_series'][1]['value'])
        save_override(self.cfg,entry['source'],before['source_sha256'],{'measurement_date':'2026-09-23'},'실제 측정일 확인, 단위는 아직 미확인')
        with patch('research_automation.pipeline.analyze',side_effect=AssertionError('date confirmation must preserve unit-held numeric candidates')):
            date_update=metadata_recompute(self.cfg,rp,['measurement_date'])
        reviewed=json.loads(Path(date_update['result_path']).read_text())
        self.assertEqual(reviewed['groups'],before['groups'])
        rp=Path(date_update['result_path'])
        save_override(self.cfg,entry['source'],before['source_sha256'],{'units_confirmed':True},'장비 내보내기 전압 V, 전류 A를 확인함')
        with patch('research_automation.pipeline.analyze',side_effect=AssertionError('unit confirmation must reuse numeric values')):
            update=metadata_recompute(self.cfg,rp,['units_confirmed'])
        after=json.loads(Path(update['result_path']).read_text())
        self.assertAlmostEqual(after['groups'][0]['rr_series'][1]['value'],.2)
        self.assertFalse(after['groups'][0]['units_review_required'])
        self.assertEqual(before['groups'][0]['fits'],after['groups'][0]['fits'])
    def test_parse_failure_has_separate_diagnostic_without_zero_metrics(self):
        source=self.cfg.paths['inbox']/'parameters.csv';source.write_text('sample,result\nA,1\n')
        entry=scan(self.cfg)['files'][0]
        self.assertEqual(entry['status'],'failed')
        detail=json.loads(Path(entry['diagnostic_path']).read_text())
        self.assertEqual(detail['parse_status'],'failed')
        self.assertEqual(detail['metric_status'],'unavailable')
        self.assertEqual(detail['model_status'],'not_run')
