import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
from research_automation.config import DEFAULT
from research_automation.research_report import direct_ss,polarity_metrics,signed_mobility,export_report
from research_automation.scientific_metrics import sample_at,transfer_observables
from research_automation.fet_parameters import export_fet
from research_automation.research_panels import research_panels,verify_png
from research_automation.note_presentation import render_note
from research_automation.metric_contract import REQUIRED,validate_records
from research_automation.metric_store import read_metric_json
from test_note_presentation import fixture


class ResearchContractTests(unittest.TestCase):
    def config(self,root):return type('Cfg',(),{'paths':{'vault':root},'data':copy.deepcopy(DEFAULT)})()

    def test_nonuniform_reversal_signed_derivative_and_normalization(self):
        x=np.array([0,.5,2,3.5]);y=-5e-9-2e-9*x
        cfg=self.config(Path('.'))
        for reverse in (False,True):
            d=pd.DataFrame({'vg':x[::-1] if reverse else x,'id':y[::-1] if reverse else y,'vd':-2,'source_row':range(4)})
            _,arrays=transfer_observables(d,cfg)
            np.testing.assert_allclose(arrays['gm_a_per_v'],-2e-9,rtol=1e-12)
            np.testing.assert_allclose(arrays['gm_over_vd_a_per_v2'],1e-9,rtol=1e-12)
            np.testing.assert_allclose(arrays['gm_signed_over_max_abs'],-1,rtol=1e-12)
            np.testing.assert_allclose(arrays['gm_abs_over_max_abs'],1,rtol=1e-12)
        d['id']=-5e-9
        _,arrays=transfer_observables(d,cfg)
        np.testing.assert_array_equal(arrays['gm_a_per_v'],0)
        self.assertTrue(np.isnan(arrays['gm_signed_over_max_abs']).all())

    def test_direct_log_ss_is_not_discrete_id_over_gm(self):
        x=np.array([0,.5,2,3.5]);current=-1e-9*10**(x/2)
        for order in (np.arange(4),np.arange(4)[::-1]):
            data=pd.DataFrame({'x_v':x[order],'id_a':current[order],'source_row':order})
            ss,slope,_=direct_ss(data)
            np.testing.assert_allclose(ss,2000,rtol=1e-12)
            np.testing.assert_allclose(slope,.5,rtol=1e-12)
        gm=np.gradient(current,x,edge_order=2)
        self.assertFalse(np.allclose(1000*np.log(10)*np.abs(current/gm),ss))

    def test_zero_and_gap_ss_support_stays_with_actual_derivative_segment(self):
        with tempfile.TemporaryDirectory() as temp:
            s,data=fixture(held=False)
            x=np.arange(-3,4,dtype=float)
            data=pd.DataFrame({'group_id':'g0001','x_v':x,'id_a':x*1e-9,'source_row':np.arange(7)+2,
                               'gm_a_per_v':1e-9,'metric_eligible':True,'segment_id':0})
            cfg=self.config(Path(temp));additional=export_fet(data,s,Path(temp),cfg)
            report=export_report(data,s,Path(temp),cfg,additional)
            ss=[p for p in report['direct_metrics'] if p['parameter']=='ss_direct']
            self.assertEqual(len(ss),6)
            for p in ss:
                currents=[q['signed_current_a'] for q in p['derivative_support']]
                self.assertTrue(all(i>0 for i in currents) or all(i<0 for i in currents))
                self.assertTrue(all(np.isfinite(q['log10_abs_current']) for q in p['derivative_support']))
            json.dumps(report,allow_nan=False)

    def test_signed_mobility_si_conversion(self):
        self.assertAlmostEqual(signed_mobility(20e-9,2,1.5e-6,400e-9,3.84e-4),.9765625)
        self.assertAlmostEqual(signed_mobility(-20e-9,-2,1.5e-6,400e-9,3.84e-4),.9765625)
        self.assertAlmostEqual(signed_mobility(-20e-9,2,1.5e-6,400e-9,3.84e-4),-.9765625)
        self.assertIsNone(signed_mobility(20e-9,0,1.5e-6,400e-9,3.84e-4))

    def test_rr_direction_signed_g_bounds_and_independent_holds(self):
        result=polarity_metrics(12e-9,-3e-9,2,1e-9,True,True)
        for key,value in [('rr',4),('g_positive_s',6e-9),('g_negative_s',1.5e-9),('delta_g_s',4.5e-9),('a_g',.6)]:self.assertAlmostEqual(result[key],value)
        bound=polarity_metrics(12e-9,-.1e-9,2,1e-9,True,True)
        self.assertIsNone(bound['rr']);self.assertAlmostEqual(bound['rr_lower_bound'],12);self.assertIsNone(bound['a_g'])
        for a,b,floor,units,history in [(12e-9,-3e-9,None,True,True),(12e-9,-3e-9,1e-9,True,False),(.1e-9,-3e-9,1e-9,True,True),(.1e-9,-.1e-9,1e-9,True,True),(12e-9,-3e-9,1e-9,False,True)]:
            held=polarity_metrics(a,b,2,floor,units,history)
            self.assertEqual(held['metric_status'],'held');self.assertIsNone(held['rr']);self.assertIsNone(held['a_g'])

    def test_asymmetry_uses_magnitudes_and_keeps_negative_or_mixed_signed_g(self):
        # Explicitly synthetic signed-current fixtures; no metadata confirmation on real data.
        for positive,negative,gp,gn,delta,ag in [(-2,-1,-2,1,1,1/3),(-2,1,-2,-1,1,1/3),(1,2,1,-2,-1,-1/3)]:
            result=polarity_metrics(positive,negative,1,.1,True,True)
            self.assertEqual(result['g_positive_s'],gp);self.assertEqual(result['g_negative_s'],gn)
            self.assertEqual(result['delta_g_s'],delta);self.assertAlmostEqual(result['a_g'],ag)
            self.assertAlmostEqual(result['rr'],abs(positive)/abs(negative))

    def test_all_new_metric_records_have_contract_and_raw_to_width_conversion(self):
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp);s,data=fixture(held=False);cfg=self.config(d)
            s['groups'][0].update(sheet='Data',trace_id='trace-001')
            s['sheets']=[{'source_sheet':'Data','column_mapping':{
                'id':{'source':'DrainI(nA)','factor_to_si':1e-9,'unit_status':'confirmed','header_cell':'B1'},
                'vg':{'source':'GateV(mV)','factor_to_si':1e-3,'unit_status':'confirmed','header_cell':'A1'}}}]
            pd.DataFrame({'source_sheet':'Data','source_row':data['source_row'],'source_id_cell':data['source_id_cell'],
                          'raw_id_cell_value':data['id_a']/1e-9,'raw_x_cell_value':data['x_v']/1e-3}).to_csv(d/'parsed_points.csv',index=False)
            additional=export_fet(data,s,d,cfg);report=export_report(data,s,d,cfg,additional)
            records=report['metric_records'];validate_records(records)
            self.assertTrue(records);self.assertTrue(all(REQUIRED<=r.keys() for r in records))
            self.assertEqual(len(report['direct_metrics']),sum(r['parameter'] in {'id_over_width','gm_over_width','ss_direct'} for r in records))
            self.assertTrue(all(a['metrics'] for a in additional['method_arrays']))
            point=next(p for p in report['direct_metrics'] if p['parameter']=='id_over_width')
            self.assertEqual(point['availability'],'candidate');self.assertAlmostEqual(point['value'],data.iloc[0]['id_a']/.4)
            provenance=point['provenance'];self.assertEqual(provenance['source_file'],s['source_relative_path'])
            self.assertEqual(provenance['source_cells'][0]['id'],'B2');self.assertEqual(provenance['source_cells'][0]['x'],'A2')
            self.assertEqual(provenance['trace_id'],'trace-001')
            self.assertAlmostEqual(float(provenance['raw_points'][0]['raw_id_cell_value']),1)
            self.assertAlmostEqual(float(provenance['raw_points'][0]['raw_x_cell_value']),-2000)
            self.assertEqual(provenance['unit_conversion']['sheet_column_mapping']['id']['factor_to_si'],1e-9)
            conversion=next(t for t in provenance['transformations'] if t['operation']=='m to μm')
            self.assertEqual(conversion['factor'],1e6);self.assertAlmostEqual(conversion['output_width_um'],.4)
            self.assertEqual(point['bias_condition']['fixed_voltages_v'],{'vd':1})
            validate_records(read_metric_json(d/'fet_parameters.json')['points'])
            validate_records(read_metric_json(d/'research_report.json')['metric_records'])
            for name in ('fet_parameters.csv','fet_summary.csv','research_metrics.csv'):
                frame=pd.read_csv(d/name);self.assertTrue(REQUIRED<=set(frame.columns))
                self.assertIsInstance(json.loads(frame.iloc[0]['provenance']),dict)
            json.dumps(report,allow_nan=False)
            broken=copy.deepcopy(point);broken.pop('availability')
            with self.assertRaises(ValueError):validate_records([broken])

    def test_held_and_unavailable_metric_contract_never_converts_null_to_zero(self):
        with tempfile.TemporaryDirectory() as temp:
            _,_,_,additional,report=self.report(temp,held=True)
            for record in report['metric_records']:
                self.assertIn(record['availability'],{'held','unavailable'})
                self.assertIsNone(record['value']);self.assertTrue(record['reason'])
            point=next(p for p in report['direct_metrics'] if p['parameter']=='id_over_width')
            self.assertIsNotNone(point['candidate_value_assuming_si']);self.assertEqual(point['availability'],'held')
            self.assertEqual(point['provenance']['unit_conversion']['units_confirmed'],False)
            self.assertEqual(next(r for r in additional['extractions'] if r['parameter']=='ss_additional')['unit'],'mV/dec')
            self.assertTrue(all(p['availability']=='unavailable' and p['value'] is None for p in report['unavailable_metrics']))

    def test_wide_sheet_keeps_each_trace_mapping_and_physical_cells(self):
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp);s,data=fixture(held=False);cfg=self.config(d)
            s['groups'][0].update(sheet='Data/trace-001',trace_id=1)
            second=copy.deepcopy(s['groups'][0]);second.update(group_id='g0002',sheet='Data/trace-002',trace_id=2)
            s['groups'].append(second)
            other=data.copy();other['group_id']='g0002';other['source_id_cell']=['E'+str(n) for n in other['source_row']]
            curves=pd.concat([data,other],ignore_index=True);curves['source_sheet']='Data'
            s['sheets']=[{'name':f'Data/trace-00{n}','source_sheet':'Data','trace_id':n,
                          'column_mapping':{'id':{'source':f'DrainI({n})','header_cell':header,'factor_to_si':factor}}}
                         for n,header,factor in [(1,'B1',1e-9),(2,'E1',1e-6)]]
            additional=export_fet(curves,s,d,cfg);report=export_report(curves,s,d,cfg,additional)
            for gid,header,cell,factor in [('g0001','B1','B2',1e-9),('g0002','E1','E2',1e-6)]:
                p=next(p for p in report['direct_metrics'] if p['group_id']==gid)
                provenance=p['provenance'];self.assertEqual(provenance['source_sheet'],'Data')
                self.assertEqual(provenance['source_cells'][0]['id'],cell)
                mapping=provenance['unit_conversion']['sheet_column_mapping']['id']
                self.assertEqual(mapping['header_cell'],header);self.assertEqual(mapping['factor_to_si'],factor)
            self.assertEqual(len(report['input_provenance']['sheet_column_mappings']),2)

    def test_frontmatter_keeps_review_flag_and_inferred_date_time_status(self):
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp);s,data,cfg,additional,report=self.report(temp)
            research_panels(data,s,d,additional,report);before=copy.deepcopy(s)
            context=s['research_context'];context.update(metadata_review_required=True,metadata_status='inferred',measurement_date='2026-09-23')
            context['fields']['measurement_date']['status']='inferred'
            context['fields']['measurement_time']={'value':None,'status':'missing','source':None}
            expected=copy.deepcopy(s);text=render_note(s,'Attachments/test',d).split('---')[1]
            for field in ('metadata_review_required: true','metadata_status: "inferred"','measurement_date_status: "inferred"','measurement_time_status: "missing"'):
                self.assertIn(field,text)
            self.assertEqual(s,expected)
            context.update(metadata_review_required=False,metadata_status='confirmed')
            context['fields']['measurement_date']['status']='confirmed'
            text=render_note(s,'Attachments/test',d).split('---')[1]
            self.assertIn('metadata_review_required: false',text);self.assertIn('measurement_date_status: "confirmed"',text)
            self.assertEqual(before['research_context']['fields']['measurement_date']['status'],'confirmed')

    def test_interpolation_records_both_brackets_signed_values_and_weights(self):
        data=pd.DataFrame({'vd':[-2,0],'id':[-3e-9,1e-9],'source_row':[10,11],'source_id_cell':['B10','B11'],'acquisition_order':[0,1]})
        sample=sample_at(data,'vd',-.5)
        self.assertAlmostEqual(sample['value'],0)
        self.assertEqual(sample['interpolation_weights'],[.25,.75])
        self.assertEqual([p['source_row'] for p in sample['source_points']],[10,11])
        self.assertEqual([p['signed_current_a'] for p in sample['source_points']],[-3e-9,1e-9])
        self.assertIsNone(sample_at(data,'vd',1)['value'])

    def report(self,temp,held=True):
        s,data=fixture(held=held);cfg=self.config(Path(temp));before=copy.deepcopy(s)
        additional=export_fet(data,s,Path(temp),cfg);report=export_report(data,s,Path(temp),cfg,additional)
        self.assertEqual(s,before)
        return s,data,cfg,additional,report

    def test_unit_confirmation_does_not_certify_ss_yfm_mobility_rr(self):
        with tempfile.TemporaryDirectory() as temp:
            s,data,cfg,additional,report=self.report(temp,held=False)
            self.assertEqual(report['groups'][0]['ss_summary']['metric_status'],'held')
            self.assertIsNone(report['groups'][0]['ss_summary']['value_min'])
            self.assertTrue(all(p['value'] is None for p in report['direct_metrics'] if p['parameter']=='ss_direct'))
            _,panels=research_panels(data,s,Path(temp),additional,report)
            self.assertEqual(next(p for p in panels if p['panel']=='e')['metric_status'],'held')
            for m in additional['extractions']:
                if m['parameter']=='vth_yfm':self.assertNotEqual(m['metric_status'],'confirmed')
            mobility=next(p for p in additional['points'] if p['parameter']=='mobility_linear')
            self.assertEqual(mobility['metric_status'],'candidate');self.assertTrue(mobility['assumptions'])
            self.assertEqual(report['ranked_rr'],[])
            for point in report['direct_metrics']:
                if point['parameter']!='ss_direct':continue
                reconstructed=sum(p['log10_abs_current']*p['derivative_weight_per_v'] for p in point['derivative_support'])
                self.assertAlmostEqual(reconstructed,point['signed_slope_dec_per_v'],places=9)

    def test_pair_history_floor_and_original_stress_are_separate_gates(self):
        from research_automation.comparison import REQUIRED
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp);s,data=fixture(held=False);positive=s['groups'][0]
            positive['conditions']={'vd':2}
            negative=copy.deepcopy(positive);negative['group_id']='g0002';negative['conditions']={'vd':-2}
            s['groups'].append(negative)
            data['id_a']=12e-9;neg=data.copy();neg['id_a']=-3e-9;neg['group_id']='g0002'
            curves=pd.concat([data,neg],ignore_index=True)
            cfg=self.config(d);cfg.data['science'].update(detection_limit_a=1e-9,detection_limit_evidence='synthetic validated floor')
            fields=s['research_context']['fields']
            for key in REQUIRED:fields[key]={'value':'synthetic same','status':'confirmed','source':'synthetic test fixture'}
            fields['illumination']={'value':'dark','status':'confirmed','source':'synthetic test fixture'}
            s['research_context']['illumination']='dark'
            additional=export_fet(curves,s,d,cfg)
            report=export_report(curves,s,d,cfg,additional)
            self.assertTrue(report['polarity_pairs']);self.assertTrue(all(p['rr']==4 for p in report['polarity_pairs']))
            self.assertTrue(all(next(r for r in p['metrics'] if r['parameter']=='rr_lower_bound')['availability']=='unavailable' for p in report['polarity_pairs']))
            fields['history']['status']='missing'
            report=export_report(curves,s,d,cfg,additional)
            self.assertTrue(all(p['rr'] is None for p in report['polarity_pairs']))
            fields['history']['status']='confirmed';negative['original_sweep']['min_v']=-40
            report=export_report(curves,s,d,cfg,additional)
            self.assertTrue(all(p['rr'] is None for p in report['polarity_pairs']))
            self.assertTrue(any('crop' in reason for p in report['polarity_pairs'] for reason in p['comparison_reasons']))

    def test_format_order_actual_files_absent_panels_and_preserved_audit(self):
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp);s,data,cfg,additional,report=self.report(temp)
            data.to_csv(d/'curves.csv',index=False,encoding='utf-8-sig')
            (d/'result.json').write_text(json.dumps(s),encoding='utf-8')
            files,manifest=research_panels(data,s,d,additional,report)
            s['figures']=files
            text=render_note(s,'Attachments/test',d)
            self.assertEqual([p['panel'] for p in manifest],list('abcdefghijklm'))
            body=text.split('<details>')[0]
            self.assertNotIn('{{',body);self.assertNotIn('None',body);self.assertNotIn('null',body)
            self.assertIn('report_format: fet-research-note-2',body);self.assertIn('QC PASS',body)
            for letter in 'dfghl':
                p=next(p for p in manifest if p['panel']==letter);self.assertIsNone(p['file'])
            for name in files:self.assertTrue(verify_png(d/name)['decoded']);self.assertIn(name,text)
            self.assertIn('<summary>감사 상세',text);self.assertIn('result.json',text)
            # A missing newly generated PNG becomes generation failure, without an invented link.
            (d/'figure2_b.png').unlink()
            text=render_note(s,'Attachments/test',d);body=text.split('<details>')[0]
            self.assertNotIn('figure2_b.png',body);self.assertIn('생성 실패',body)

    def test_save_failure_distinct_from_absence_and_does_not_claim_file(self):
        with tempfile.TemporaryDirectory() as temp:
            s,data,cfg,additional,report=self.report(temp)
            with patch('matplotlib.figure.Figure.savefig',side_effect=OSError('synthetic permission denial')):
                files,manifest=research_panels(data,s,Path(temp),additional,report)
            self.assertEqual(files,[])
            self.assertEqual(next(p for p in manifest if p['panel']=='b')['generation_status'],'failed')
            self.assertEqual(next(p for p in manifest if p['panel']=='f')['generation_status'],'unavailable')

    def test_confirmed_dark_date_preserved_light_not_promoted(self):
        with tempfile.TemporaryDirectory() as temp:
            s,data,cfg,additional,report=self.report(temp)
            research_panels(data,s,Path(temp),additional,report)
            s['research_context']['measurement_date']='2026-09-23'
            field=s['research_context']['fields']['measurement_date']
            self.assertEqual(field['status'],'confirmed')
            text=render_note(s,'Attachments/test',Path(temp));self.assertIn('2026-09-23',text)
            self.assertEqual(field['status'],'confirmed')
            field['status']='inferred';s['research_context']['fields']['illumination']['value']='light'
            text=render_note(s,'Attachments/test',Path(temp));self.assertIn('추정',text)
            self.assertEqual(field['status'],'inferred')


if __name__=='__main__':unittest.main()
