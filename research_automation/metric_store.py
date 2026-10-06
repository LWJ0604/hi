"""Lossless shared evidence storage, with an adapter for expanded v2 records.

No scientific field is discarded. Repeated objects have content-addressed IDs;
table columns store a common value once when dictionary encoding is smaller.
References are strictly local to metric_evidence.json in the same directory.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
from .util import atomic_text,write_json,digest

EVIDENCE_FILE='metric_evidence.json'
METRIC_FIELDS={'value','unit','availability','reason','extraction_method','bias_condition','provenance'}
SHARED={
    'input_provenance':'sources','sheet_column_mappings':'trace_maps','sheet_column_mapping':'trace_maps',
    'extraction_method':'methods','settings':'methods','derivative_settings':'methods','assumptions':'methods',
    'bias_condition':'biases','metadata':'conditions','original_sweep':'traces','comparison_reasons':'conditions',
    'provenance':'provenance','unit_conversion':'conversions','configured_scales':'conversions',
    'transformations':'transformations','width_source':'geometry','dependencies':'conditions',
    'source_rows':'supports','source_cells':'supports','raw_points':'supports','derivative_support':'supports',
    'support_points':'supports','source_records':'supports','source_positive':'supports','source_negative':'supports',
}
REF=re.compile(r'^metric_evidence\.json#/tables/([a-z_]+)/([0-9a-f]{20})$')


def canonical(value):
    return json.dumps(value,ensure_ascii=False,allow_nan=False,sort_keys=True,separators=(',',':'))


def identifier(kind,value):
    return hashlib.sha256((kind+'\0'+canonical(value)).encode('utf-8')).hexdigest()[:20]


def reference(kind,key):return {'$ref':f'{EVIDENCE_FILE}#/tables/{kind}/{key}'}


def pack_table(values):
    """Columnar batches retain key presence, JSON types and row identities."""
    groups={};other={}
    for key,value in values.items():
        if isinstance(value,dict):groups.setdefault(tuple(sorted(value)),[]).append((key,value))
        else:other[key]=value
    batches=[]
    for keys,items in groups.items():
        template={};columns=[];encoded={}
        for key in keys:
            vals=[value[key] for _,value in items];tokens=[canonical(v) for v in vals]
            if len(set(tokens))==1:template[key]=vals[0];continue
            palette=[];seen={};indices=[]
            for token,value in zip(tokens,vals):
                if token not in seen:seen[token]=len(palette);palette.append(value)
                indices.append(seen[token])
            raw_cost=sum(len(t.encode('utf-8')) for t in tokens)
            dict_cost=len(canonical(palette).encode('utf-8'))+len(canonical(indices).encode('utf-8'))
            if dict_cost<raw_cost:
                columns.append({'name':key,'encoding':'dictionary','values':palette});encoded[key]=indices
            else:columns.append({'name':key,'encoding':'raw'});encoded[key]=vals
        batches.append({'template':template,'columns':columns,
                        'rows':[[identity,*[encoded[c['name']][i] for c in columns]] for i,(identity,_) in enumerate(items)]})
    return {'batches':batches,'values':other}


def unpack_table(table):
    values=dict(table.get('values',{}))
    for batch in table.get('batches',[]):
        columns=batch['columns'];template=batch['template']
        names=[c['name'] for c in columns]
        if len(set(names))!=len(names) or set(names)&template.keys():raise ValueError('Duplicate evidence table columns')
        for row in batch['rows']:
            if len(row)!=len(columns)+1 or row[0] in values:raise ValueError('Invalid or duplicate evidence table row')
            value=dict(template)
            for column,cell in zip(columns,row[1:]):
                if column['encoding']=='dictionary':
                    if not isinstance(cell,int) or isinstance(cell,bool) or not 0<=cell<len(column['values']):raise ValueError('Invalid evidence dictionary index')
                    cell=column['values'][cell]
                elif column['encoding']!='raw':raise ValueError('Unknown evidence column encoding')
                value[column['name']]=cell
            values[row[0]]=value
    return values


class EvidenceStore:
    def __init__(self,directory):
        self.directory=Path(directory);self.path=self.directory/EVIDENCE_FILE;self.tables={};self.memo={}
        if self.path.is_file():
            data=json.loads(self.path.read_text(encoding='utf-8-sig'))
            if data.get('storage_version')!=1 or data.get('encoding')!='columnar-tables-v1':raise ValueError('Unsupported evidence storage version')
            self.tables={name:unpack_table(table) for name,table in data['tables'].items()}
            for kind,values in self.tables.items():
                for key,value in values.items():
                    if key!=identifier(kind,value):raise ValueError('Evidence content ID does not match: '+kind+'/'+key)

    def intern(self,kind,value):
        key=identifier(kind,value);values=self.tables.setdefault(kind,{})
        if key in values and canonical(values[key])!=canonical(value):raise ValueError('Evidence content ID collision')
        values.setdefault(key,value)
        return reference(kind,key)

    def encode(self,value,key=None,_memo=None):
        if not isinstance(value,(dict,list,tuple)):return value
        memo={} if _memo is None else _memo
        token=(id(value),key)
        if token in memo:
            if memo[token] is None:raise ValueError('Cyclic input JSON')
            return memo[token][1]
        memo[token]=None
        if isinstance(value,dict):
            encoded={name:self.encode(item,name,memo) for name,item in value.items()}
            if METRIC_FIELDS<=value.keys():encoded=self.intern('metrics',encoded)
            elif {'group_id','parameter','value'}<=value.keys():encoded=self.intern('legacy_metrics',encoded)
        elif isinstance(value,(list,tuple)):
            encoded=[self.encode(item,'point' if key in ('source_cells','raw_points','support_points','derivative_support') else None,memo) for item in value]
        kind='points' if key=='point' else SHARED.get(key)
        if kind and len(canonical(encoded).encode('utf-8'))>=80:encoded=self.intern(kind,encoded)
        memo[token]=(value,encoded)
        return encoded

    def encoded_record(self,ref):
        token=ref.get('$ref','')
        match=REF.fullmatch(token) if isinstance(token,str) else None
        if not match:raise ValueError('Invalid local evidence reference')
        kind,key=match.groups()
        try:return self.tables[kind][key]
        except KeyError:raise ValueError('Missing evidence reference: '+ref['$ref']) from None

    def resolve(self,value,active=None):
        active=set() if active is None else active
        if isinstance(value,dict) and '$ref' in value:
            if set(value)!={'$ref'}:raise ValueError('Evidence reference cannot override fields')
            match=REF.fullmatch(value['$ref']) if isinstance(value['$ref'],str) else None
            if not match:raise ValueError('Unsafe or invalid evidence reference: '+str(value['$ref']))
            token=match.groups()
            if token in active:raise ValueError('Cyclic evidence reference')
            if token not in self.memo:
                active.add(token)
                try:self.memo[token]=self.resolve(self.encoded_record(value),active)
                finally:active.remove(token)
            return self.memo[token]
        if isinstance(value,dict):return {key:self.resolve(item,active) for key,item in value.items()}
        if isinstance(value,list):return [self.resolve(item,active) for item in value]
        return value

    def verify(self,document=None):
        for kind,values in self.tables.items():
            for key,value in values.items():
                if key!=identifier(kind,value):raise ValueError('Evidence content ID does not match: '+kind+'/'+key)
                self.resolve(reference(kind,key))
        if document is not None:self.resolve(document)
        return {'unique_objects':sum(map(len,self.tables.values())),
                'objects_by_table':{name:len(values) for name,values in self.tables.items()},
                'all_references_resolve':True,'content_ids_verified':True}

    def write(self):
        data={'storage_version':1,'encoding':'columnar-tables-v1',
              'tables':{name:pack_table(values) for name,values in self.tables.items()}}
        atomic_text(self.path,json.dumps(data,ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n')


def write_metric_json(path,value):
    """Publish shared evidence before the referencing document, append-only IDs."""
    path=Path(path);store=EvidenceStore(path.parent);encoded=store.encode(value)
    storage={'version':1,'evidence_file':EVIDENCE_FILE,'encoding':'columnar-tables-v1',
             'logical_schema_version':value.get('schema_version'),
             'logical_metric_contract_version':value.get('metric_contract_version')}
    document={**encoded,'schema_version':3,'metric_contract_version':3,'_metric_storage':storage}
    store.verify(document);store.write()
    atomic_text(path,json.dumps(document,ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n')
    return document,store


def read_metric_json(path,store=None):
    """Legacy v1/v2 pass through; v3 resolves to the exact expanded v2 shape."""
    path=Path(path);document=json.loads(path.read_text(encoding='utf-8-sig'))
    storage=document.get('_metric_storage')
    if storage is None:return document
    if storage.get('version')!=1 or storage.get('evidence_file')!=EVIDENCE_FILE or storage.get('encoding')!='columnar-tables-v1':raise ValueError('Unsupported metric reference format')
    store=store or EvidenceStore(path.parent)
    if not store.path.is_file():raise FileNotFoundError('같은 폴더의 metric_evidence.json이 필요합니다: '+str(store.path))
    result=store.resolve(document);result.pop('_metric_storage')
    for key,storage_key in [('schema_version','logical_schema_version'),('metric_contract_version','logical_metric_contract_version')]:
        if storage[storage_key] is None:result.pop(key,None)
        else:result[key]=storage[storage_key]
    return result


def compact_legacy_copies(directory,preserved):
    """Normalize only new historical copies; original files are never modified.

    Already-referenced v3 copies remain byte-identical. IDs are append-only so
    their old JSON/CSV references still resolve in the shared graph.
    """
    directory=Path(directory);changes={}
    for original,name in preserved.items():
        if not name.startswith('prior_'):continue
        path=directory/name
        if path.suffix=='.json' and (original.startswith('fet_') or original=='research_report.json'):
            value=json.loads(path.read_text(encoding='utf-8-sig'))
            if '_metric_storage' in value:continue
            before=digest(path);size=path.stat().st_size
            write_metric_json(path,value)
            if canonical(read_metric_json(path))!=canonical(value):raise ValueError('Historical JSON normalization is not lossless')
            changes[original]={'copy':name,'original_copy_sha256':before,'normalized_copy_sha256':digest(path),
                               'before_bytes':size,'after_bytes':path.stat().st_size,'logical_payload_equal':True}
        elif path.suffix=='.csv' and (original.startswith('fet_') or original=='research_metrics.csv'):
            with path.open(encoding='utf-8-sig',newline='') as source:
                reader=csv.DictReader(source);fields=list(reader.fieldnames or []);rows=list(reader)
            if 'evidence_document' in fields:continue
            store=EvidenceStore(directory);converted=[];changed=False
            for row in rows:
                record=dict(row)
                for field in set(fields)&SHARED.keys():
                    try:value=json.loads(row[field])
                    except (ValueError,TypeError):continue
                    if not isinstance(value,(dict,list)):continue
                    encoded=store.encode(value,field)
                    if canonical(encoded)!=canonical(value):
                        if canonical(store.resolve(encoded))!=canonical(value):raise ValueError('Historical CSV normalization is not lossless')
                        record[field]=canonical(encoded);changed=True
                converted.append(record)
            if not changed:continue
            before=digest(path);size=path.stat().st_size;store.verify();store.write()
            import io
            buffer=io.StringIO(newline='');writer=csv.DictWriter(buffer,fieldnames=fields+['evidence_document'],lineterminator='\n')
            writer.writeheader();writer.writerows({**row,'evidence_document':EVIDENCE_FILE} for row in converted)
            atomic_text(path,'\ufeff'+buffer.getvalue())
            changes[original]={'copy':name,'original_copy_sha256':before,'normalized_copy_sha256':digest(path),
                               'before_bytes':size,'after_bytes':path.stat().st_size,'logical_payload_equal':True,
                               'rows':len(rows),'original_columns':fields}
    return changes


def main():
    parser=argparse.ArgumentParser(description='Validate shared metric evidence or expand a local report for a v2 consumer.')
    parser.add_argument('report',type=Path);parser.add_argument('--expand',type=Path)
    args=parser.parse_args();store=EvidenceStore(args.report.parent)
    result=read_metric_json(args.report,store)
    if args.expand:
        if args.expand.exists():raise FileExistsError('기존 파일을 덮어쓰지 않습니다: '+str(args.expand))
        write_json(args.expand,result)
    print(json.dumps(store.verify(),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
