"""Uniform metric records; supplemental values never certify missing conditions."""
import copy
import json
import math
from pathlib import Path
import pandas as pd

REQUIRED={'value','unit','availability','reason','extraction_method','bias_condition','provenance'}
UNITS={'vth_yfm':'V','vth_additional':'V','ss_additional':'mV/dec','ss_min':'mV/dec','ss_average':'mV/dec','mobility_linear':'cm²/(V s)',
       'on_off_ratio':'1','contact_resistance':'Ω','hysteresis_voltage':'V','carrier_density':'m⁻²','trap_density':'m⁻²',
       'Rc':'Ω','TLM':'Ω','nS':'m⁻²','mu_con':'cm²/(V s)','DIBL':'V/V','Isat':'A'}


def validate_records(records):
    for r in records:
        if not REQUIRED<=r.keys():raise ValueError('Metric contract fields missing: '+str(REQUIRED-r.keys()))
        if r['availability'] not in {'available','candidate','held','unavailable'}:raise ValueError('Invalid availability')
        if not r['reason'] or not isinstance(r['extraction_method'],dict) or not isinstance(r['bias_condition'],dict) or not isinstance(r['provenance'],dict):raise ValueError('Metric contract structure missing')
        if r['value'] is not None and (not isinstance(r['value'],(int,float)) or not math.isfinite(r['value'])):raise ValueError('Metric value must be finite or null')
        if r['availability'] in {'held','unavailable'} and r['value'] is not None:raise ValueError('Held/unavailable metric must have null value')
        if not {'source_file','source_sheet','source_rows','source_cells','group_id','trace_id','transformations','evaluation_window_v','unit_conversion'}<=r['provenance'].keys():raise ValueError('Provenance structure missing')


def annotator(summary,cfg,curves,directory):
    groups={g['group_id']:g for g in summary.get('groups',[])}
    # Wide sheets contain distinct trace columns on the same physical sheet.
    # Key by logical sheet/trace so later traces cannot overwrite earlier mappings.
    sheets={s.get('name') or s.get('source_sheet'):s for s in summary.get('sheets',[])}
    mappings={name:s.get('column_mapping',{}) for name,s in sheets.items()}
    points={}
    for _,row in curves.iterrows():
        if pd.notna(row.get('source_row')):points[(row['group_id'],int(row['source_row']))]=row
    raw={};path=Path(directory)/'parsed_points.csv'
    if path.is_file():
        for _,row in pd.read_csv(path,dtype=str,keep_default_na=False).iterrows():
            if row.get('source_row'):raw[(row.get('source_sheet',row.get('sheet')),int(float(row['source_row'])),row.get('source_id_cell'))]=row
    def annotate(item):
        r=copy.deepcopy(item);g=groups.get(r.get('group_id'),{})
        sheet_info=sheets.get(g.get('sheet'),{})
        physical_sheet=sheet_info.get('source_sheet') or r.get('source_sheet') or g.get('sheet')
        mapping_reference=g.get('sheet') or physical_sheet
        status=r.get('metric_status','unavailable');why=r.get('reason') or 'derived_observable_not_certified'
        availability='held' if status in ('held','bound','ambiguous') or (status=='unavailable' and why.startswith('unconfirmed')) else 'candidate' if status in ('candidate','valid','converged') else 'unavailable'
        r.update(value=r.get('value'),unit=r.get('unit') or UNITS.get(r.get('parameter'),'1'),availability=availability,reason=why)
        if availability in ('held','unavailable') and r['value'] is not None:
            r['candidate_value_exploratory']=r['value'];r['value']=None
        rows=r.get('source_rows',[]) or ([r['source_row']] if r.get('source_row') is not None else [])
        supports=r.get('derivative_support',[]) or r.get('support_points',[])
        if supports:rows=list(dict.fromkeys([*rows,*[s['source_row'] for s in supports if s.get('source_row') is not None]]))
        cells=[];raw_points=[]
        targets=[(s.get('group_id',g.get('group_id')),s['source_row']) for s in supports if s.get('source_row') is not None]
        targets+= [(g.get('group_id'),n) for n in rows if not any(number==n for _,number in targets)]
        for source_group,number in dict.fromkeys(targets):
            point=points.get((source_group,int(number)))
            source_g=groups.get(source_group,g)
            sheet=(point.get('source_sheet',point.get('sheet')) if point is not None else None) or sheets.get(source_g.get('sheet'),{}).get('source_sheet') or physical_sheet
            xcell=(str(point.get('source_x_cell','')) if point is not None else r.get('source_x_cell'))
            icell=(str(point.get('source_id_cell','')) if point is not None else r.get('source_id_cell'))
            cells.append({'group_id':source_group,'trace_id':source_g.get('trace_id'),'sheet':sheet,'row':int(number),'x':xcell,'id':icell})
            original=raw.get((sheet,int(number),icell))
            raw_points.append({'group_id':source_group,'sheet':sheet,'row':int(number),'x_cell':xcell,'id_cell':icell,
                               'raw_x_cell_value':original.get('raw_x_cell_value') if original is not None else None,
                               'raw_id_cell_value':original.get('raw_id_cell_value') if original is not None else None,
                               'raw_value_reference':'parsed_points.csv' if original is not None else 'raw cell value not cached in this fixture/result'})
        sheet=physical_sheet
        r['source_sheet']=sheet
        method=r.get('formula') or r.get('definition') or 'required inputs absent; extraction not performed'
        transformations=[{'operation':'cached normalized arrays','reference':'curves.csv','column_mapping_reference':'input_provenance.sheet_column_mappings'},
                         {'operation':'metric extraction','formula':method}]
        if r.get('width_m') is not None:
            transformations.extend([{'operation':'m to μm','input_width_m':r['width_m'],'factor':1e6,'output_width_um':r['width_um']},
                                    {'operation':'divide by width_um','input_column':r['input_column'],'input_value_si':r['input_value_si'],'width_source':r.get('width_source')}])
        if r.get('parameter')=='mobility_linear':transformations.append({'operation':'m²/(V s) to cm²/(V s)','factor':1e4})
        fields=summary.get('research_context',{}).get('fields',{})
        r['extraction_method']={'formula':method,'settings':r.get('settings',{}),'gm_source_column':r.get('gm_source_column'),
                                'derivative_settings':g.get('transfer_metrics',{}).get('smoothing_settings',[]),
                                'endpoint':r.get('endpoint'),'weighting':r.get('weighting'),'assumptions':r.get('assumptions',[])}
        r['bias_condition']={'axis':g.get('axis',r.get('axis')),'evaluation_voltage_v':r.get('evaluation_voltage_v'),
                             'evaluation_abs_vds_v':r.get('evaluation_abs_vds_v'),'fixed_voltages_v':r.get('fixed_voltages_v',g.get('conditions',{})),
                             'vg_v':r.get('vg_v'),'positive_group':r.get('positive_group'),'negative_group':r.get('negative_group'),
                             'comparison_reasons':r.get('comparison_reasons',[]),
                             'window_v':r.get('window_v'),'original_sweep':g.get('original_sweep',{}),'direction':g.get('direction'),
                             'gate_block_id':g.get('gate_block_id'),'branch_index':g.get('branch_index'),
                             'metadata':{k:fields.get(k,{}) for k in ('illumination','sweep_delay_s','hold_s','history')}}
        r['provenance']={'source_file':summary.get('source_relative_path'),'source_sha256':summary.get('source_sha256'),
                         'source_sheet':sheet,'source_rows':rows,'source_cells':cells,'raw_points':raw_points,
                         'group_id':g.get('group_id',r.get('group_id')),'trace_id':g.get('trace_id'),
                         'transformations':transformations,'evaluation_window_v':r.get('window_v'),
                         'unit_conversion':{'column_mapping_reference':mapping_reference,'sheet_column_mapping':mappings.get(mapping_reference,{}),
                                            'configured_scales':getattr(cfg,'data',{}).get('columns',{}).get('scales',{}),
                                            'units_confirmed':not g.get('units_review_required',True),'SI_assumption':g.get('units_review_required',True)},
                         'support_points':supports,'source_records':r.get('source_records',{})}
        return r
    return annotate,{'source_file':summary.get('source_relative_path'),'source_sha256':summary.get('source_sha256'),
                     'sheet_column_mappings':mappings,'raw_values':'parsed_points.csv','normalized_arrays':'curves.csv',
                     'configured_scales':getattr(cfg,'data',{}).get('columns',{}).get('scales',{})}


def annotate_method_arrays(arrays,annotate):
    formulas={'y_function_sqrt_a_v':'abs(Id)/sqrt(abs(stored gm))',
              'y_fit_sqrt_a_v':'slope*Vg+intercept within the stated Y fit window',
              'ss_local_mv_per_dec':'1000*ln(10)*abs(Id/stored gm); distinct from direct log10 derivative SS'}
    for a in arrays:
        a['metrics']=[]
        for column,unit in [('y_function_sqrt_a_v','sqrt(A V)'),('y_fit_sqrt_a_v','sqrt(A V)'),('ss_local_mv_per_dec','mV/dec')]:
            held=a.get('units_review_required',True);missing=a.get(column) is None
            record=annotate({**{k:v for k,v in a.items() if k!='metrics'},'parameter':column,
                            'value':a.get(column) if not held else None,
                            'candidate_value_assuming_si':a.get(column) if held else None,'unit':unit,
                            'reason':'method_array_value_not_available' if missing else 'unconfirmed_voltage_or_current_units' if held else 'legacy_exploratory_method_array_not_certified',
                            'formula':formulas[column],'metric_status':'unavailable' if missing else 'held' if held else 'candidate'})
            a['metrics'].append(record)


def annotate_fet_contract(output,curves,summary,cfg,directory):
    annotate,input_provenance=annotator(summary,cfg,curves,directory)
    for name in ('points','extractions'):output[name]=[annotate(r) for r in output[name]]
    annotate_method_arrays(output.get('method_arrays',[]),annotate)
    output['metric_contract_version']=2;output['input_provenance']=input_provenance
    validate_records([*output['points'],*output['extractions'],*[m for a in output.get('method_arrays',[]) for m in a['metrics']]])


def complete_report_contract(report,additional,summary,cfg,directory,curves):
    annotate,input_provenance=annotator(summary,cfg,curves,directory)
    report['direct_metrics']=[annotate(r) for r in report['direct_metrics']]
    records=[*additional['points'],*additional['extractions'],*report['direct_metrics']]
    for g in report['groups']:
        ss=g.get('ss_summary')
        if not ss:continue
        ss['metrics']=[annotate({**ss,'group_id':g['group_id'],'parameter':'ss_direct_'+name,'value':ss.get('value_'+name),
                               'unit':'mV/dec','formula':'1000/abs(d(log10(abs(Id)))/dVg); '+ss.get('weighting',''),
                               'candidate_value_assuming_si':ss.get('candidate_'+name+'_assuming_si'),
                               'candidate_value_exploratory':ss.get('exploratory_'+name)}) for name in ('min','average')]
        records.extend(ss['metrics'])
    for p in report['polarity_pairs']:
        p['metrics']=[]
        for name,unit in p['units'].items():
            item={**{k:v for k,v in p.items() if k!='metrics'},'group_id':p['positive_group'],'parameter':name,
                  'value':None if p['metric_status']=='bound' else p[name],'unit':unit,'formula':p['definition'],
                  'source_records':{'positive':{'group_id':p['positive_group'],**p['source_positive']},'negative':{'group_id':p['negative_group'],**p['source_negative']}},
                  'support_points':[{**point,'group_id':p[polarity+'_group']} for polarity in ('positive','negative') for point in p['source_'+polarity].get('source_points',[])]}
            if p['metric_status']=='bound':item.update(bound_value=p['rr_lower_bound'] if name in ('rr','rr_lower_bound') else None,bound_type='lower')
            elif name=='rr_lower_bound':item.update(metric_status='unavailable',reason='lower_bound_not_applicable_to_detected_or_held_pair')
            record=annotate(item);p['metrics'].append(record);records.append(record)
    records.extend(m for a in additional.get('method_arrays',[]) for m in a['metrics'])
    report['unavailable_metrics']=[annotate({'parameter':k,'value':None,'unit':UNITS[k],'metric_status':'unavailable','reason':v}) for k,v in report['unavailable'].items()]
    records.extend(report['unavailable_metrics'])
    validate_records(records)
    report['metric_records']=records;report['input_provenance']=input_provenance;report['metric_contract_version']=2


def export_contract_csv(document,store,directory):
    from .metric_store import EVIDENCE_FILE
    csv=[]
    for ref in document['metric_records']:
        r=store.encoded_record(ref)
        csv.append({**{k:json.dumps(r[k],ensure_ascii=False,allow_nan=False) if isinstance(r[k],dict) else r[k] for k in ['parameter',*sorted(REQUIRED)]},
                    'metric_ref':ref['$ref'],'evidence_document':EVIDENCE_FILE})
    pd.DataFrame(csv).to_csv(Path(directory)/'research_metrics.csv',index=False,encoding='utf-8-sig')
