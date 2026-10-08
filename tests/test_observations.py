import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from research_automation.config import DEFAULT
from research_automation.config import Config
from research_automation import observation_metrics as om
from research_automation.observation_analysis import analyze_observations, analyze_file
from research_automation.observation_report import export_report, measurement_description


def frame(x,y,axis='vd'):
    return pd.DataFrame({axis:x,'id':y,'metric_eligible':True,'source_row':np.arange(len(x))+2,
        'acquisition_order':np.arange(len(x)),'segment_id':0})


class ObservationTests(unittest.TestCase):
    def setUp(self):self.cfg=SimpleNamespace(data=copy.deepcopy(DEFAULT))

    def test_fixed_ratio_orientation_and_zero_floor(self):
        self.assertEqual(om.ratio(2,-8)[0],.25)
        self.assertIsNone(om.ratio(2,0)[0])
        v,state=om.ratio(10,.1,1)
        self.assertIsNone(v);self.assertEqual(state['bound_value'],10)
        self.assertEqual(om.ratio(10,.1)[0],100)
        self.assertNotIn('bound_value',om.ratio(10,.1)[1])

    def test_raw_rr_available_without_si_but_dimensional_value_is_assumed(self):
        f=frame(np.linspace(-2,2,81),1e-9*(3+np.linspace(-2,2,81)))
        metrics,_,_=om.output_metrics(f,False,self.cfg)
        rr=next(m for m in metrics if m['parameter']=='rr' and m['evaluation_abs_voltage']==1)
        self.assertAlmostEqual(rr['value'],2);self.assertEqual(rr['denominator_confidence'],'not_assessed')
        current=next(m for m in metrics if m['parameter']=='signed_current')
        self.assertIsNone(current['value']);self.assertIsNotNone(current['value_assuming_si'])

    def test_signed_interpolation_and_gap_dwell_no_extrapolation(self):
        f=frame([-1,0,1],[-10,0,20])
        self.assertEqual(om.sample(f,'vd',.5)['value'],10)
        self.assertIsNone(om.sample(f,'vd',2)['value'])
        f.loc[2,'acquisition_order']=9
        self.assertIsNone(om.sample(f,'vd',.5)['value'])
        d=frame([0,0,1],[1,2,3]);self.assertIsNone(om.sample(d,'vd',0)['value'])

    def test_g0_free_offset_and_window_never_expanded(self):
        x=np.linspace(-.2,.2,81);f=frame(x,7e-10+3e-8*x)
        metrics,_,_=om.output_metrics(f,True,self.cfg)
        for m in metrics:
            if m['parameter']=='g0':self.assertAlmostEqual(m['value'],3e-8,places=16)
            if m['parameter']=='offset':self.assertAlmostEqual(m['value'],7e-10,places=17)
        coarse=frame([-.1,-.05,0,.05,.1],np.array([-.1,-.05,0,.05,.1])*2)
        metrics,_,_=om.output_metrics(coarse,True,self.cfg)
        g0=[m for m in metrics if m['parameter']=='g0']
        self.assertIsNone(g0[0]['value']);self.assertIsNone(g0[1]['value']);self.assertAlmostEqual(g0[2]['value'],2)

    def test_no_g0_fit_across_invalid_point(self):
        x=np.linspace(-.1,.1,21);f=frame(x,x)
        f.loc[10,'metric_eligible']=False
        metrics,_,_=om.output_metrics(f,True,self.cfg)
        self.assertTrue(all(m['value'] is None for m in metrics if m['parameter']=='g0'))

    def test_empty_voltage_window_is_held_without_crashing(self):
        f=frame([1,2,3],[1e-9,2e-9,3e-9])
        metrics,_,_=om.output_metrics(f,True,self.cfg)
        self.assertTrue(all(m['value'] is None for m in metrics if m['parameter']=='g0'))

    def test_actual_irregular_coordinate_derivative(self):
        x=np.array([-.3,-.23,-.19,-.11,-.02,0,.07,.12,.22,.28,.3]);f=frame(x,2e-9+3e-8*x+4e-8*x*x)
        derivatives,_=om.local_derivatives(f,'vd',[.6],7)
        np.testing.assert_allclose(derivatives[0]['values'][5],3e-8,rtol=1e-10)

    def test_signed_gm_peak_and_censored_width(self):
        x=np.linspace(-10,10,201);f=frame(x,-1e-8*x,'vg')
        metrics,_,_=om.transfer_metrics(f,True,self.cfg)
        for m in metrics:
            if m['parameter']=='gm_peak':self.assertAlmostEqual(m['value'],-1e-8,places=17)
            if m['parameter']=='gm_fwhm':self.assertIsNone(m['value']);self.assertTrue(m['censored'])

    def test_inverse_log_slope_exploratory_not_device_ss(self):
        x=np.linspace(-2,2,41);f=frame(x,1e-9*10**x,'vg')
        metrics,_,_=om.transfer_metrics(f,True,self.cfg)
        ss=next(m for m in metrics if m['parameter']=='inverse_log_slope')
        self.assertAlmostEqual(ss['value'],1000);self.assertFalse(ss['trusted_ss'])

    def test_constant_current_multiple_crossings_and_scale(self):
        f=frame(np.linspace(-2,2,41),1e-9*(1+np.linspace(-2,2,41)**2),'vg')
        self.assertIsNone(om.monotone_crossings(f,2e-9)[0])
        metrics,_,_=om.transfer_metrics(f,False,self.cfg)
        self.assertTrue(all(m['value'] is None for m in metrics if m['parameter']=='vcc'))

    def test_leakage_absent_unknown_channels_and_no_subtraction(self):
        f=frame([0,1,2],[1,2,4]);self.assertEqual(om.leakage_metrics(f,True,True)[0]['reason'],'Ig_not_recorded')
        f['ig']=[.5,.5,.5];record=om.leakage_metrics(f,False,False)[1]
        self.assertIsNone(record['value']);self.assertEqual(record['value_assuming_si'],.5)
        self.assertEqual(f['id'].tolist(),[1,2,4])
        f['metric_eligible']=False
        self.assertIsNone(om.leakage_metrics(f,True,True)[1]['value'])

    def test_leakage_unit_dependencies_are_independent_of_id_and_axis(self):
        data=frame([-1,0,1],[1e-9,1e-9,1e-9]);data['ig']=[-2e-10,0,1e-10]
        for ig_known in (False,True):
            for id_known in (False,True):
                with self.subTest(ig_known=ig_known,id_known=id_known):
                    sheet={'axis':'vd','data':data,'column_mapping':{
                        'ig':{'unit_status':'confirmed' if ig_known else 'unknown'},
                        'id':{'unit_status':'confirmed' if id_known else 'unknown'},
                        'vd':{'unit_status':'unknown'}},'invalid_rows':0,
                        'raw_rows':len(data),'group_by':[],'name':'measurement'}
                    result,_=analyze_observations([sheet],self.cfg)
                    records={m['parameter']:m for m in result['branches'][0]['metrics'] if m['parameter'].startswith('leakage_')}
                    maximum,ratio=records['leakage_max'],records['leakage_ratio']
                    self.assertEqual(maximum['unit_dependencies'],['ig'])
                    self.assertEqual(ratio['unit_dependencies'],['ig','id'])
                    self.assertEqual(maximum['value'],2e-10 if ig_known else None)
                    self.assertEqual(maximum['value_assuming_si'],None if ig_known else 2e-10)
                    self.assertEqual(maximum['unit_basis'],'declared_or_user_confirmed' if ig_known else 'SI_assumption')
                    self.assertEqual(maximum['availability'],'observation' if ig_known else 'exploratory')
                    if ig_known and id_known:
                        self.assertAlmostEqual(ratio['value'],.2)
                        self.assertIsNone(ratio['value_assuming_si'])
                    else:
                        self.assertIsNone(ratio['value'])
                        self.assertAlmostEqual(ratio['value_assuming_si'],.2)
                    self.assertFalse(result['metadata_status']['human_overrides_created'])

    def test_leakage_ratio_normalizes_different_declared_current_scales(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'different-current-units.csv'
            pd.DataFrame({'DrainV (V)':[-1,0,1],'DrainI (mA)':[1e-6,1e-6,1e-6],
                'GateI (nA)':[-.2,0,.1]}).to_csv(source,index=False,encoding='utf-8')
            result,points=analyze_file(source,self.cfg)
            records={m['parameter']:m for m in result['branches'][0]['metrics'] if m['parameter'].startswith('leakage_')}
            self.assertAlmostEqual(records['leakage_max']['value'],2e-10,places=18)
            self.assertAlmostEqual(records['leakage_ratio']['value'],.2)
            np.testing.assert_allclose(points['id'],1e-9)
            np.testing.assert_allclose(points['ig'],[-2e-10,0,1e-10])

    def test_report_distinguishes_measured_channels_structure_hint_and_confirmation(self):
        result={'branches':[{'axis':'vg'}],'metadata_fields':{}}
        unknown=measurement_description(result,{},'unknown.csv')
        self.assertIn('Id–Vg',unknown);self.assertNotIn('Id–Vd',unknown)
        self.assertIn('구조(fold): 미확인',unknown)
        self.assertNotIn('접힌 구조의 소자',unknown)
        self.assertNotIn('2단자',unknown)
        hint=measurement_description(result,{'relative_path':'center_fold/sample.csv'},'sample.csv')
        self.assertIn('center-fold (사람의 확인 아님)',hint)
        self.assertNotIn('사용자 확인 구조',hint)
        result['metadata_fields']['fold']={'value':'center-fold','source':'user_override','status':'confirmed'}
        confirmed=measurement_description(result,{},'sample.csv')
        self.assertIn('사용자 확인 구조(fold): center-fold',confirmed)
        self.assertNotIn('구조(fold): 미확인',confirmed)

    def test_branches_original_stress_and_hysteresis_pairing(self):
        x=np.r_[np.linspace(-20,20,81),np.linspace(19.5,-20,80)]
        data=frame(x,1e-9*(x+30),'vg');data['vd']=2
        sheet={'axis':'vg','data':data,'column_mapping':{k:{'unit_status':'confirmed'} for k in ('vg','id')},
            'invalid_rows':0,'raw_rows':len(data),'group_by':['vd'],'name':'measurement','source_sheet':'measurement'}
        result,points=analyze_observations([sheet],self.cfg)
        self.assertEqual(len(result['branches']),2);self.assertEqual(len(result['hysteresis_pairs']),1)
        self.assertEqual(result['branches'][0]['original_sweep']['maximum'],20)
        self.assertEqual(result['branches'][1]['branch_sweep']['start'],20)
        self.assertEqual(len(points),len(data)+1)
        self.assertFalse(result['metadata_status']['human_overrides_created'])
        current=[m for m in result['hysteresis_pairs'][0]['metrics'] if m['parameter']=='hysteresis_current']
        self.assertEqual(sum(m['value'] is None for m in current),2)
        self.assertTrue(all(m['value']==0 for m in current if m['value'] is not None))

    def test_independent_sweeps_not_hysteresis_pairs(self):
        x=np.r_[np.linspace(-20,20,81),np.linspace(-20,20,81)]
        data=frame(x,1e-9*(x+30),'vg');data['vd']=2
        sheet={'axis':'vg','data':data,'column_mapping':{},'invalid_rows':0,'raw_rows':len(data),'group_by':['vd'],'name':'m'}
        result,_=analyze_observations([sheet],self.cfg)
        self.assertEqual(len(result['branches']),2);self.assertEqual(result['hysteresis_pairs'],[])

    def test_report_links_all_metrics_without_generic_benchmark_wall(self):
        x=np.linspace(-20,20,81);data=frame(x,1e-9*(x+30),'vg');data['vd']=2
        sheet={'axis':'vg','data':data,'column_mapping':{},'invalid_rows':0,'raw_rows':len(data),'group_by':['vd'],'name':'m'}
        result,points=analyze_observations([sheet],self.cfg)
        with tempfile.TemporaryDirectory() as temp:
            export_report(result,points,temp,'검증 측정')
            self.assertTrue((Path(temp)/'evidence-b0001.html').is_file())
            self.assertIn('실제 날짜', (Path(temp)/'report.html').read_text(encoding='utf-8'))
            self.assertIn('구조(fold): 미확인', (Path(temp)/'report.html').read_text(encoding='utf-8'))
            self.assertNotIn('접힌 구조의 소자', (Path(temp)/'report.md').read_text(encoding='utf-8'))
            self.assertNotIn('human_confirmed', (Path(temp)/'observations.json').read_text(encoding='utf-8'))

    def test_timing_disagreement_keeps_both_without_confirmation(self):
        x=np.arange(-20,21);data=frame(x,1e-9*(x+30),'vg');data['vd']=2
        sheet={'axis':'vg','data':data,'column_mapping':{},'invalid_rows':0,'raw_rows':len(data),'group_by':['vd'],'name':'m',
            'instrument_settings':{'sweep_delay_s':'0'}}
        result,_=analyze_observations([sheet],self.cfg,{'relative_path':'09-23/IdVg Delay 0.1s.xls'})
        field=result['metadata_fields']['sweep_delay_s']
        self.assertEqual(field['status'],'conflict');self.assertEqual({c['value'] for c in field['candidates']},{0,.1})
        self.assertEqual(field['history'],[])

    def test_selected_batch_preserves_notes_db_and_continues_after_missing_file(self):
        import json,hashlib
        from research_automation.observation_batch import observe
        with tempfile.TemporaryDirectory() as temp:
            config=Path(temp)/'config.json';config.write_text(json.dumps(copy.deepcopy(DEFAULT)),encoding='utf-8')
            cfg=Config(config);cfg.ensure_dirs()
            note=cfg.paths['vault']/'사용자 메모.md';note.write_text('메모 보존',encoding='utf-8')
            db=cfg.paths['state']/'sentinel.sqlite';db.write_bytes(b'preserve database sentinel')
            source=cfg.paths['inbox']/'한글 공백.csv'
            pd.DataFrame({'GateV (V)':np.linspace(-20,20,81),'DrainI (A)':np.linspace(1e-9,2e-9,81),'DrainV (V)':2}).to_csv(source,index=False,encoding='utf-8')
            before=[hashlib.sha256(p.read_bytes()).hexdigest() for p in (note,db,source)]
            result=observe(cfg,['누락.xls','한글 공백.csv'])
            self.assertEqual([r['status'] for r in result['files']],['failed','completed'])
            self.assertEqual(before,[hashlib.sha256(p.read_bytes()).hexdigest() for p in (note,db,source)])
            with self.assertRaisesRegex(ValueError,'Inbox'):observe(cfg,['../escape.xls'])


if __name__=='__main__':unittest.main()
