import copy
import json
from pathlib import Path
import tempfile
import unittest
from research_automation.metric_store import (EvidenceStore,canonical,pack_table,unpack_table,
    read_metric_json,write_metric_json,reference,EVIDENCE_FILE,compact_legacy_copies)
from research_automation.metric_contract import validate_records
from research_automation.config import DEFAULT
from research_automation.fet_parameters import export_fet
from research_automation.research_report import export_report
from research_automation.util import write_json
from unittest.mock import patch
from test_note_presentation import fixture


class MetricStoreTests(unittest.TestCase):
    def test_complete_fet_report_and_csv_refs_are_lossless_and_shared(self):
        import pandas as pd
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp);s,data=fixture(held=False)
            cfg=type('Cfg',(),{'paths':{'vault':d},'data':copy.deepcopy(DEFAULT)})()
            fet=export_fet(data,s,d,cfg);report=export_report(data,s,d,cfg,fet)
            store=EvidenceStore(d)
            for name,expected in [('fet_parameters.json',fet),('research_report.json',report)]:
                self.assertEqual(canonical(read_metric_json(d/name,store)),canonical(expected))
                stored=json.loads((d/name).read_text(encoding='utf-8'))
                self.assertEqual(stored['schema_version'],3);self.assertEqual(stored['metric_contract_version'],3)
                self.assertEqual(stored['_metric_storage']['evidence_file'],EVIDENCE_FILE)
            validate_records(read_metric_json(d/'research_report.json',store)['metric_records'])
            unique={canonical(r) for r in report['metric_records']}
            self.assertEqual(store.verify()['objects_by_table']['metrics'],len(unique))
            baseline=sum(len((json.dumps(v,ensure_ascii=False,allow_nan=False,indent=2)+'\n').encode('utf-8')) for v in (fet,report))
            compact=sum((d/n).stat().st_size for n in ('fet_parameters.json','research_report.json',EVIDENCE_FILE))
            self.assertLess(compact,baseline*.2)
            for name,records in [('fet_parameters.csv',fet['points']),('fet_summary.csv',fet['extractions']),('research_metrics.csv',report['metric_records'])]:
                frame=pd.read_csv(d/name,keep_default_na=False)
                self.assertEqual(len(frame),len(records))
                for (_,row),expected in zip(frame.iterrows(),records):
                    actual=store.resolve({'$ref':row['metric_ref']})
                    self.assertEqual(canonical(actual),canonical(expected))
                    for field in ('extraction_method','bias_condition','provenance'):
                        self.assertEqual(canonical(store.resolve(json.loads(row[field]))),canonical(expected[field]))

    def test_column_dictionary_preserves_numbers_null_order_types_and_key_presence(self):
        values={str(k):{'null':None,'signed':-1.5 if k%2 else 0.0,'flag':bool(k%2),
                        'integer':0,'text':'한글 / whitespace','points':[3,2,1],'empty':''} for k in range(80)}
        values['missing']={'integer':0};values['list']=[{'x':1},None,True]
        packed=pack_table(values)
        self.assertTrue(any(c['encoding']=='dictionary' for b in packed['batches'] for c in b['columns']))
        self.assertEqual(canonical(unpack_table(packed)),canonical(values))
        self.assertNotIn('null',unpack_table(packed)['missing'])
        self.assertEqual(unpack_table(packed)['0']['points'],[3,2,1])

    def test_legacy_reports_and_logical_versions_stay_compatible(self):
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp)
            for original in [{'schema_version':1,'value':None},{'schema_version':2,'metric_contract_version':2,'signed':-1.0},{'raw':[0,0.0,False,None,'0']}]:
                path=d/'report.json';write_json(path,original)
                self.assertEqual(canonical(read_metric_json(path)),canonical(original))
                write_metric_json(path,original)
                self.assertEqual(canonical(read_metric_json(path)),canonical(original))

    def test_append_keeps_prior_document_refs_and_content_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp);old={'schema_version':2,'settings':{'source':'synthetic original '*20,'value':1},'array':[1,-2,None]}
            write_metric_json(d/'prior.json',old)
            prior_bytes=(d/'prior.json').read_bytes();before=EvidenceStore(d).tables
            new=copy.deepcopy(old);new['settings']['value']=2
            write_metric_json(d/'new.json',new);after=EvidenceStore(d).tables
            self.assertEqual((d/'prior.json').read_bytes(),prior_bytes)
            for kind,table in before.items():
                for key,value in table.items():self.assertEqual(canonical(after[kind][key]),canonical(value))
            self.assertEqual(canonical(read_metric_json(d/'prior.json')),canonical(old))
            self.assertEqual(canonical(read_metric_json(d/'new.json')),canonical(new))

    def test_missing_evidence_and_dangling_refs_never_invent_values(self):
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp);write_metric_json(d/'report.json',{'schema_version':2,'settings':{'source':'synthetic '*20}})
            (d/EVIDENCE_FILE).unlink()
            with self.assertRaises(FileNotFoundError):read_metric_json(d/'report.json')
            with self.assertRaisesRegex(ValueError,'Missing evidence'):EvidenceStore(d).resolve(reference('metrics','0'*20))

    def test_publish_failure_keeps_prior_report_and_refs_consistent(self):
        from research_automation.metric_store import atomic_text
        for fail_evidence in (True,False):
            with tempfile.TemporaryDirectory() as temp:
                d=Path(temp);path=d/'report.json'
                prior={'schema_version':2,'settings':{'source':'synthetic prior '*20,'value':1}}
                write_metric_json(path,prior);before=path.read_bytes();evidence_before=(d/EVIDENCE_FILE).read_bytes()
                changed=copy.deepcopy(prior);changed['settings']['value']=2
                def publish(target,text):
                    if Path(target)==(d/EVIDENCE_FILE if fail_evidence else path):raise OSError('synthetic publication failure')
                    return atomic_text(target,text)
                with patch('research_automation.metric_store.atomic_text',side_effect=publish):
                    with self.assertRaises(OSError):write_metric_json(path,changed)
                self.assertEqual(path.read_bytes(),before)
                self.assertEqual(canonical(read_metric_json(path)),canonical(prior))
                if fail_evidence:self.assertEqual((d/EVIDENCE_FILE).read_bytes(),evidence_before)

    def test_corrupt_table_id_is_detected(self):
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp);write_metric_json(d/'report.json',{'settings':{'value':1,'source':'synthetic '*20}})
            path=d/EVIDENCE_FILE;data=json.loads(path.read_text(encoding='utf-8'))
            batch=data['tables']['methods']['batches'][0];batch['template']['value']=2
            path.write_text(json.dumps(data),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'content ID'):read_metric_json(d/'report.json')

    def test_unsafe_override_and_cyclic_refs_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            store=EvidenceStore(Path(temp))
            for ref in ['../private.json#/tables/metrics/'+'0'*20,'https://example.org/value','#/tables/metrics/'+'0'*20,42]:
                with self.assertRaises(ValueError):store.resolve({'$ref':ref})
            with self.assertRaises(ValueError):store.resolve({**reference('metrics','0'*20),'value':0})
            store.tables={'metrics':{'0'*20:reference('metrics','1'*20),'1'*20:reference('metrics','0'*20)}}
            with self.assertRaisesRegex(ValueError,'Cyclic'):store.resolve(reference('metrics','0'*20))

    def test_column_table_rejects_duplicate_rows_and_bad_palette_indices(self):
        table={'values':{},'batches':[{'template':{'x':1},'columns':[],'rows':[['a'],['a']]}]}
        with self.assertRaises(ValueError):unpack_table(table)
        table={'values':{},'batches':[{'template':{},'columns':[{'name':'x','encoding':'dictionary','values':[1]}],'rows':[['a',2]]}]}
        with self.assertRaises(ValueError):unpack_table(table)

    def test_historical_json_copy_preserves_every_legacy_field_and_v3_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp);legacy={'schema_version':1,'points':[{'group_id':'g1','parameter':'gm','value':-1e-9,
                        'unit':'A/V','metric_status':'candidate','source_row':2,'user_note':'사용자 원문','optional':None}]}
            path=d/'prior_fet_parameters.json';write_json(path,legacy)
            changes=compact_legacy_copies(d,{'fet_parameters.json':path.name})
            self.assertTrue(changes['fet_parameters.json']['logical_payload_equal'])
            self.assertEqual(canonical(read_metric_json(path)),canonical(legacy))
            before=path.read_bytes();self.assertEqual(compact_legacy_copies(d,{'fet_parameters.json':path.name}),{})
            self.assertEqual(path.read_bytes(),before)

    def test_historical_csv_copy_keeps_all_columns_raw_cells_and_resolvable_support(self):
        import csv
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp);path=d/'prior_fet_parameters.csv'
            support={'source_file':'한글 경로/data.xls','source_cells':[{'id':'B2','x':'A2'}]*8,'signed_current':-1e-9}
            original=[{'parameter':'gm','value':'-1.000000000000001e-09','provenance':json.dumps(support),'blank':'','literal':'  사용자 원문  '},
                      {'parameter':'gm','value':'','provenance':'not-json','blank':'','literal':'0'}]
            with path.open('w',encoding='utf-8-sig',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=list(original[0]));writer.writeheader();writer.writerows(original)
            compact_legacy_copies(d,{'fet_parameters.csv':path.name});store=EvidenceStore(d)
            with path.open(encoding='utf-8-sig',newline='') as stream:rows=list(csv.DictReader(stream))
            self.assertEqual(set(rows[0]),set(original[0])|{'evidence_document'})
            for expected,actual in zip(original,rows):
                for key in expected:
                    if key=='provenance' and expected[key]!='not-json':self.assertEqual(canonical(store.resolve(json.loads(actual[key]))),canonical(support))
                    else:self.assertEqual(actual[key],expected[key])
            before=path.read_bytes();compact_legacy_copies(d,{'fet_parameters.csv':path.name});self.assertEqual(path.read_bytes(),before)


if __name__=='__main__':unittest.main()
