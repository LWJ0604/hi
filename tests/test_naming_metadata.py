"""Synthetic naming-rule fixtures; no real researcher confirmations are created."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd
import yaml

from research_automation.config import Config, DEFAULT
from research_automation.naming_metadata import automatic_conditions, resolve_conditions
from research_automation.benchmark_data import load_source
from research_automation.benchmark_batch import generate
from research_automation.metadata_review import build_context, override_path
from research_automation.observation_batch import observe
from research_automation.util import digest, parse_filename


class NamingMetadataTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.data=copy.deepcopy(DEFAULT)
        self.cfg=self.config();self.cfg.ensure_dirs()

    def config(self):
        path=self.root/'config.json';path.write_text(json.dumps(self.data),encoding='utf-8')
        return Config(path)

    def automatic(self,relative):
        return automatic_conditions(self.cfg.paths['inbox']/relative,self.cfg)

    def source(self,relative):
        path=self.cfg.paths['inbox']/relative;path.parent.mkdir(parents=True,exist_ok=True)
        x=np.linspace(-2,2,17)
        pd.DataFrame({'DrainV (V)':x,'GateV (V)':0.,'DrainI (A)':1e-8*np.sinh(x)}).to_excel(path,index=False)
        return path

    def device(self,path,conditions):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('---\n'+yaml.safe_dump({'schema_version':1,'run_conditions':conditions},allow_unicode=True,sort_keys=False)+'---\nSynthetic fixture memo.\n',encoding='utf-8')
        return path

    def test_light_substring_case_and_extension(self):
        for name in ['with light.xls','LIGHT.XLSX','WithLiGhT.xlsx','dark_withlight.xlsx']:
            with self.subTest(name=name):
                item=self.automatic('device/2026-09-23/'+name)['illumination']
                self.assertEqual(item['value'],'light')
                self.assertEqual(item['source'],'filename')
                self.assertEqual(item['verification'],'naming_rule')
                self.assertEqual(item['status'],'inferred');self.assertEqual(item['history'],[])

    def test_without_light_is_dark_and_folders_are_ignored(self):
        for name in ['data.xlsx','with dark.xls','unknown.xlsx']:
            with self.subTest(name=name):
                self.assertEqual(self.automatic('light-device/light/2026-09-23/'+name)['illumination']['value'],'dark')
        self.assertNotIn('illumination',self.automatic('device/2026-09-23/light.csv'))

    def test_valid_date_folder_formats_and_leap_day(self):
        for folder,expected in [('2026-09-23','2026-09-23'),('2026.9.3','2026-09-03'),('2026_9_3','2026-09-03'),('2024-02-29','2024-02-29'),('2026/09/23','2026-09-23')]:
            with self.subTest(folder=folder):
                item=self.automatic('device/'+folder+'/원본/data.xlsx')['measurement_date']
                self.assertEqual(item['value'],expected);self.assertEqual(item['source'],'folder_name')
                self.assertEqual(item['verification'],'naming_rule');self.assertEqual(item['history'],[])

    def test_invalid_missing_partial_and_generated_dates_remain_unknown(self):
        for folder in ['2026-02-30','2025-02-29','2026-13-01','09-23','2026-09','260923','2026-10-07_pair_demo','분석/2026-10-08','원본/2026-10-08','analysis/2026-10-08']:
            with self.subTest(folder=folder):
                self.assertNotIn('measurement_date',self.automatic('device/'+folder+'/data2026-09-23.xlsx'))
        self.assertNotIn('measurement_date',self.automatic('device/data2026-09-23.xlsx'))

    def test_nearest_valid_classification_date_and_raw_boundary(self):
        for relative,expected in [('device/2026-09-09/group/2026-09-23/data.xlsx','2026-09-23'),('device/2026-09-09/2026-02-30/data.xlsx','2026-09-09'),('device/2026-09-23/원본/2026-10-08/data.xlsx','2026-09-23'),('device/2026-09-23/analysis/2026-10-08/data.xlsx','2026-09-23')]:
            with self.subTest(relative=relative):self.assertEqual(self.automatic(relative)['measurement_date']['value'],expected)

    def test_selected_raw_inbox_uses_parent_date_without_reading_parent_metadata(self):
        self.data['paths']['inbox']='device/2026-09-23/원본';self.cfg=self.config();self.cfg.ensure_dirs()
        path=self.source('data.xlsx');loaded=load_source(path,self.cfg)
        self.assertEqual(loaded['conditions']['measurement_date']['value'],'2026-09-23')
        self.assertEqual(loaded['context']['sources'],[])

    def test_outside_root_does_not_supply_date(self):
        fields=automatic_conditions(self.root/'2026-09-23/data.xlsx',self.cfg)
        self.assertNotIn('measurement_date',fields)

    def test_switches_and_old_config_backfill_are_read_only(self):
        self.data['organization'].pop('naming_rules');self.cfg=self.config()
        before=digest(self.cfg.path)
        self.assertEqual(self.cfg.data['organization']['naming_rules'],DEFAULT['organization']['naming_rules'])
        self.assertEqual(before,digest(self.cfg.path))
        self.data['organization']['naming_rules']={'date_from_folder':False,'excel_light_from_filename':False}
        self.cfg=self.config();self.assertEqual(self.automatic('device/2026-09-23/data.xlsx'),{})

    def test_invalid_rule_settings_are_rejected(self):
        for rules in ({'date_from_folder':'true','excel_light_from_filename':True},{'date_from_folder':True},[],{'date_from_folder':True,'excel_light_from_filename':True,'extra':True}):
            with self.subTest(rules=rules):
                self.data['organization']['naming_rules']=rules
                with self.assertRaises(ValueError):self.config()

    def test_valid_explicit_values_keep_source_and_confirmation(self):
        declared={'measurement_date':{'value':'2026-09-09','source':'synthetic fixture only','verification':'user_confirmed'},'illumination':{'value':'light','source':'synthetic fixture only','verification':'reported'}}
        before=copy.deepcopy(declared)
        conditions,notices=resolve_conditions(self.cfg.paths['inbox']/'device/2026-09-23/data.xlsx',self.cfg,declared)
        self.assertEqual(declared,before)
        for key in declared:
            for field in declared[key]:self.assertEqual(conditions[key][field],declared[key][field])
            self.assertIn('naming_rule_candidate',conditions[key])
        self.assertEqual(len(notices),2);self.assertIn('device.md',notices[0])

    def test_null_unknown_and_unconfirmed_placeholders_fall_back(self):
        for value in [None,'unknown','unconfirmed','',{'invalid':'value'},False,'2026-02-30']:
            with self.subTest(value=value):
                declaration={key:{'value':value,'source':'synthetic placeholder','verification':'unconfirmed'} for key in ['measurement_date','illumination']}
                fields,notices=resolve_conditions(self.cfg.paths['inbox']/'device/2026-09-23/LIGHT.xlsx',self.cfg,declaration)
                self.assertEqual(fields['measurement_date']['value'],'2026-09-23')
                self.assertEqual(fields['illumination']['value'],'light')
                self.assertTrue(all(f['verification']=='naming_rule' for f in fields.values()));self.assertEqual(notices,[])

    def test_concrete_unconfirmed_declaration_is_not_promoted(self):
        fields,_=resolve_conditions(self.cfg.paths['inbox']/'device/2026-09-23/light.xlsx',self.cfg,{'illumination':{'value':'dark','verification':'unconfirmed'}})
        self.assertEqual(fields['illumination']['value'],'dark');self.assertEqual(fields['illumination']['verification'],'unconfirmed')

    def test_scoped_override_precedes_device_and_keeps_history(self):
        override={'illumination':{'value':'light','source':'user_override','status':'confirmed','history':[{'reason':'synthetic fixture only'}]}}
        fields,notices=resolve_conditions(self.cfg.paths['inbox']/'device/2026-09-23/data.xlsx',self.cfg,{'illumination':{'value':'dark','verification':'user_confirmed'}},override)
        self.assertEqual(fields['illumination']['source'],'user_override');self.assertEqual(fields['illumination']['verification'],'user_confirmed')
        self.assertEqual(fields['illumination']['history'],override['illumination']['history']);self.assertIn('사용자 확인 이력',notices[0])

    def test_all_files_multiple_devices_receive_rules_without_declared_pair(self):
        for relative in ['소자 A/2026-09-23/원본/one.xlsx','소자 A/2026-09-23/원본/two_LIGHT.xlsx','소자 B/2026-09-09/원본/three.xlsx']:
            with self.subTest(relative=relative):
                loaded=load_source(self.source(relative),self.cfg)
                self.assertIsNone(loaded['role'])
                self.assertEqual(loaded['conditions']['measurement_date']['value'],relative.split('/')[1])
                self.assertEqual(loaded['conditions']['illumination']['value'],'light' if 'LIGHT' in relative else 'dark')
                self.assertIsNone(loaded['geometry']['temperature_C']);self.assertIsNone(loaded['geometry']['L_um'])
        self.assertFalse(override_path(self.cfg).exists())

    def test_declared_values_affect_only_the_linked_file_and_preserve_metadata(self):
        parent=self.cfg.paths['inbox']/'device/2026-09-23/device.md'
        self.device(parent,{'IdVd':{'file':'one.xlsx','measurement_date':{'value':'2026-09-09','source':'synthetic fixture only','verification':'user_confirmed'},'illumination':{'value':'light','source':'synthetic fixture only','verification':'user_confirmed'}}})
        before=digest(parent)
        one=load_source(self.source('device/2026-09-23/one.xlsx'),self.cfg)
        two=load_source(self.source('device/2026-09-23/two.xlsx'),self.cfg)
        self.assertEqual(one['conditions']['measurement_date']['value'],'2026-09-09')
        self.assertEqual(one['conditions']['illumination']['value'],'light')
        self.assertEqual(two['conditions']['measurement_date']['value'],'2026-09-23')
        self.assertEqual(two['conditions']['illumination']['value'],'dark')
        self.assertEqual(digest(parent),before)

    def test_review_context_preserves_manual_value_and_exposes_disagreement(self):
        path=self.source('device/2026-09-23/one.xlsx')
        self.device(path.parent/'device.md',{'IdVd':{'file':path.name,'illumination':{'value':'light','source':'synthetic fixture only','verification':'user_confirmed'}}})
        summary={'axis':'vd','groups':[{'axis':'vd','x_min_v':-2,'x_max_v':2,'conditions':{'vg':0}}]}
        context=build_context(path.relative_to(self.cfg.paths['inbox']).as_posix(),parse_filename(path.name),{},summary,self.cfg,digest(path))
        item=context['fields']['illumination']
        self.assertEqual(item['value'],'light');self.assertEqual(item['status'],'confirmed')
        self.assertTrue(item['candidate_disagreement']);self.assertTrue(context['condition_notices'])
        self.assertEqual(context['fields']['measurement_date']['verification'],'naming_rule')

    def test_real_report_format_shows_auto_sources_and_manual_disagreement(self):
        path=self.source('device/2026-09-23/one.xlsx')
        self.device(path.parent/'device.md',{'IdVd':{'file':path.name,'illumination':{'value':'light','source':'synthetic fixture only','verification':'user_confirmed'}}})
        result=generate(self.cfg,[path.relative_to(self.cfg.paths['inbox']).as_posix()])
        text=Path(result['markdown']).read_text(encoding='utf-8')
        self.assertIn('2026-09-23',text);self.assertIn('날짜 폴더',text)
        self.assertIn('이름 규칙 자동 입력',text);self.assertIn('조건 확인:',text)
        self.assertIn('device.md의 light',text)
        self.assertFalse(override_path(self.cfg).exists())

    def test_observation_snapshot_uses_original_path_and_no_generated_date(self):
        path=self.source('device/2026-09-23/원본/LIGHT.xlsx');before=digest(path)
        result=observe(self.cfg,[path.relative_to(self.cfg.paths['inbox']).as_posix()])
        self.assertEqual(result['files'][0]['status'],'completed')
        text=Path(result['files'][0]['markdown']).read_text(encoding='utf-8')
        self.assertIn('2026-09-23',text);self.assertIn('이름 규칙 자동 입력',text)
        payload=json.loads((Path(result['files'][0]['html']).parent/'observations.json').read_text(encoding='utf-8'))
        self.assertEqual(payload['metadata_fields']['measurement_date']['value'],'2026-09-23')
        self.assertEqual(payload['metadata_fields']['illumination']['value'],'light')
        self.assertFalse(payload['metadata_status']['human_overrides_created'])
        self.assertEqual(before,digest(path));self.assertFalse(override_path(self.cfg).exists())
