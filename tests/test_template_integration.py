"""Actual packaged Jinja/schema tests over explicitly synthetic evidence."""
import copy
import importlib.util
from pathlib import Path
import unittest
import test_template_report as bridge_tests
from test_note_presentation import fixture
from research_automation.template_integration import ROOT
from research_automation.template_report import TemplateBundle, adapt_records


class PackagedTemplateTests(unittest.TestCase):
    setUp=bridge_tests.TemplateBridgeTests.setUp
    def canonical(self, parameter='gm'):
        bundle=TemplateBundle(ROOT)
        summary,_=fixture()
        summary['source_sha256']=self.context['sources']['source-1']['sha256']
        summary['research_context']['fields']['measurement_date']['status']='inferred'
        item=bridge_tests.native();item['parameter']=parameter
        if parameter.startswith('vth_'):item['unit']='V'
        figures=copy.deepcopy(self.context['figures'])
        figures['gm'].update(id='gm',title='Synthetic gm',x_axis='Vg (V)',y_axis='Signed gm (A/V)',
            caption={'observation':'합성 테스트 곡선','conditions':'실제 연구 확인 아님','limitation':'검증용 입력'},
            error_bars=False,validated_repeat_refs=[],supported_parameters=[parameter])
        ctx=adapt_records(bundle.empty,summary,[item],raw_path='synthetic.csv',lineage_path='points.csv',
                          figures=figures,evidence_document='metrics.json')
        return bundle,ctx

    def test_packaged_schema_empty_and_native_candidate(self):
        bundle,ctx=self.canonical();before=copy.deepcopy(ctx)
        text,checked=bundle.render(ctx,self.root,self.proofs,'../자료 폴더')
        self.assertEqual(ctx,before)
        self.assertIn('profile: id_vg',text)
        self.assertIn('../자료 폴더/gm.png',text)
        self.assertIn('-2e-09 A/V',text)
        self.assertIn('모델·구간 검증이 필요한 후보',text)
        self.assertIsNone(checked['sources']['source-1']['confirmed_measurement_date'])
        self.assertNotIn('{{',text)
        self.assertNotIn('## D.',text)

    def test_absent_own_figure_holds_native_number(self):
        bundle,ctx=self.canonical('vth_yfm')
        ctx['figures']['gm']['result_refs']=[]
        text,checked=bundle.render(ctx,self.root,self.proofs)
        self.assertFalse(checked['modules']['y_function']['display_approved'])
        self.assertNotIn('## C.',text)

    def test_anchor_and_preview_links_are_usable(self):
        bundle,ctx=self.canonical('vth_yfm')
        text,checked=bundle.render(ctx,self.root,self.proofs)
        anchor=checked['modules']['y_function']['results']['threshold_candidate']['detail_anchor']
        self.assertNotIn('_',anchor)
        spec=importlib.util.spec_from_file_location('note_html',Path(__file__).resolve().parents[1]/'scripts/preview_note_html.py')
        preview=importlib.util.module_from_spec(spec);spec.loader.exec_module(preview)
        html=preview.render(text)
        self.assertIn('<img src="gm.png"',html)
        self.assertIn('id="'+anchor+'"',html)
        self.assertIn('href="#'+anchor+'"',html)
        self.assertIn('<details>',html)
