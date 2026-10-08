"""Synthetic regressions for metadata evidence and malformed field isolation."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd
import yaml

from research_automation.config import Config,DEFAULT
from research_automation.device_metadata import context_for,measurement_config,read_device,value
from research_automation.benchmark_data import geometry,load_source,output_benchmarks,transfer_benchmarks
from research_automation.benchmark_batch import generate
from research_automation.util import digest


class DeviceMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);data=copy.deepcopy(DEFAULT)
        data['benchmark']['electrode_pair']='p'
        config=self.root/'config.json';config.write_text(json.dumps(data),encoding='utf-8')
        self.cfg=Config(config);self.cfg.ensure_dirs()
        self.evidence='synthetic test fixture only'
        def quantity(number,unit):
            return {'value':number,'unit':unit,'source':self.evidence,'verification':'user_confirmed'}
        self.parent={
            'device_name':{'value':'fixture device','source':self.evidence,'verification':'user_confirmed'},
            'active_electrode_pair':'p',
            'electrode_pairs':{'p':{'L':quantity(1.5,'um'),'W':quantity(.4,'um')}},
            'structure':{'gate_dielectric':{'thickness':quantity(90,'nm'),'relative_permittivity':quantity(3.9,'dimensionless')}},
            'run_conditions':{'temperature':quantity(25,'degC'),'units':{'voltage':'V','current':'A','source':self.evidence,'verification':'user_confirmed'}}}
        self.parent_path=self.device(self.parent)
        self.parent_hash=digest(self.parent_path)

    def device(self,fields,child=False):
        path=self.cfg.paths['inbox']/('child/device.md' if child else 'device.md')
        path.parent.mkdir(parents=True,exist_ok=True)
        fields={'schema_version':1,**fields}
        path.write_text('---\n'+yaml.safe_dump(fields,allow_unicode=True,sort_keys=False)+'---\nSynthetic memo stays unchanged.\n',encoding='utf-8')
        return path

    def source(self,name='child/data.csv',transfer=True,units=True):
        path=self.cfg.paths['inbox']/name;path.parent.mkdir(parents=True,exist_ok=True)
        x=np.linspace(-2,2,17)
        frame=pd.DataFrame({'GateV (V)':x,'DrainV (V)':1.,'DrainI (A)':1e-8+2e-9*x,'GateI (A)':1e-12}) if transfer else pd.DataFrame({'DrainV (V)':x,'GateV (V)':0.,'DrainI (A)':1e-8*np.sinh(x)})
        if not units:frame.columns=[c.split(' (')[0] for c in frame]
        frame.to_csv(path,index=False,encoding='utf-8');return path

    def test_child_field_does_not_borrow_unit_source_or_confirmation(self):
        path=self.source()
        for replacement in ({'value':9},{'value':9,'unit':'um'},{'unit':'nm'},{'value':1.5},{'source':'new synthetic evidence'}):
            with self.subTest(replacement=replacement):
                child=self.device({'electrode_pairs':{'p':{'L':replacement}}},child=True)
                loaded=load_source(path,self.cfg);record=loaded['context']['data']['electrode_pairs']['p']['L']
                self.assertEqual(record['verification'],'unconfirmed')
                self.assertEqual(record.get('unit'),replacement.get('unit'))
                self.assertEqual(record.get('source'),replacement.get('source'))
                self.assertIsNone(loaded['geometry']['L_um'])
                self.assertEqual(loaded['geometry']['W_um'],.4)
                self.assertEqual(loaded['context']['provenance']['electrode_pairs.p.L.verification'],str(child.resolve()))
                self.assertTrue(loaded['context']['warnings'])
        self.assertEqual(digest(self.parent_path),self.parent_hash)

    def test_complete_child_field_uses_its_own_explicit_evidence(self):
        child=self.device({'electrode_pairs':{'p':{'L':{'value':9,'unit':'um','source':'new synthetic evidence','verification':'user_confirmed'}}}},child=True)
        loaded=load_source(self.source(),self.cfg)
        self.assertEqual(loaded['geometry']['L_um'],9)
        self.assertEqual(loaded['geometry']['W_um'],.4)
        self.assertEqual(loaded['context']['data']['electrode_pairs']['p']['L']['source'],'new synthetic evidence')
        self.assertEqual(loaded['context']['provenance']['electrode_pairs.p.L.value'],str(child.resolve()))

    def test_partial_unit_profile_is_not_a_confirmed_parent_profile(self):
        self.device({'run_conditions':{'units':{'voltage':'mV'}}},child=True)
        path=self.source(units=False);context=context_for(path,self.cfg)
        units=context['data']['run_conditions']['units']
        self.assertEqual(units['verification'],'unconfirmed')
        self.assertIsNone(units.get('current'));self.assertIsNone(units.get('source'))
        self.assertFalse(measurement_config(context,self.cfg).data['measurement_profile']['confirmed'])
        self.assertEqual(len(load_source(path,self.cfg)['points']),17)

    def test_redeclaring_file_does_not_carry_the_previous_date(self):
        self.parent['run_conditions']['IdVg']={'file':'data.csv','measurement_date':{'value':'2026-09-23','source':self.evidence,'verification':'user_confirmed'}}
        self.device(self.parent);self.source('data.csv')
        self.device({'run_conditions':{'IdVg':{'file':'data.csv'}}},child=True)
        loaded=load_source(self.source(),self.cfg)
        self.assertEqual(loaded['role'],'IdVg')
        self.assertNotIn('measurement_date',loaded['conditions'])
        self.assertEqual(loaded['geometry']['temperature_C'],25)

    def test_malformed_selection_holds_mobility_and_retains_raw_and_gm(self):
        path=self.source()
        for selection in (['p'],{'value':['p']},True,1,{'value':True},{'value':'p','verification':['bad']},''):
            with self.subTest(selection=selection):
                self.device({'active_electrode_pair':selection},child=True)
                loaded=load_source(path,self.cfg);result=transfer_benchmarks(loaded,self.cfg)
                self.assertEqual(len(loaded['points']),17)
                self.assertIsNone(loaded['geometry']['electrode_pair'])
                self.assertTrue(loaded['context']['warnings'])
                self.assertTrue(np.isfinite(result['frame'].gm_central_A_V.iloc[1:-1]).all())
                self.assertTrue(result['metrics'][0]['gm_peaks'])
                self.assertNotIn('mu_apparent_central_cm2_Vs',result['frame'])

    def test_malformed_selection_does_not_block_RR(self):
        self.device({'active_electrode_pair':['p']},child=True)
        loaded=load_source(self.source(transfer=False),self.cfg)
        result=output_benchmarks(loaded,self.cfg,fit=False)
        self.assertEqual(len(loaded['points']),17)
        np.testing.assert_allclose(result['rr'].RR,1)

    def test_malformed_quantity_does_not_restore_confirmed_parent_value(self):
        path=self.source()
        cases=[{'electrode_pairs':{'p':{'L':item}}} for item in ([9],{'value':[9]},{'value':9,'unit':['um']},{'value':9,'source':{}},{'value':9,'verification':True})]
        cases += [{'electrode_pairs':['p']},{'electrode_pairs':{'p':'bad'}},{'structure':{'gate_dielectric':['bad']}},{'structure':{'gate_dielectric':{'thickness':{'value':True,'unit':'nm'}}}}]
        for child in cases:
            with self.subTest(child=child):
                self.device(child,child=True);loaded=load_source(path,self.cfg);result=transfer_benchmarks(loaded,self.cfg)
                self.assertEqual(len(loaded['points']),17)
                self.assertTrue(loaded['context']['warnings'])
                self.assertEqual(loaded['geometry']['temperature_C'],25)
                self.assertTrue(np.isfinite(result['frame'].gm_central_A_V.iloc[1:-1]).all())
                self.assertNotIn('mu_apparent_central_cm2_Vs',result['frame'])

    def test_malformed_temperature_holds_only_temperature_dependent_values(self):
        path=self.source()
        for temperature in ([25],{'value':[25]},{'value':True,'unit':'degC'},{'value':25,'unit':['degC']}):
            with self.subTest(temperature=temperature):
                self.device({'run_conditions':{'temperature':temperature}},child=True)
                loaded=load_source(path,self.cfg);result=transfer_benchmarks(loaded,self.cfg)
                self.assertIsNone(loaded['geometry']['thermal_voltage_V'])
                self.assertEqual(loaded['geometry']['L_um'],1.5)
                self.assertIn('mu_apparent_central_cm2_Vs',result['frame'])
                self.assertEqual(len(loaded['points']),17)

    def test_malformed_strings_are_isolated_and_keep_independent_conditions(self):
        self.device({'device_name':{'value':['bad']},'run_conditions':{'IdVg':{'file':'data.csv','measurement_date':{'value':{}},'illumination':{'value':['dark']},'sweep_delay_user_s':[.1]},'units':{'voltage':['V'],'current':'A','verification':'user_confirmed'}},'reference_inputs':{'mobility_cm2_Vs':{'value':[2]}}},child=True)
        loaded=load_source(self.source(),self.cfg)
        self.assertEqual(len(loaded['points']),17)
        self.assertTrue(loaded['context']['warnings'])
        self.assertEqual(loaded['geometry']['temperature_C'],25)
        self.assertIsNone(loaded['geometry']['L_um'])
        self.assertIsNone(loaded['conditions']['measurement_date'].get('value'))
        self.assertFalse(measurement_config(loaded['context'],self.cfg).data['measurement_profile']['confirmed'])
        self.assertTrue(transfer_benchmarks(loaded,self.cfg)['metrics'][0]['gm_peaks'])

    def test_malformed_selection_still_creates_raw_graphs_in_real_report(self):
        self.device({'active_electrode_pair':['p']},child=True)
        path=self.source();metadata=self.cfg.paths['inbox']/'child/device.md';before=digest(metadata)
        report=generate(self.cfg,[path.relative_to(self.cfg.paths['inbox']).as_posix()])
        folder=Path(report['output'])
        self.assertTrue((folder/'images/01-IdVg-linear-1.png').is_file())
        self.assertTrue((folder/'images/01-gm-Ig-1.png').is_file())
        self.assertIn('active_electrode_pair',Path(report['markdown']).read_text(encoding='utf-8'))
        self.assertEqual(before,digest(metadata))

    def test_geometry_defends_unvalidated_types_and_numeric_overflow(self):
        for selection in (['p'],{'value':['p']},True):
            context={'data':{'active_electrode_pair':selection,'electrode_pairs':['p'],'structure':['bad'],'run_conditions':['bad']},'warnings':[]}
            result=geometry(context,self.cfg)
            self.assertIsNone(result['L_um']);self.assertIsNone(result['thermal_voltage_V'])
            self.assertTrue(context['warnings'])
        self.assertIsNone(value({'value':10**10000,'unit':'um'},'um'))

    def test_schema_version_boolean_is_not_version_one(self):
        path=self.device({'schema_version':True})
        with self.assertRaises(ValueError):read_device(path)


if __name__=='__main__':unittest.main()
