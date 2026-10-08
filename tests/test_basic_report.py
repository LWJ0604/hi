import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
import yaml
from scipy.optimize import brentq

from research_automation.config import Config,DEFAULT
from research_automation.device_metadata import read_device,context_for,declared_pair,run_conditions,measurement_config
from research_automation.benchmark_batch import generate,dependencies,select
from research_automation.benchmark_data import load_source,monotone_segments,output_benchmarks,transfer_benchmarks
from research_automation.benchmark_models import model_current,fit_branch,fit_signed
from research_automation.gui_backend import save_settings
from research_automation.util import digest


class BasicReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.path=self.root/'config.json'
        self.data=copy.deepcopy(DEFAULT);self.data['ingest']['stable_seconds']=.01
        self.cfg=self.config();self.cfg.ensure_dirs()

    def config(self):
        self.path.write_text(json.dumps(self.data),encoding='utf-8');return Config(self.path)

    def device(self,path=None,text=''):
        p=path or self.cfg.paths['inbox']/'device.md';p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text('---\nschema_version: 1\n'+text+'---\n내 메모는 보존하세요.\n',encoding='utf-8');return p

    def source(self,name='measure.csv',transfer=False,units=True):
        path=self.cfg.paths['inbox']/name;path.parent.mkdir(parents=True,exist_ok=True)
        x=np.linspace(-2,2,17)
        if transfer:frame=pd.DataFrame({'GateV (V)':x,'DrainV (V)':1.,'DrainI (A)':1e-8+2e-9*x,'GateI (A)':1e-12})
        else:frame=pd.DataFrame({'DrainV (V)':x,'GateV (V)':0.,'DrainI (A)':1e-8*np.sinh(x)})
        if not units:frame.columns=[c.split(' (')[0] for c in frame]
        frame.to_csv(path,index=False,encoding='utf-8');return path

    def test_safe_yaml_rejects_object_execution_and_duplicate(self):
        for text in ('device_name: !!python/object/apply:os.system [echo nope]\n','device_name: a\ndevice_name: b\n'):
            with self.assertRaises((ValueError,yaml.YAMLError)):read_device(self.device(text=text))

    def test_invalid_metadata_keeps_raw_data(self):
        self.device(text='structure: bad\n');loaded=load_source(self.source(),self.cfg)
        self.assertEqual(len(loaded['points']),17);self.assertTrue(loaded['context']['warnings'])

    def test_nearest_override_preserves_parent_and_memo(self):
        parent=self.device(text='device_name: {value: same}\nrun_conditions:\n  temperature: {value: 25, unit: degC}\n')
        child=self.device(self.cfg.paths['inbox']/'child/device.md','run_conditions:\n  temperature: {value: 20, unit: degC}\n')
        before={p:digest(p) for p in (parent,child)};ctx=context_for(self.source('child/data.csv'),self.cfg)
        self.assertEqual(ctx['data']['run_conditions']['temperature']['value'],20)
        self.assertEqual(before,{p:digest(p) for p in before})

    def test_changed_device_identity_does_not_inherit_geometry(self):
        self.device(text='device_name: {value: parent}\nelectrode_pairs: {p: {L: {value: 2, unit: um}}}\n')
        self.device(self.cfg.paths['inbox']/'child/device.md','device_name: {value: different}\n')
        self.assertNotIn('electrode_pairs',context_for(self.source('child/data.csv'),self.cfg)['data'])

    def test_dates_apply_only_to_declared_file(self):
        self.device(text='run_conditions:\n  IdVd:\n    file: measure.csv\n    measurement_date: {value: 2026-09-23, verification: user_confirmed}\n')
        a=self.source();b=self.source('transfer.csv',True)
        self.assertEqual(run_conditions(a,context_for(a,self.cfg))[1]['measurement_date']['value'],'2026-09-23')
        self.assertEqual(run_conditions(b,context_for(b,self.cfg)),(None,{}))

    def test_pair_requires_two_existing_explicit_links(self):
        a=self.source();b=self.source('transfer.csv',True)
        self.assertEqual(select(self.cfg,['measure.csv'])[0],[a])
        self.device(text='run_conditions:\n  IdVd: {file: measure.csv}\n  IdVg: {file: transfer.csv}\n')
        self.assertEqual(select(self.cfg,['measure.csv'])[0],[a,b]);b.unlink()
        self.assertEqual(select(self.cfg,['measure.csv'])[0],[a])

    def test_pair_traversal_blocked(self):
        a=self.source();self.device(text='run_conditions:\n  IdVd: {file: ../escape.csv}\n')
        ctx=context_for(a,self.cfg);self.assertTrue(ctx['warnings']);self.assertEqual(declared_pair(a,ctx),[a])

    def test_memo_change_is_dependency_without_note_overwrite(self):
        p=self.device();a=self.source();before=dependencies(self.cfg,a)
        p.write_text(p.read_text(encoding='utf-8')+'추가 메모\n',encoding='utf-8')
        self.assertNotEqual(before,dependencies(self.cfg,a))

    def test_confirmed_unitless_profile(self):
        self.data['measurement_profile']={'voltage_unit':'V','current_unit':'A','confirmed':True,'source':'test fixture only'}
        cfg=self.config();a=self.source(units=False);r=load_source(a,cfg)['records'][0]
        self.assertEqual(r['column_mapping']['id']['unit_status'],'confirmed')
        self.assertEqual(r['column_mapping']['id']['unit_source'],'user_profile')

    def test_unknown_default_does_not_forge_confirmation(self):
        loaded=load_source(self.source(units=False),self.cfg);r=loaded['records'][0]
        self.assertEqual(r['column_mapping']['id']['unit_status'],'inferred')
        result=output_benchmarks(loaded,self.cfg)
        self.assertTrue(result['rr'].RR.isna().all());self.assertTrue(result['parameters'].empty)
        self.assertEqual(len(loaded['points']),17)

    def test_explicit_file_units_win_profile_conflict(self):
        self.data['measurement_profile']={'voltage_unit':'V','current_unit':'A','confirmed':True,'source':'test fixture only'}
        cfg=self.config();p=self.cfg.paths['inbox']/'n.csv'
        pd.DataFrame({'DrainV (V)':np.arange(6),'DrainI (nA)':np.arange(6)+1}).to_csv(p,index=False,encoding='utf-8')
        r=load_source(p,cfg)['records'][0]
        self.assertAlmostEqual(r['data'].id.iloc[0],1e-9)
        self.assertTrue(r['column_mapping']['id']['unit_conflict'])

    def test_device_profile_nearest_confirmed_value(self):
        self.device(text='run_conditions:\n  units: {voltage: V, current: A, verification: user_confirmed}\n')
        r=load_source(self.source(units=False),self.cfg)['records'][0]
        self.assertEqual(r['column_mapping']['id']['unit_status'],'confirmed')

    def test_invalid_device_profile_falls_back_without_blank_output(self):
        self.device(text='run_conditions:\n  units: {voltage: cats, current: A, verification: user_confirmed}\n')
        loaded=load_source(self.source(units=False),self.cfg)
        self.assertEqual(len(loaded['points']),17);self.assertTrue(loaded['context']['warnings'])

    def test_geometry_requires_selected_confirmed_pair(self):
        self.device(text='electrode_pairs:\n  p:\n    L: {value: 2, unit: um, verification: user_confirmed}\n    W: {value: 1, unit: um, verification: user_confirmed}\n')
        loaded=load_source(self.source(),self.cfg);self.assertIsNone(loaded['geometry']['L_um'])
        self.data['benchmark']['electrode_pair']='p';loaded=load_source(loaded['path'],self.config());self.assertEqual(loaded['geometry']['L_um'],2)

    def test_missing_geometry_holds_only_mobility(self):
        loaded=load_source(self.source(transfer=True),self.cfg);result=transfer_benchmarks(loaded,self.cfg)
        self.assertTrue(result['metrics'][0]['gm_peaks']);self.assertTrue(result['holds'])
        self.assertNotIn('mu_apparent_central_cm2_Vs',result['frame'])

    def test_acquisition_turn_order_and_no_fabricated_repeats(self):
        frame=pd.DataFrame({'vg':[0.,1.,2.,1.,0.],'source_row':np.arange(5)+2})
        segments=monotone_segments(frame,'vg');self.assertEqual([s.vg.tolist() for s in segments],[[0,1,2],[2,1,0]])
        self.assertEqual(segments[1].source_row.tolist(),[4,5,6])

    def test_gaps_and_dwells_do_not_join_derivative(self):
        frame=pd.DataFrame({'vg':[0.,1.,1.,2.,3.],'source_row':[2,3,4,8,9]})
        self.assertEqual([s.vg.tolist() for s in monotone_segments(frame,'vg')],[[0,1],[1],[2,3]])

    def test_rr_fixed_numerator_raw_cells(self):
        loaded=load_source(self.source(),self.cfg);result=output_benchmarks(loaded,self.cfg,fit=False)['rr']
        self.assertTrue(np.allclose(result.RR,result.abs_Iplus_A/result.abs_Iminus_A));self.assertIn('plus_source_Id_cell',result)

    def test_zero_denominator_has_reason_and_null(self):
        p=self.source();d=pd.read_csv(p);d.loc[d['DrainV (V)']==-1.,'DrainI (A)']=0;d.to_csv(p,index=False)
        rr=output_benchmarks(load_source(p,self.cfg),self.cfg,fit=False)['rr'];r=rr[rr.abs_Vd_V==1].iloc[0]
        self.assertTrue(pd.isna(r.RR));self.assertIn('0',r.reason)

    def test_implicit_model_matches_independent_root_signed(self):
        Is,a,rs=2e-8,.1,1e6
        for v in [-1.,-.01,0.,.01,1.]:
            prediction=float(model_current(v,Is,a,rs))
            residual=a*np.log1p(prediction/Is)+prediction*rs-v
            self.assertLess(abs(residual),1e-10)
            if v>0:
                root=brentq(lambda j:a*np.log1p(j/Is)+j*rs-v,0,1e-5,xtol=1e-20)
                self.assertAlmostEqual(prediction/root,1.,places=8)

    def test_model_minus_one_and_zero_preserved(self):
        self.assertEqual(float(model_current(0,1e-8,.2)),0)
        self.assertAlmostEqual(float(model_current(.1,1e-8,.2))/1e-8,np.expm1(.5))

    def test_effective_parameter_recovery(self):
        x=np.linspace(.1,1.5,20);y=model_current(x,2e-8,.15,1e6)
        result,pred=fit_branch(x,y,'Shockley+Rs')
        self.assertTrue(np.allclose(pred,y,rtol=1e-5));self.assertAlmostEqual(result['Rs_ohm']/1e6,1,places=3)

    def test_fixed_n_requires_temperature(self):
        v=np.linspace(-1,1,21);y=1e-8*np.sinh(v)
        with self.assertRaises(ValueError):fit_signed(v,y,'Shockley',1,None)

    def test_gm_uses_actual_coordinates_and_ignores_endpoints(self):
        loaded=load_source(self.source(transfer=True),self.cfg);result=transfer_benchmarks(loaded,self.cfg)['frame']
        np.testing.assert_allclose(result.gm_central_A_V.iloc[1:-1],2e-9,rtol=1e-10)
        self.assertTrue(result.gm_central_A_V.iloc[[0,-1]].isna().all())

    def test_gui_profile_saved_with_backup_and_idempotent(self):
        cfg=save_settings(self.path,str(self.cfg.paths['inbox']),str(self.cfg.paths['vault']),False,True)
        self.assertTrue(cfg.data['measurement_profile']['confirmed']);count=len(list(self.root.glob('config.before-gui-*')))
        save_settings(self.path,str(cfg.paths['inbox']),str(cfg.paths['vault']),False,True)
        self.assertEqual(count,len(list(self.root.glob('config.before-gui-*'))))

    def test_explicit_override_history_applies_and_invalidates_report(self):
        from research_automation.metadata_review import save_override
        p=self.source();before=dependencies(self.cfg,p)
        save_override(self.cfg,p.name,digest(p),{'measurement_date':'2026-09-23','illumination':'dark'},'synthetic test fixture only')
        loaded=load_source(p,self.cfg)
        self.assertEqual(loaded['conditions']['measurement_date']['value'],'2026-09-23')
        self.assertTrue(loaded['conditions']['measurement_date']['history'])
        self.assertNotEqual(before,dependencies(self.cfg,p))

    def test_report_preserves_original_and_never_reuses_output_folder(self):
        p=self.source(transfer=True);device=self.device();before={p:digest(p),device:digest(device)}
        with patch('research_automation.benchmark_report.figures',return_value={}):
            a=generate(self.cfg,[p.name]);b=generate(self.cfg,[p.name])
        self.assertNotEqual(a['output'],b['output']);self.assertEqual(before,{p:digest(p) for p in before})
        text=Path(a['markdown']).read_text(encoding='utf-8')
        self.assertIn('gm',text);self.assertIn('계산 보류',text)
        for forbidden in ('None','null','Sentinel','trace_id','optimizer_success'):self.assertNotIn(forbidden,text)

    def test_native_default_publishes_basic_report_and_metadata_revision_preserves_note(self):
        from research_automation.pipeline import scan
        from research_automation.change_preview import preview
        p=self.source();device=self.device()
        with patch('research_automation.benchmark_report.figures',return_value={}),patch('research_automation.pipeline.plots') as legacy_figures:
            first=scan(self.cfg,sources=[p.name]);self.assertEqual(first['counts']['completed'],1,first)
            job=first['files'][0];note=Path(job['note']);before=digest(note)
            result=json.loads(Path(job['result_path']).read_text(encoding='utf-8'))
            self.assertEqual(result['benchmark_report_format'],'basic-parameters-1')
            from research_automation.gui_backend import job_row
            row=job_row({'result_path':job['result_path'],'source':p.name,'status':'completed'})
            self.assertIn('RR ',row['metric_summary']);self.assertNotIn('b000',row['metric_summary'])
            self.assertTrue((Path(job['result_path']).parent/'benchmark/report.html').is_file())
            self.assertIn('RR(Vg)',note.read_text(encoding='utf-8'))
            legacy_figures.assert_not_called()
            self.assertEqual(scan(self.cfg,sources=[p.name])['counts']['unchanged'],1)
            self.assertEqual(preview(self.cfg,[p.name])['files'][0]['action'],'unchanged')
            device.write_text(device.read_text(encoding='utf-8')+'새 사용자 메모\n',encoding='utf-8')
            self.assertEqual(preview(self.cfg,[p.name])['files'][0]['action'],'new_versioned_result')
            second=scan(self.cfg,sources=[p.name]);self.assertEqual(second['counts']['completed'],1,second)
            self.assertNotEqual(note,Path(second['files'][0]['note']))
            self.assertEqual(before,digest(note))
            from research_automation.metadata_review import save_override
            from research_automation.review_recompute import metadata_recompute
            save_override(self.cfg,p.name,digest(p),{'measurement_date':'2026-09-23'},'synthetic test fixture only')
            with patch('research_automation.pipeline.analyze',side_effect=AssertionError('legacy numeric analysis must be reused')):
                reviewed=metadata_recompute(self.cfg,second['files'][0]['result_path'],['measurement_date'])
            self.assertTrue(reviewed['recalculation']['reused_numeric_analysis'])
            self.assertIn('2026-09-23',Path(reviewed['note']).read_text(encoding='utf-8'))
            self.assertEqual(job_row({'result_path':reviewed['result_path']})['measurement_date'],'2026-09-23')
            self.assertEqual(scan(self.cfg,sources=[p.name])['counts']['unchanged'],1)
            self.assertEqual(before,digest(note))
        from research_automation.pipeline_logging import PipelineLogOwner
        import logging
        log=logging.getLogger('research-automation.'+str(self.path.resolve()))
        for handler in list(log.handlers):handler.close();log.removeHandler(handler)


if __name__=='__main__':unittest.main()
