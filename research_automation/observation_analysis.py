"""Supplementary observations; the legacy fitter and QC remain unchanged."""
import json
import copy
import re
from pathlib import Path

import numpy as np
import pandas as pd

from .analysis import split_sweeps
from .ingest import load_measurements
from .science_qc import point_qc
from . import observation_metrics as om


def analyze_observations(sheets, cfg, context=None):
    branches=[]; point_tables=[]; anomalies=[]; pairs=[]
    fields=copy.deepcopy((context or {}).get('fields',{}))
    confirmed_units=fields.get('units_confirmed',{})
    user_units=confirmed_units.get('value') is True and confirmed_units.get('status')=='confirmed' and confirmed_units.get('source')=='user_override'
    for sheet_index,sheet in enumerate(sheets,1):
        axis=sheet['axis']; original=sheet['data']
        data,qc=point_qc(original,sheet.get('compliance_a',{}),cfg)
        mapping=sheet['column_mapping']
        if 'ig' in data:
            from .ingest import cell_address
            data['source_ig_cell']=[cell_address(mapping.get('ig',{}).get('source_column'),row) for row in data['source_row']]
        known=user_units or all(mapping.get(k,{}).get('unit_status')=='confirmed' for k in (axis,'id'))
        invalid_fraction=sheet['invalid_rows']/max(sheet['raw_rows'],1)
        blocked=invalid_fraction>cfg.data['qc']['max_invalid_fraction']
        if blocked:data['metric_eligible']=False
        keys=[k for k in sheet['group_by'] if k in data]
        runs=data[keys].ne(data[keys].shift()).any(axis=1).cumsum() if keys else pd.Series(0,index=data.index)
        for run_index,(_,fixed) in enumerate(data.groupby(runs,sort=False),1):
            fixed_context={k:float(fixed.iloc[0][k]) for k in keys}
            run_branches=[]
            for number,(direction,frame) in enumerate(split_sweeps(fixed,axis),1):
                frame=frame.reset_index(drop=True)
                bid=f'b{len(branches)+1:04d}'
                records,derivatives,duplicates=(om.output_metrics(frame,known,cfg) if axis=='vd' else om.transfer_metrics(frame,known,cfg))
                ig_known=user_units or mapping.get('ig',{}).get('unit_status')=='confirmed'
                id_known=user_units or mapping.get('id',{}).get('unit_status')=='confirmed'
                records.extend(om.leakage_metrics(frame,ig_known,id_known))
                conditions={**fixed_context}
                branch={'branch_id':bid,'sheet':sheet['name'],'source_sheet':sheet.get('source_sheet'),
                    'trace_id':sheet.get('trace_id'),'axis':axis,'run_id':f's{sheet_index}/r{run_index}',
                    'branch_index':number,'direction':direction,'conditions':conditions,'n':len(frame),
                    'branch_sweep':{'start':float(frame[axis].iloc[0]),'end':float(frame[axis].iloc[-1]),
                        'minimum':float(frame[axis].min()),'maximum':float(frame[axis].max())},
                    'original_sweep':{'start':float(original[axis].iloc[0]),'end':float(original[axis].iloc[-1]),
                        'minimum':float(original[axis].min()),'maximum':float(original[axis].max()),
                        'source':'whole uncropped trace; stress preserved'},
                    'unit_dependencies':mapping,'units_confirmed':known,'qc_blocked':blocked,
                    'invalid_fraction':invalid_fraction,'excluded_points':int((~frame['metric_eligible']).sum()),
                    'duplicate_voltage_points':int(duplicates.sum()),'metrics':records,'data_qc':qc,
                    'research_status':'exploratory; physical interpretation requires measurement conditions'}
                branches.append(branch);run_branches.append((branch,frame))
                table=frame.copy();table.insert(0,'branch_id',bid);table['axis']=axis
                for derivative in derivatives:table[f'derivative_width_{derivative["width"]:g}']=derivative['values']
                point_tables.append(table)
                for code,count in [('compliance_or_parse_exclusion',branch['excluded_points']),('duplicate_voltage',int(duplicates.sum()))]:
                    if count:anomalies.append({'branch_id':bid,'code':code,'count':count,'interpretation':'candidate; inspect original support'})
                for record in records:
                    if record.get('flags') or (record['parameter']=='gm_peak' and (record.get('peak_position_sensitivity_v') or 0)>2):
                        anomalies.append({'branch_id':bid,'code':record['parameter']+'_review','flags':record.get('flags',[]),
                            'position_sensitivity_v':record.get('peak_position_sensitivity_v'),'interpretation':'numerical candidate; no mechanism attribution'})
                if 'gate_reset_before' in frame and frame['gate_reset_before'].any():
                    anomalies.append({'branch_id':bid,'code':'gate_reset','count':1})
            # Only adjacent branches sharing the original turning point, in the
            # same condition run, are hysteresis pairs. Never pair separate repeats.
            if axis=='vg':
                for (a,af),(b,bf) in zip(run_branches[:-1],run_branches[1:]):
                    shared=af.iloc[-1].get('acquisition_order')==bf.iloc[0].get('acquisition_order')
                    if shared and {a['direction'],b['direction']}=={'forward','reverse'}:
                        forward,reverse=(af,bf) if a['direction']=='forward' else (bf,af)
                        records=[]
                        for gate in (-40,-20,0,20,40):
                            f,r=om.sample(forward,'vg',gate),om.sample(reverse,'vg',gate)
                            val=r['value']-f['value'] if f['value'] is not None and r['value'] is not None else None
                            rec=om.metric('hysteresis_current',val,'A',forward,f['indices'],units_known=known,
                                evaluation_gate_voltage=gate,reverse_points=om.support(reverse,r['indices']),
                                definition='reverse signed Id minus forward signed Id at same gate; adjacent acquisition branches')
                            records.append(rec)
                        for target in (1e-10,1e-9,1e-8):
                            fv,fi=om.monotone_crossings(forward,target) if known else (None,[])
                            rv,ri=om.monotone_crossings(reverse,target) if known else (None,[])
                            records.append(om.metric('hysteresis_voltage',rv-fv if fv is not None and rv is not None else None,'V',forward,fi,
                                units_known=known,criterion_a=target,reverse_points=om.support(reverse,ri),
                                reason='operational_same_criterion' if fv is not None and rv is not None else 'current_units_or_unique_monotone_crossing_unavailable'))
                        pairs.append({'branches':[a['branch_id'],b['branch_id']],'run_id':a['run_id'],'metrics':records})
    settings=sheets[0].get('instrument_settings',{}) if sheets else {}
    # Keep filename timing hints and equipment records side by side, even when
    # a user has already confirmed a different delay. Neither resolves the other.
    delay=fields.get('sweep_delay_s',{'value':None,'source':'unavailable','status':'missing','candidates':[],'history':[]})
    candidates=list(delay.get('candidates',[]))
    if settings.get('sweep_delay_s') is not None:
        candidates.append({'value':om.finite(settings['sweep_delay_s']),'source':'Settings/Sweep Delay'})
    relative=(context or {}).get('relative_path','')
    match=re.search(r'(?i)delay[ _=:-]*(\d+(?:\.\d+)?)\s*s',relative)
    if match:candidates.append({'value':float(match[1]),'source':'filename/delay; not human confirmation'})
    delay['candidates']=candidates
    if len({c['value'] for c in candidates if c.get('value') is not None})>1:delay['status']='conflict'
    fields['sweep_delay_s']=delay
    return {'method_version':om.METHOD_VERSION,'policy':om.POLICY,'branches':branches,'hysteresis_pairs':pairs,
        'anomalies':anomalies,'instrument_settings':settings,'metadata_fields':fields,
        'condition_notices':list((context or {}).get('condition_notices',[])),
        'metadata_status':{'actual_date':fields.get('measurement_date',{}).get('verification','unconfirmed'),
            'geometry':'unconfirmed','illumination':fields.get('illumination',{}).get('verification','unconfirmed'),
            'human_overrides_created':False},
        'model_parameters':{'mobility':{'value':None,'reason':'requires scoped confirmed geometry, capacitance and low-field/model evidence'},
            'threshold_voltage':{'value':None,'reason':'Vcc operational crossings are separate; physical VT model unconfirmed'},
            'intrinsic_contact_resistance':{'value':None,'reason':'two-terminal IV cannot separate channel/contact'},
            'barrier_height':{'value':None,'reason':'temperature/model evidence not supplied'}}},pd.concat(point_tables,ignore_index=True) if point_tables else pd.DataFrame()


def analyze_file(source,cfg,context=None):
    context=copy.deepcopy(context or {})
    # Snapshot paths belong to generated outputs. Naming and per-file metadata
    # must use the original Inbox path, while numerical parsing uses the copy.
    if hasattr(cfg,'paths'):
        original=cfg.paths['inbox']/context['relative_path'] if context.get('relative_path') else Path(source)
        from .device_metadata import context_for,resolved_run_conditions
        try:
            device_context=context_for(original,cfg)
        except ValueError:
            if context.get('relative_path'):raise
            # Standalone analysis also accepts a file outside the configured Inbox.
            # It cannot read scoped device metadata there.
            device_context={'resolved_runs':{},'data':{}}
        _,conditions,notices=resolved_run_conditions(original,device_context,cfg,context.get('fields',{}))
        fields=context.setdefault('fields',{})
        for key in ('measurement_date','illumination'):
            if key in conditions:
                fields[key]=conditions[key]
                fields[key].setdefault('status','confirmed' if fields[key].get('verification')=='user_confirmed' else 'inferred')
        context['condition_notices']=notices
    sheets,ignored=load_measurements(source,cfg,{})
    result,points=analyze_observations(sheets,cfg,context)
    result['ignored_sheets']=ignored
    result['trace_count']=len(sheets)
    return result,points


def write_observations(result,points,directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    (directory/'observations.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    points.to_csv(directory/'observation_points.csv',index=False,encoding='utf-8-sig')
