import copy
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
from research_automation.config import Config,DEFAULT
from research_automation.note_presentation import number,representative,render_note,fold,metric_text,usability
from research_automation.fet_parameters import export_fet
from research_automation.fet_methods import yfm_ss,geometry_profiles
from research_automation.note_index import publish_index


def fixture(held=True,axis='vg'):
    x=np.linspace(-2,2,81);current=(x+3)*1e-9
    g={'group_id':'g0001','axis':axis,'conditions':{'vd':1} if axis=='vg' else {'vg':0},
       'gate_block_id':'block-001','direction':'forward','branch_index':1,'units_review_required':held,
       'original_sweep':{'min_v':-2,'max_v':2},'n':len(x),'transfer_metrics':{},'rr_series':[],'fits':[]}
    frame=pd.DataFrame({'group_id':'g0001','x_v':x,'id_a':current,'gm_a_per_v':1e-9,
        'did_dvd_a_per_v':1e-9,'source_row':np.arange(len(x))+2,'source_x_cell':['A'+str(i+2) for i in range(len(x))],
        'source_id_cell':['B'+str(i+2) for i in range(len(x))],'metric_eligible':True,'segment_id':0})
    s={'groups':[g],'version':'1.4.0','source_filename':'transfer.xls','source_relative_path':'drain-fold/2026-09-23/transfer.xls',
       'job_id':'fixture','source_sha256':'hash','code_sha256':'code','qc':{'overall':'PASS','checks':[]},
       'research_context':{'device_name':'drain-fold','metadata_status':'missing','fields':{
           'device_name':{'value':'drain-fold','status':'inferred','source':'folder'},
           'measurement_date':{'value':'2026-09-23','status':'confirmed','source':'user'},
           'illumination':{'value':'dark','status':'inferred','source':'filename'}}},'figures':[]}
    return s,frame


class NotePresentationTests(unittest.TestCase):
    def test_signed_engineering_units(self):
        for value,unit,expected in [(-2e-9,'A','-2 nA'),(-3.2e-6,'A','-3.2 μA'),(-2e-9,'A/V','-2 nA/V'),
                                    (2e6,'Ω','2 MΩ'),(-4e-9,'S','-4 nS'),(1.5e-6,'m','1.5 μm')]:
            self.assertEqual(number(value,unit),expected)
        self.assertEqual(number(None,'A'),'추출하지 않음')

    def test_representative_uses_block_bias_and_order_not_extreme_metric(self):
        s,_=fixture();base=s['groups'][0]
        s['groups']=[dict(base,group_id='first',conditions={'vd':2}),dict(base,group_id='zero',conditions={'vd':0}),
                     dict(base,group_id='later',conditions={'vd':0},gate_block_id='block-002')]
        self.assertEqual(representative(s)['group_id'],'zero')

    def test_first_screen_and_three_metrics_never_promote_unit_hold(self):
        s,frame=fixture();g=s['groups'][0]
        g['transfer_metrics']={'internal_peak_abs':{'value':None,'candidate_value_assuming_si':-2e-9,
            'vg_v':-1,'unit':'A/V','metric_status':'unavailable','reason':'unconfirmed_voltage_or_current_units'}}
        before=copy.deepcopy(s)
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp);frame.to_csv(d/'curves.csv',index=False);(d/'result.json').write_text(json.dumps(s))
            text=render_note(s,'Attachments/test',d,'figure.png');body=text.split('## ⑧')[0]
        for heading in ('① 연구 질문','② 조건 한 줄','③ 현재 판단','④ 대표 근거 그림','⑤ 핵심 수치','⑥ 의미와 한계','⑦ 다음 확인'):
            self.assertIn(heading,body)
        self.assertLess(body.index('figure.png'),body.index('⑤ 핵심 수치'))
        self.assertNotIn('null',body);self.assertNotIn('None',body);self.assertNotIn('raw_peak_abs',body)
        self.assertNotIn('unconfirmed_voltage_or_current_units',body);self.assertNotIn('정량 지표 사용 가능',body)
        self.assertIn('-2 nA/V',body);self.assertIn('V/A 가정',body);self.assertEqual(s,before)
        self.assertNotIn('RR',body)

    def test_multiline_details_remain_inside_collapsed_callout(self):
        rendered=fold('QC',['```json','{\n  "value": null\n}','```'])
        self.assertTrue(all(line.startswith('>') for line in rendered[:-1]))

    def test_bound_ambiguous_candidate_unavailable_are_distinct(self):
        self.assertIn('≥',metric_text({'metric_status':'bound','bound_type':'lower','bound_value':3,'unit':'1'}))
        self.assertIn('모호함',metric_text({'metric_status':'ambiguous','value':100}))
        self.assertNotIn('100',metric_text({'metric_status':'ambiguous','value':100}))
        self.assertIn('검증 전',metric_text({'metric_status':'candidate','value':3,'unit':'1'}))
        self.assertIn('보류',metric_text({'metric_status':'unavailable','value':3}))

    def test_root_index_append_preserves_researcher_text_and_counts_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);data=copy.deepcopy(DEFAULT);(root/'config.json').write_text(json.dumps(data));cfg=Config(root/'config.json');cfg.ensure_dirs()
            experiments=cfg.paths['vault']/'Experiments';experiments.mkdir(exist_ok=True)
            original='사용자 메모 그대로\n';(experiments/'index.md').write_text(original)
            (cfg.paths['inbox']/'new.xls').write_bytes(b'not processed')
            s,_=fixture();index=publish_index(cfg,[(s,'Experiments/preview.md')],[],True)
            self.assertTrue((experiments/'index.md').read_text().startswith(original))
            text=index.read_text();self.assertIn('미처리/변경/읽기 확인 필요 1개',text)
            self.assertTrue((experiments/'최신 연구 결과.md').exists())


class AdditionalFETTests(unittest.TestCase):
    def test_g_and_gds_differ_signs_zero_division_holds_and_legacy_unchanged(self):
        s,frame=fixture(axis='vd');before=copy.deepcopy(s)
        with tempfile.TemporaryDirectory() as temp:
            cfg=type('Cfg',(),{'paths':{'vault':Path(temp)}})()
            report=export_fet(frame,s,Path(temp),cfg)
        g=next(p for p in report['points'] if p['parameter']=='conductance' and p['evaluation_voltage_v']==-2)
        self.assertEqual(g['candidate_value_assuming_si'],-.5e-9);self.assertIsNone(g['value'])
        d=next(p for p in report['points'] if p['parameter']=='gds');self.assertEqual(d['candidate_value_assuming_si'],1e-9)
        self.assertFalse(any(p['parameter']=='conductance' and p['evaluation_voltage_v']==0 for p in report['points']))
        self.assertEqual(s,before)

    def test_yfm_known_threshold_and_unit_hold_without_best_fit_search(self):
        s,frame=fixture();x=np.linspace(1,10,181);vth=.4;beta=1e-7;theta=.1
        current=beta*(x-vth-.5)/(1+theta*(x-vth));gm=beta*(1+theta*.5)/(1+theta*(x-vth))**2
        data=pd.DataFrame({'x_v':x,'id_a':current,'gm_a_per_v':gm,'gm_local_w4_a_per_v':gm,'source_row':np.arange(len(x)),'segment_id':0})
        metrics,_=yfm_ss(s['groups'][0],data,{})
        m=next(m for m in metrics if m['parameter']=='vth_yfm')
        self.assertAlmostEqual(m['candidate_value_assuming_si'],vth,places=10)
        self.assertIsNone(m['value']);self.assertEqual(m['metric_status'],'unavailable')
        self.assertIn('no best-R²',m['automatic_window_rule'])

    def test_ss_min_and_average_on_exact_exponential(self):
        s,_=fixture(held=False);x=np.linspace(0,1,501);ss=.3;current=1e-12*10**(x/ss);gm=current*np.log(10)/ss
        data=pd.DataFrame({'x_v':x,'id_a':current,'gm_a_per_v':gm,'gm_local_w0.1_a_per_v':gm,'segment_id':0})
        metrics,_=yfm_ss(s['groups'][0],data,{'yfm':{'gm_window_v':.1}})
        for key in ('ss_min','ss_average'):
            m=next(m for m in metrics if m['parameter']==key)
            self.assertAlmostEqual(m['value'],300,places=8);self.assertEqual(m['metric_status'],'candidate')
            self.assertFalse(m['subthreshold_region_confirmed'])

    def test_yfm_does_not_bridge_removed_rows_or_zero_vds(self):
        s,frame=fixture();data=frame.iloc[[0,2,4,6,8,10,12,14,16,18]]
        metrics,_=yfm_ss(s['groups'][0],data,{})
        self.assertIsNone(next(m for m in metrics if m['parameter']=='vth_yfm')['value'])
        s['groups'][0]['conditions']['vd']=0
        metrics,_=yfm_ss(s['groups'][0],frame,{})
        self.assertNotIn('candidate_value_assuming_si',next(m for m in metrics if m['parameter']=='vth_yfm'))

    def test_geometry_comes_from_user_while_permittivity_stays_assumed(self):
        profiles=geometry_profiles();self.assertEqual(profiles['drainfold']['channel_length_m']['value'],1.5e-6)
        self.assertEqual(profiles['centerfold']['channel_length_m']['value'],2e-6)
        for profile in profiles.values():
            self.assertEqual(profile['channel_width_m']['value'],400e-9)
            self.assertEqual(profile['oxide_thickness_m']['value'],90e-9)
            self.assertEqual(profile['cox_f_per_m2']['status'],'assumed')
            self.assertAlmostEqual(profile['cox_f_per_m2']['value'],3.83681471888e-4)

class SpecialNoteTests(unittest.TestCase):
    def test_failure_note_preserves_error_evidence_without_internal_codes_in_body(self):
        from research_automation.special_notes import failure_note
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'config.json').write_text(json.dumps(copy.deepcopy(DEFAULT)))
            cfg=Config(root/'config.json');cfg.ensure_dirs()
            diagnostic=root/'failed.json';data={'job_id':'fail','source_relative_path':'bad.xls','parse_status':'failed','error':'NoMeasurementHeader: missing'}
            diagnostic.write_text(json.dumps(data));before=diagnostic.read_bytes()
            path=failure_note(diagnostic,cfg);text=path.read_text();body=text.split('## ⑧')[0]
            self.assertIn('파일 읽기 실패',body);self.assertNotIn('NoMeasurementHeader',body)
            self.assertEqual(diagnostic.read_bytes(),before)
            for link in re.findall(r'\[\[([^\]|]+)',text):self.assertTrue((cfg.paths['vault']/link).is_file())

    def test_photo_signed_difference_note_and_exclusion_summary(self):
        from research_automation.special_notes import photo_note
        pair={'metric_status':'candidate','dark_group_id':'g1','light_group_id':'g2','dark_note':'dark.md','light_note':'light.md',
              'points':[{'axis':'vg','evaluation_voltage_v':-1,'signed_delta_id_a':-2e-9,'delta_abs_id_a':2e-9,'responsivity_a_per_w':None}]}
        before=copy.deepcopy(pair)
        with tempfile.TemporaryDirectory() as temp:
            text=photo_note([pair],'Attachments/photo',Path(temp),{'다른 소자':2000},3)
            self.assertTrue((Path(temp)/'note_photo_signed_delta.png').is_file())
        body=text.split('## ⑧')[0];self.assertIn('-2 nA',body);self.assertIn('2 nA',body)
        self.assertIn('다른 소자: 2000개',text);self.assertIn('사용자 선택 대기 3개',text)
        self.assertEqual(pair,before);self.assertNotIn('None',body);self.assertNotIn('null',body)

class ComparisonPresentationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        (self.root/'config.json').write_text(json.dumps(copy.deepcopy(DEFAULT)))
        self.cfg=Config(self.root/'config.json');self.cfg.ensure_dirs()
    def tearDown(self):self.temp.cleanup()
    def records(self,other_date=False,other_sweep=False):
        from research_automation.comparison import REQUIRED
        jobs=[]
        for lighting in ('dark','light'):
            s,frame=fixture(held=False)
            c=s['research_context'];c.update(device_name='same',illumination=lighting,measurement_date='2026-09-24' if lighting=='light' and other_date else '2026-09-23')
            c['fields']={k:{'value':'same','status':'confirmed','source':'synthetic'} for k in REQUIRED}
            c['fields'].update(illumination={'value':lighting,'status':'confirmed','source':'synthetic'},measurement_date={'value':c['measurement_date'],'status':'confirmed','source':'synthetic'})
            s.update(schema_version=4,source_relative_path=lighting+'.csv',source_sha256=lighting,job_id=lighting,vault_note_relative_path='Experiments/'+lighting+'.md')
            if lighting=='light':frame['id_a']+=1e-9
            if lighting=='light' and other_sweep:s['groups'][0]['original_sweep']['min_v']=-40
            directory=self.cfg.paths['analysis']/lighting;directory.mkdir()
            (directory/'result.json').write_text(json.dumps(s));frame.to_csv(directory/'curves.csv',index=False)
            (self.cfg.paths['vault']/s['vault_note_relative_path']).parent.mkdir(exist_ok=True)
            (self.cfg.paths['vault']/s['vault_note_relative_path']).write_text('User original')
            jobs.append({'completed_at':lighting,'result_path':str(directory/'result.json')})
        return jobs
    def test_cross_date_requires_explicit_selection_and_keeps_legacy_guard(self):
        from research_automation.comparison_catalog import publish
        jobs=self.records(other_date=True)
        before={j['result_path']:Path(j['result_path']).read_bytes() for j in jobs}
        result=publish(self.cfg,jobs);self.assertEqual(result['pairs'],0);self.assertEqual(result['date_selection_pending'],1)
        selected=publish(self.cfg,jobs,selected_sources=['dark.csv','light.csv']);self.assertEqual(selected['eligible'],1)
        text=Path(selected['note']).read_text();self.assertIn('다른 날짜를 사용자가 선택',text)
        self.assertEqual(before,{j['result_path']:Path(j['result_path']).read_bytes() for j in jobs})
        self.assertTrue(all((self.cfg.paths['vault']/link).is_file() for link in re.findall(r'\[\[([^\]|]+)',text)))
    def test_original_sweep_mismatch_is_aggregated_and_never_computed(self):
        from research_automation.comparison_catalog import publish
        result=publish(self.cfg,self.records(other_sweep=True))
        self.assertEqual(result['pairs'],0);self.assertEqual(sum(result['excluded_by_reason'].values()),1)
        text=Path(result['note']).read_text();self.assertIn('crop으로 해결 안 됨',text)

class MobilityAndSettingsTests(unittest.TestCase):
    def test_signed_mobility_cm2_conversion_and_assumptions_preserve_input(self):
        s,data=fixture(held=False);data['gm_a_per_v']=-1e-9;before=data.copy(deep=True)
        with tempfile.TemporaryDirectory() as temp:
            cfg=type('Cfg',(),{'paths':{'vault':Path(temp)}})()
            report=export_fet(data,s,Path(temp),cfg)
        point=next(p for p in report['points'] if p['parameter']=='mobility_linear')
        cox=8.8541878128e-12*3.9/90e-9
        self.assertAlmostEqual(point['value'],1.5e-6/(400e-9*cox)*-1e-9*1e4)
        self.assertEqual(point['unit'],'cm²/(V s)');self.assertEqual(point['metric_status'],'candidate')
        self.assertEqual(len(point['assumptions']),2);pd.testing.assert_frame_equal(data,before)
    def test_settings_reject_wrong_units_and_preserve_prior_sidecar(self):
        from research_automation.fet_settings import save_settings
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);(p/'config.json').write_text(json.dumps(copy.deepcopy(DEFAULT)));cfg=Config(p/'config.json');cfg.ensure_dirs()
            data={'devices':{'drain-fold':geometry_profiles()['drainfold']}}
            path=save_settings(cfg,data);before=path.read_bytes()
            bad=copy.deepcopy(data);bad['devices']['drain-fold']['channel_length_m']['unit']='nm'
            with self.assertRaises(ValueError):save_settings(cfg,bad)
            self.assertEqual(path.read_bytes(),before)
            save_settings(cfg,data);self.assertTrue(list(path.parent.glob('*_preserved_*.json')))

class IndexCoverageTests(unittest.TestCase):
    def test_54_current_notes_and_69_old_results_do_not_claim_full_reprocessing(self):
        import hashlib
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'config.json').write_text(json.dumps(copy.deepcopy(DEFAULT)));cfg=Config(root/'config.json');cfg.ensure_dirs()
            jobs=[];records=[]
            for n in range(69):
                s,_=fixture();s['source_relative_path']=f'sample-{n}.xls'
                raw=b'synthetic coverage fixture';(cfg.paths['inbox']/s['source_relative_path']).write_bytes(raw)
                old=cfg.paths['analysis']/f'old-{n}.json';old.write_text(json.dumps(s))
                jobs.append({'result_path':str(old),'source':s['source_relative_path'],'source_hash':hashlib.sha256(raw).hexdigest(),'status':'completed'})
                if n<54:
                    new=copy.deepcopy(s);new['version']='1.5.0';path=cfg.paths['analysis']/f'new-{n}.json';path.write_text(json.dumps(new));jobs.append(dict(jobs[-1],result_path=str(path)))
                    records.append((new,f'Experiments/note-{n}.md'))
            text=publish_index(cfg,records,jobs).read_text()
            self.assertIn('새 형식 54개 파일',text);self.assertIn('v1.4.0: 저장 완료 69개 파일',text)
            self.assertIn('v1.5.0: 저장 완료 54개 파일',text);self.assertIn('포함하지 않은 저장 결과 15개',text)
            self.assertNotIn('전체 재처리가 완료되었습니다',text)
