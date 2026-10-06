import copy,json,tempfile,unittest
from pathlib import Path
import numpy as np
import pandas as pd
from research_automation.config import Config,DEFAULT
from research_automation.comparison import compare_reasons,rr_knee,photo_difference,REQUIRED
from research_automation.rectifier_models import predict_current,fit_effective_models


class ComparisonModelTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();p=Path(self.temp.name)/'c.json';p.write_text(json.dumps(copy.deepcopy(DEFAULT)), encoding="utf-8");self.cfg=Config(p)
    def tearDown(self):
        from test_cleanup import close_test_logs
        close_test_logs(self.temp.name)
        self.temp.cleanup()
    def context(self,lighting='dark'):
        fields={k:{'status':'confirmed','value':'same'} for k in REQUIRED}
        fields['illumination']={'status':'confirmed','value':lighting}
        return {'research_context':{'fields':fields,'illumination':lighting}}
    def group(self,limit=40):
        return {'axis':'vg','direction':'forward','gate_block_id':'block-001','branch_index':1,'conditions':{'vd':2.},'units_review_required':False,
            'original_sweep':{'start_v':-limit,'end_v':limit,'min_v':-limit,'max_v':limit,'steps_v':[.5]}}
    def test_original_sweep_crop_cannot_make_twenty_and_forty_comparable(self):
        reasons=compare_reasons(self.context(),self.group(20),self.context(),self.group(40))
        self.assertTrue(any('원래 sweep' in r for r in reasons))
        missing=self.context();missing['research_context']['fields']['history']['status']='missing'
        self.assertTrue(compare_reasons(missing,self.group(),missing,self.group()))
        first,second=self.context(),self.context()
        first['research_context']['fixed_conditions_v']={'vg':[-20.,0.,20.]}
        second['research_context']['fixed_conditions_v']={'vg':[-40.,0.,40.]}
        ga,gb=self.group(2),self.group(2)
        ga['axis']=gb['axis']='vd';ga['conditions']=gb['conditions']={'vg':0.}
        self.assertTrue(any('gate step' in r for r in compare_reasons(first,ga,second,gb)))
        ga['original_sweep']['programmed_start_v']=-40.
        gb['original_sweep']['programmed_start_v']=-20.
        self.assertTrue(any('원래 설정' in r for r in compare_reasons(first,ga,second,gb)))
    def test_knee_and_no_forced_knee_with_sensitive_axis_definition(self):
        x=np.arange(-20.,21.,2.);y=np.where(x<0,1.-.02*x,1.-.002*x)
        k=rr_knee(x,y,self.cfg)
        self.assertEqual(k['metric_status'],'candidate');self.assertEqual(k['knee_vg_v'],0.)
        self.assertEqual(k['rr_axis'],'linear')
        self.assertEqual(rr_knee(x,1.-.01*x,self.cfg)['metric_status'],'no_knee')
        self.assertEqual(rr_knee([0,0,1,2],[1,2,3,4],self.cfg)['metric_status'],'ambiguous')
    def test_signed_and_magnitude_light_difference_power_missing(self):
        dark,light=self.context(),self.context('light')
        gd,gl=self.group(),self.group()
        f=pd.DataFrame({'vg':[-1.,0.,1.],'id':[-3.,-2.,1.],'source_row':[1,2,3]})
        l=f.copy();l['id']=[-2.,-1.,2.]
        result=photo_difference(dark,gd,f,light,gl,l)
        self.assertEqual(result['points'][0]['signed_delta_id_a'],1.)
        self.assertEqual(result['points'][0]['delta_abs_id_a'],-1.)
        self.assertIsNone(result['points'][0]['responsivity_a_per_w'])
    def test_known_shared_coefficient_models_units_and_constraints(self):
        self.cfg.data['science']['rectifier_models_enabled']=True
        u=np.linspace(.6,2.,36);j0=2e-10;a=.25;rp=1.5e6;rn=3e6
        vp=predict_current(u,rp,a,j0);vn=predict_current(u,rn,a,j0)
        frame=pd.DataFrame({'vd':np.r_[-u[::-1],u],'id':np.r_[-vn[::-1],vp],
            'source_row':np.arange(72)+2,'metric_eligible':True})
        result=fit_effective_models(frame,self.cfg)
        models={m['model']:m for m in result['models']}
        for name,count in [('independent',6),('shared_a_j0',4),('shared_a',5)]:
            m=models[name];self.assertEqual(m['k'],count);self.assertEqual(m['parameter_units']['a_v'],'V')
            self.assertEqual(m['source_rows'],models['exponential']['source_rows'])
            self.assertIsNone(m['parameter_confidence_interval'])
        fit=models['shared_a_j0'];p,n=fit['parameters']['positive'],fit['parameters']['negative']
        self.assertEqual(p['a_v'],n['a_v']);self.assertEqual(p['j0_a'],n['j0_a'])
        self.assertAlmostEqual(p['a_v'],a,delta=.001)
        self.assertAlmostEqual(p['j0_a']/j0,1.,delta=.01)
        self.assertAlmostEqual(p['rs_ohm']/rp,1.,delta=.01)
        self.assertLess(fit['heldout_rmse_a'],1e-11)
