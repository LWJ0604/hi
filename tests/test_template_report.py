"""Synthetic bridge tests, never confirmations or example data for real reports."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image
from research_automation.research_panels import verify_png
from research_automation.template_report import (
    TemplateBundle, adapt_records, derive_display_flags, load_native_records, local_file, native_result)
from research_automation.metric_store import write_metric_json
from test_note_presentation import fixture as measurement_fixture


def native(value=-2e-9, availability='candidate'):
    return {'parameter': 'gm', 'group_id': 'g0001', 'value': value, 'unit': 'A/V',
            'availability': availability, 'reason': 'synthetic derivative; model not certified',
            'extraction_method': {'formula': 'dId/dVg', 'assumptions': []},
            'bias_condition': {'evaluation_voltage_v': 1, 'fixed_voltages_v': {'vd': -2},
                               'direction': 'forward', 'gate_block_id': 'block-1'},
            'provenance': {'source_file': 'synthetic.csv', 'source_sheet': 'synthetic',
                           'source_rows': [2, 3, 4], 'source_cells': ['A2:B4'],
                           'group_id': 'g0001', 'trace_id': 'synthetic-1', 'transformations': [],
                           'evaluation_window_v': [0, 2],
                           'unit_conversion': {'units_confirmed': True, 'SI_assumption': False}}}


def metric(record=None):
    return native_result(record or native(), result_id='result-gm-evaluated', label='Signed gm',
                         source_id='source-1', run_id='run-1', figure_ids=['gm'],
                         lineage_path='points.csv', evidence_reference='metrics.json / logical record 0')


class TemplateBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'synthetic.csv').write_text('x,id\n0,-2e-9\n', encoding='utf-8')
        (self.root/'points.csv').write_text('x,id\n0,-2e-9\n', encoding='utf-8')
        Image.new('RGB', (32, 32), 'white').save(self.root/'gm.png')
        source_hash = hashlib.sha256((self.root/'synthetic.csv').read_bytes()).hexdigest()
        self.proofs = {'gm': verify_png(self.root/'gm.png')}
        self.context = {
            'summary': {'unresolved_statement': None}, 'floors': {}, 'comparisons': {},
            'sources': {'source-1': {'raw_path': 'synthetic.csv', 'sha256': source_hash,
                                     'link_validated': True, 'confirmed_measurement_date': None}},
            'runs': {'run-1': {'source_refs': ['source-1']}},
            'figures': {'gm': {'state': 'ready', 'render_verified': True, 'image_path': 'gm.png',
                               'plot_data_path': 'points.csv', 'source_refs': ['source-1'],
                               'result_refs': ['result-gm-evaluated']}},
            'modules': {'gm': {'status': 'candidate', 'display_approved': True,
                                'comparison_refs': [], 'results': {'evaluated': metric()}}}}

    def checked(self):
        return derive_display_flags(self.context, self.root, self.proofs)

    def test_native_value_sign_status_and_input_are_preserved(self):
        source = native()
        before = copy.deepcopy(source)
        mapped = metric(source)
        self.assertEqual(mapped['value'], -2e-9)
        self.assertEqual(mapped['status'], 'candidate')
        self.assertFalse(mapped['validation']['model_validated'])
        self.assertEqual(source, before)
        self.assertEqual(mapped['extraction']['settings']['evidence_reference'], 'metrics.json / logical record 0')
        self.assertNotIn('raw_points', mapped['extraction']['settings'])

    def test_unavailable_si_candidate_is_not_promoted(self):
        source = native(None, 'held')
        source['candidate_value_assuming_si'] = -2e-9
        source['provenance']['unit_conversion']['units_confirmed'] = False
        mapped = metric(source)
        self.assertIsNone(mapped['value'])
        self.assertEqual(mapped['status'], 'on_hold')
        self.assertFalse(mapped['display_approved'])

    def test_zero_is_not_missing_and_no_epsilon_is_created(self):
        mapped = metric(native(0))
        self.assertEqual(mapped['value'], 0)
        self.assertEqual(mapped['value_kind'], 'exact')

    def test_schema3_reader_retains_exact_values_provenance_and_disk_bytes(self):
        records = [native(), native(None, 'held')]
        path = self.root/'fet_parameters.json'
        write_metric_json(path, {'schema_version': 2, 'metric_contract_version': 2, 'points': records})
        original = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        loaded = load_native_records(path, 'points')
        self.assertEqual(loaded, records)
        self.assertEqual(metric(loaded[0])['value'], records[0]['value'])
        self.assertEqual({p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}, original)

    def test_flags_are_derived_without_mutating_inputs(self):
        before = copy.deepcopy(self.context)
        checked = self.checked()
        self.assertTrue(checked['modules']['gm']['display_approved'])
        self.assertEqual(checked['modules']['gm']['results']['evaluated']['status'], 'candidate')
        self.assertEqual(self.context, before)

    def test_source_change_and_missing_proof_override_true_flags(self):
        (self.root/'synthetic.csv').write_text('changed', encoding='utf-8')
        self.assertFalse(self.checked()['modules']['gm']['display_approved'])
        checked = derive_display_flags(self.context, self.root, {})
        self.assertFalse(checked['figures']['gm']['render_verified'])

    def test_unrelated_ready_figure_does_not_approve_result(self):
        self.context['figures']['gm']['result_refs'] = ['another-result']
        self.assertFalse(self.checked()['modules']['gm']['display_approved'])

    def test_broken_png_is_render_failure_and_raw_view_guidance_remains(self):
        (self.root/'gm.png').write_bytes(b'not an image')
        checked = self.checked()
        self.assertEqual(checked['figures']['gm']['state'], 'failed')
        self.assertIn('원본 곡선', checked['summary']['unresolved_statement'])

    def test_comparison_scope_and_unknown_conditions_are_not_approved(self):
        result = self.context['modules']['gm']['results']['evaluated']
        result['evaluation']['comparison_refs'] = ['pair-1']
        self.context['comparisons']['pair-1'] = {
            'status': 'approved_for_scope', 'approved_module_ids': ['gm'], 'run_refs': ['run-1'],
            'original_domains': ['original ±20 V'],
            'checks': [{'condition': 'history', 'reference': None, 'test': None, 'verdict': 'matched'}]}
        self.assertFalse(self.checked()['modules']['gm']['display_approved'])
        check = self.context['comparisons']['pair-1']
        check['checks'] = [{'condition': 'range', 'reference': '±20 V', 'test': '±40 V', 'verdict': 'matched'}]
        self.assertFalse(self.checked()['modules']['gm']['display_approved'])
        check['checks'][0]['test'] = '±20 V'
        check['approved_module_ids'] = ['ss']
        self.assertFalse(self.checked()['modules']['gm']['display_approved'])

    def test_unverified_floor_cannot_approve_bound(self):
        result = self.context['modules']['gm']['results']['evaluated']
        result.update(value_kind='lower_bound', relation='≥', floor_refs=['floor-1'], bound_reason='synthetic bound')
        self.context['floors']['floor-1'] = {'value_A': 1e-12, 'verified': False, 'method': 'synthetic',
                                            'source_refs': ['source-1'], 'run_refs': ['run-1'], 'bias_domain': 'synthetic'}
        self.assertFalse(self.checked()['modules']['gm']['display_approved'])

    def test_confirmed_checks_and_source_date_evidence_are_required(self):
        result = self.context['modules']['gm']['results']['evaluated']
        result['status'] = 'confirmed'
        self.assertFalse(self.checked()['modules']['gm']['display_approved'])
        self.context['sources']['source-1']['confirmed_measurement_date'] = '2026-09-23'
        with self.assertRaisesRegex(ValueError, '확인 범위'):
            self.checked()

    def test_local_links_reject_network_and_escape_paths(self):
        for relative in ('https://example.test/data', '../outside.csv', r'C:\private\data.csv', ''):
            self.assertIsNone(local_file(self.root, relative))
        self.assertEqual(local_file(self.root, 'points.csv'), (self.root/'points.csv').resolve())

    def test_actual_template_bundle_is_required_and_external_schema_is_rejected(self):
        with self.assertRaisesRegex(FileNotFoundError, '실제 템플릿'):
            TemplateBundle(self.root)
        # Tiny independently authored test contract, not the user's Library files.
        (self.root/'report.md.j2').write_text('{{ absent }}', encoding='utf-8')
        (self.root/'empty_report.json').write_text('{}', encoding='utf-8')
        (self.root/'report.schema.json').write_text('{"$ref":"https://example.test/schema"}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '내부 참조'):
            TemplateBundle(self.root)

    @unittest.skipUnless(importlib.util.find_spec('jinja2') and importlib.util.find_spec('jsonschema'),
                         'optional report-template dependencies are not installed')
    def test_renderer_uses_recomputed_flags_and_strict_variables(self):
        # Independent minimal renderer fixture. It is not the Library template.
        (self.root/'empty_report.json').write_text('{}', encoding='utf-8')
        (self.root/'report.schema.json').write_text('{"type":"object"}', encoding='utf-8')
        (self.root/'report.md.j2').write_text(
            "{{ modules.gm.results.evaluated.value if modules.gm.results.evaluated.display_approved else 'held' }}",
            encoding='utf-8')
        bundle = TemplateBundle(self.root)
        text, checked = bundle.render(self.context, self.root, self.proofs)
        self.assertEqual(text, '-2e-09')
        self.assertEqual(checked['modules']['gm']['results']['evaluated']['status'], 'candidate')
        text, _ = bundle.render(self.context, self.root, {})
        self.assertEqual(text, 'held')
        bundle.template = '{{ absent }}'
        from jinja2 import UndefinedError
        with self.assertRaises(UndefinedError):
            bundle.render(self.context, self.root, self.proofs)

    def test_adapter_preserves_original_range_date_conflict_and_keeps_headlines_empty(self):
        summary, _ = measurement_fixture(held=False)
        summary.update(source_sha256=self.context['sources']['source-1']['sha256'], source_filename='synthetic.csv')
        summary['research_context'].setdefault('fields', {}).update({
            'measurement_date': {'value': '2026-09-23', 'status': 'inferred', 'source': 'filename'},
            'sweep_delay_s': {'value': None, 'status': 'conflict', 'candidates': [0.1, 0]}})
        empty = {'report': {}, 'device': {}, 'summary': {}, 'sources': {}, 'runs': {},
                 'figures': {}, 'layout': {}, 'next_actions': [], 'availability': {'candidates': [], 'on_hold': []},
                 'modules': {'gm': {'results': {}, 'figure_ids': []}}}
        before = copy.deepcopy(summary)
        mapped = adapt_records(empty, summary, [native()], raw_path='synthetic.csv', lineage_path='points.csv',
                               figures={}, evidence_document='metric_evidence.json')
        self.assertEqual(summary, before)
        self.assertEqual(mapped['summary']['headline_metrics'], [])
        self.assertIsNone(mapped['sources']['source-1']['confirmed_measurement_date'])
        self.assertIn('사용자 확인 전', mapped['report']['measurement_date_display'])
        run = next(iter(mapped['runs'].values()))
        self.assertIsNone(run['protocol']['sweep_delay_s'])
        self.assertEqual(json.loads(run['notes'])['original_sweep'], summary['groups'][0]['original_sweep'])
        self.assertEqual(mapped['device']['analysis_context'], 'unknown')


if __name__ == '__main__':
    unittest.main()
