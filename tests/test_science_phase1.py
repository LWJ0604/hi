import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from research_automation.analysis import split_sweeps
from research_automation.config import Config, DEFAULT
from research_automation.ingest import load_measurements
from research_automation.metadata_review import build_context, load_override, save_override
from research_automation.organization import lighting_in
from research_automation.science_qc import point_qc


class ParsingMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        (self.root/'config.json').write_text(json.dumps(copy.deepcopy(DEFAULT)), encoding="utf-8")
        self.cfg=Config(self.root/'config.json'); self.cfg.ensure_dirs()
    def tearDown(self):
        from test_cleanup import close_test_logs
        close_test_logs(self.temp.name)
        self.temp.cleanup()
    def total_book(self,missing=False):
        v=np.linspace(-40,40,161); biases=np.arange(-2,2.1,.5)
        rows=[[None]+[f'Vds = {b:g} V' for b in biases],['GateV']+['DrainI']*9]
        rows += [[x]+[(x+50)*(abs(b)+1)*1e-9 for b in biases] for x in v]
        if missing:rows[82][0]='--'
        rows += [['--']*10 for _ in v]
        path=self.root/'id-Vg-total.xlsx'
        pd.DataFrame(rows).to_excel(path,index=False,header=False)
        return path
    def test_repeated_headers_nine_correct_biases_padding_and_cells(self):
        path=self.total_book(); before=hashlib.sha256(path.read_bytes()).hexdigest()
        sheets,_=load_measurements(path,self.cfg,{})
        self.assertEqual(len(sheets),9)
        for i,s in enumerate(sheets):
            self.assertEqual(len(s['data']),161); self.assertEqual(s['padding_rows'],161)
            self.assertEqual(s['invalid_rows'],0); self.assertEqual(s['data']['vd'].unique().tolist(),[-2+i*.5])
            self.assertEqual(s['column_mapping']['id']['source_column'],i+2)
            self.assertEqual(s['data'].iloc[0]['source_id_cell'],chr(66+i)+'3')
            self.assertEqual(s['column_mapping']['vd']['source_cell'],chr(66+i)+'1')
        self.assertEqual(before,hashlib.sha256(path.read_bytes()).hexdigest())
    def test_internal_placeholder_is_gap_and_does_not_connect_sweeps(self):
        sheets,_=load_measurements(self.total_book(True),self.cfg,{})
        self.assertEqual(sheets[0]['invalid_rows'],1)
        branches=split_sweeps(sheets[0]['data'],'vg')
        self.assertEqual(len(branches),2)
        self.assertEqual(sum(len(b) for _,b in branches),160)
        self.assertIn(83,sheets[0]['parse_status']['missing_source_rows'])
    def test_withlight_and_unmarked_conflict(self):
        for name in ['withlight','with light','with_light','light']:
            self.assertEqual(lighting_in(name),['light'])
        self.assertEqual(lighting_in('dark_withlight'),['dark','light'])
        c=self.context('device/2026-09-23/Id-Vg.xls')
        self.assertEqual(c['illumination'],'unknown')
        self.assertEqual(c['fields']['illumination']['status'],'missing')
        clock=self.context('device/2026-09-23/Id-Vg.xls',{'hold_time_s':3.,'sweep_delay_s':.5})
        self.assertEqual(clock['fields']['hold_s']['source'],'Settings/Hold Time')
        self.assertEqual(clock['fields']['sweep_delay_s']['source'],'Settings/Sweep Delay')
    def context(self,relative,instrument=None):
        return build_context(relative,{},instrument or {},{'axis':'vg','groups':[{'axis':'vg','conditions':{'vd':2.},'x_min_v':-40.,'x_max_v':40.}]},self.cfg,'hash')
    def test_user_date_equipment_clock_and_delay_conflict_persist(self):
        relative='device/2026-09-23/dark sweep delay 0.1s.xls'
        save_override(self.cfg,relative,'hash',{'measurement_date':'2026-09-23','sweep_delay_s':.1},'사용자 측정일/설정 확인')
        c=self.context(relative,{'measurement_timestamp_raw':'09/24/2026 02:27:29','sweep_delay_s':0.})
        self.assertEqual(c['measurement_date'],'2026-09-23')
        self.assertEqual(c['fields']['measurement_date']['status'],'confirmed')
        self.assertEqual(c['equipment_record_time']['value'],'09/24/2026 02:27:29')
        self.assertEqual(c['fields']['sweep_delay_s']['status'],'conflict')
        self.assertEqual(load_override(self.cfg,relative,'hash')['fields']['sweep_delay_s']['value'],.1)
        self.assertEqual(self.context(relative,{'sweep_delay_s':0.})['fields']['sweep_delay_s']['status'],'conflict')
    def test_missing_leakage_is_not_assessed_and_flags_do_not_delete(self):
        f=pd.DataFrame({'source_row':[1,2,3],'vd':[-1.,0.,1.],'id':[-2e-9,1e-9,3e-9]})
        out,qc=point_qc(f,{},self.cfg)
        self.assertEqual(next(x for x in qc if x['code']=='gate_leakage')['status'],'not_assessed')
        self.assertEqual(len(out),len(f)); self.assertEqual(out['id'].tolist(),f['id'].tolist())
