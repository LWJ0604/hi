import copy,json,tempfile,unittest
from pathlib import Path
import numpy as np
import pandas as pd
from research_automation.config import Config,DEFAULT
from research_automation.scientific_metrics import rectification_series,ratio_with_limit,sample_at,transfer_observables


class ObservableTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();p=Path(self.temp.name)/'c.json';p.write_text(json.dumps(copy.deepcopy(DEFAULT)), encoding="utf-8");self.cfg=Config(p)
    def tearDown(self):
        from test_cleanup import close_test_logs
        close_test_logs(self.temp.name)
        self.temp.cleanup()
    def frame(self,x,y,axis='vg'):
        return pd.DataFrame({axis:x,'id':y,'source_row':np.arange(len(x))+3,'acquisition_order':np.arange(len(x)),
            'segment_id':0,'metric_eligible':True,**({'vd':2.} if axis=='vg' else {'vg':1.})})
    def test_rr_less_than_one_and_evaluation_voltages(self):
        f=self.frame([-2.,-1.,0.,1.,2.],[-10e-9,-5e-9,0.,1e-9,2e-9],'vd')
        values=rectification_series(f,self.cfg)
        self.assertEqual([r['evaluation_abs_vd_v'] for r in values],[.5,1.,1.5,2.])
        self.assertAlmostEqual(values[1]['value'],.2)
        self.assertEqual(values[1]['metric_status'],'candidate')
    def test_bounds_zero_both_undetected_and_unknown_limit(self):
        self.assertEqual(ratio_with_limit(2.,0.,1.)['bound_type'],'lower')
        self.assertEqual(ratio_with_limit(0.,2.,1.)['bound_type'],'upper')
        self.assertIsNone(ratio_with_limit(.1,.2,1.)['value'])
        self.assertIsNone(ratio_with_limit(0.,0.,None)['value'])
        self.assertEqual(ratio_with_limit(0.,2.,None)['value'],0.)
        self.assertEqual(ratio_with_limit(1.,1e-30,None)['metric_status'],'candidate')
    def test_no_interpolation_through_missing_or_compliance_or_repeats(self):
        f=self.frame([-1.,1.],[-1e-9,1e-9],'vd')
        f.loc[1,'acquisition_order']=2
        self.assertIsNone(sample_at(f,'vd',0.)['value'])
        f.loc[1,'acquisition_order']=1;f.loc[1,'metric_eligible']=False
        self.assertIsNone(sample_at(f,'vd',0.)['value'])
        duplicate=self.frame([1.,1.,2.],[1e-9,2e-9,3e-9],'vd')
        self.assertEqual(sample_at(duplicate,'vd',1.)['metric_status'],'ambiguous')
    def test_signed_gm_ascending_descending_and_nonuniform(self):
        for x in [np.linspace(-5,5,101),np.linspace(5,-5,101),np.array([-5.,-4.,-2.1,-1.7,-.5,0.,.2,.4,.6,.9,1.4,2.,4.,5.])]:
            f=self.frame(x,3e-9*x+20e-9);m,a=transfer_observables(f,self.cfg)
            np.testing.assert_allclose(a['gm_a_per_v'],3e-9,rtol=1e-12)
            for key,values in a.items():
                if key.startswith('gm_local_') and key.endswith('_a_per_v'):
                    np.testing.assert_allclose(values[np.isfinite(values)],3e-9,rtol=1e-10)
    def test_endpoint_peak_not_certified_and_missing_geometry_only_holds_mobility(self):
        x=np.linspace(-40,40,161);y=10e-9*(1+np.tanh(x/15));y[-1]+=20e-9
        m,a=transfer_observables(self.frame(x,y),self.cfg)
        self.assertTrue(m['raw_peak_abs']['endpoint'])
        self.assertEqual(m['raw_peak_abs']['reason'],'raw_endpoint_maximum')
        self.assertNotEqual(m['internal_peak_abs']['metric_status'],'valid')
        self.assertIsNone(m['mobility']['value']);self.assertIsNotNone(m['gm_max_a_per_v'])
    def test_configured_vth_ss_and_unknown_geometry_do_not_block_gm(self):
        self.cfg.data['science']['detection_limit_a']=1e-12
        self.cfg.data['science']['detection_limit_evidence']='independent baseline fixture'
        self.cfg.data['science']['vth']={'method':'constant_current','criterion_a':1e-8,'window_v':[-2.,2.]}
        self.cfg.data['science']['ss']={'window_v':[-2.,2.],'current_range_a':[1e-10,1e-6]}
        x=np.linspace(-2,2,81);y=1e-8*10**x
        m,a=transfer_observables(self.frame(x,y),self.cfg)
        self.assertAlmostEqual(m['vth']['value'],0.)
        self.assertAlmostEqual(m['ss']['value'],1.,places=10)
        self.assertEqual(m['ss']['unit'],'V/dec')
        self.assertIsNone(m['mobility']['value']);self.assertIsNotNone(m['gm_max_a_per_v'])
    def test_audited_rr_voltage_example_is_kept_distinct_synthetic_reproduction(self):
        f=self.frame([-2.,-1.,0.,1.,2.],[-1e-8,-1e-8,0.,.8275698e-8,.7618766e-8],'vd')
        series={r['evaluation_abs_vd_v']:r for r in rectification_series(f,self.cfg)}
        self.assertAlmostEqual(series[1.]['value'],.8275698)
        self.assertAlmostEqual(series[2.]['value'],.7618766)
        self.assertNotEqual(series[1.]['value'],series[2.]['value'])
    def test_duplicate_and_zero_vd_normalization(self):
        f=self.frame([-2.,-1.,0.,0.,1.,2.],[-2e-9,-1e-9,0.,2e-9,1e-9,2e-9]);f['vd']=0.
        m,a=transfer_observables(f,self.cfg)
        self.assertTrue(a['gm_duplicate_coordinate'][2]);self.assertTrue(np.isnan(a['gm_a_per_v'][2]))
        self.assertTrue(np.isnan(a['gm_over_vd_a_per_v2']).all())
        self.assertIn('unavailable',m['gm_over_vd_status'])
