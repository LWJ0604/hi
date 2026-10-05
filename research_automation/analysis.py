"""Numerical results are independent of AI. Example models are empirical."""
import math
import warnings
from types import SimpleNamespace

import numpy as np
import pandas as pd
from scipy.optimize import OptimizeWarning, curve_fit
from .rectifier_models import fit_effective_models
from .science_qc import point_qc
from .scientific_metrics import rectification_series, transfer_observables, output_observables


def finding(code, status, scope, detail, value=None, threshold=None):
    return {"code": code, "status": status, "scope": scope, "detail": detail, "value": value, "threshold": threshold}


def split_sweeps(frame, xcol):
    """Retain the shared turning point in both adjacent branches."""
    if "segment_id" in frame and frame['segment_id'].nunique()>1:
        return [branch for _, segment in frame.groupby('segment_id',sort=False) for branch in split_sweeps(segment,xcol)]
    x = frame[xcol].to_numpy()
    if len(x)>5:
        steps=np.abs(np.diff(x)); typical=np.median(steps[steps>0]) if np.any(steps>0) else 0
        resets=np.flatnonzero((steps>5*typical)&(steps>.8*np.ptp(x)))+1 if typical else []
        if len(resets):
            cuts=[0,*resets,len(x)]
            result=[]
            for start,end in zip(cuts[:-1],cuts[1:]):
                part=frame.iloc[start:end].copy()
                part['gate_reset_before']=False
                if start:part.iloc[0,part.columns.get_loc('gate_reset_before')]=True
                result.extend(split_sweeps(part,xcol))
            return result
    if len(x) < 2:
        return [("flat", frame)]
    segments, start, direction = [], 0, 0
    for index, change in enumerate(np.diff(x), 1):
        sign = int(np.sign(change))
        if not sign:
            continue
        if direction and sign != direction:
            segments.append(("forward" if direction > 0 else "reverse", frame.iloc[start:index].copy()))
            start = index - 1
        direction = sign
    segments.append(("forward" if direction > 0 else "reverse" if direction < 0 else "flat", frame.iloc[start:].copy()))
    return segments


def fit_models(x, y, cfg):
    n = len(x)
    if n < cfg.data["analysis"]["min_points"] or len(np.unique(x)) < 3:
        return [], ["피팅 포인트 부족 또는 서로 다른 전압값 3개 미만"]
    scale = max(float(np.max(np.abs(y))), cfg.data["analysis"]["current_floor_a"])
    yn = y / scale
    results, failures = [], []
    for model in cfg.data["analysis"]["models"]:
        try:
            notices = []
            if model == "linear":
                # Scaled current avoids optimizer tolerance problems at nanoamps.
                matrix = np.column_stack([x, np.ones(n)])
                params, _, rank, _ = np.linalg.lstsq(matrix, yn, rcond=None)
                if rank < 2:
                    raise ValueError("전압 설계행렬 rank 부족")
                pred = matrix @ params * scale
                physical = {"slope_a_per_v": float(params[0] * scale), "offset_a": float(params[1] * scale)}
                covariance = np.linalg.inv(matrix.T @ matrix) * float(np.sum((yn - matrix @ params) ** 2) / (n - 2)) * scale ** 2
                uncertainties = {key: float(np.sqrt(max(0, value))) for key, value in zip(physical, np.diag(covariance))}
            else:
                xmax = float(np.max(np.abs(x)))
                if xmax == 0:
                    raise ValueError("전압 범위 0")
                def function(voltage, amplitude, alpha):
                    return amplitude * np.sinh(alpha * voltage)
                slope = float(np.dot(x, yn) / max(np.dot(x, x), np.finfo(float).tiny))
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always", OptimizeWarning)
                    params, covariance = curve_fit(function, x, yn, p0=[slope * xmax, 1 / xmax], bounds=([-np.inf, 1e-8 / xmax], [np.inf, 20 / xmax]), maxfev=20000)
                    notices.extend(str(w.message) for w in caught)
                pred = function(x, *params) * scale
                physical = {"i0_a": float(params[0] * scale), "alpha_per_v": float(params[1])}
                uncertainties = {"i0_a": float(np.sqrt(covariance[0, 0]) * scale) if np.isfinite(covariance[0, 0]) else None, "alpha_per_v": float(np.sqrt(covariance[1, 1])) if np.isfinite(covariance[1, 1]) else None}
                if params[1] >= 19.99 / xmax:
                    notices.append("alpha가 상한에 도달; 모델/범위 재검토 필요")
            rss = float(np.sum((y - pred) ** 2))
            k = 2
            variance = max(rss / n, np.finfo(float).tiny)
            values = [rss, *physical.values(), *pred]
            if not all(math.isfinite(float(value)) for value in values):
                raise ValueError("피팅 결과에 비유한 값")
            results.append({"model": model, "n": n, "k": k, "parameters": physical, "parameter_std": uncertainties, "rss_a2": rss, "rmse_a": float(np.sqrt(rss / n)), "aic": float(2 * k + n * np.log(variance)), "bic": float(k * np.log(n) + n * np.log(variance)), "warnings": notices, "predicted": pred.tolist()})
        except (ValueError, RuntimeError, FloatingPointError, np.linalg.LinAlgError) as error:
            failures.append(f"{model}: {error}")
    results.sort(key=lambda item: item["aic"])
    return results, failures


def qc_branch(frame, cfg, scope):
    limits = cfg.data["qc"]
    checks = []
    if "ig" in frame and np.isfinite(frame["ig"]).all():
        leakage = float(frame["ig"].abs().max())
        checks.append(finding("gate_leakage", "WARN" if leakage > limits["gate_leakage_a"] else "PASS", scope, "측정된 |Ig| 최대값; Id를 게이트 누설로 대체하지 않음", leakage, limits["gate_leakage_a"]))
    else:
        checks.append(finding("gate_leakage", "SKIP", scope, "유효한 Ig 컬럼 전체가 없어 검사 불가"))
    zero = frame[np.abs(frame["vd"]) <= limits["zero_voltage_tolerance_v"]] if "vd" in frame else frame.iloc[:0]
    if len(zero):
        offset = float(zero["id"].abs().max())
        checks.append(finding("zero_offset", "WARN" if offset > limits["zero_offset_a"] else "PASS", scope, "Vd≈0에서 |Id|; 물리적 오프셋 원인은 단정할 수 없음", offset, limits["zero_offset_a"]))
    else:
        checks.append(finding("zero_offset", "SKIP", scope, "Vd≈0의 측정점 없음"))
    if len(frame) > 1:
        jump = float(frame["id"].diff().abs().max())
        checks.append(finding("current_jump", "WARN" if jump > limits["current_jump_a"] else "PASS", scope, "원래 측정 순서의 인접 |ΔId| 최대; 급경사도 경고될 수 있음", jump, limits["current_jump_a"]))
    return checks


def rectification(frame, cfg):
    target = cfg.data["analysis"]["rr_voltage"]
    if cfg.data["analysis"]["x"] != "vd":
        return {"status": "SKIP", "reason": "Id–Vd에서만 RR 계산", "voltage_v":target,"unit":"1"}
    if target <= 0:
        return {"status": "SKIP", "reason": "rr_voltage는 양수 필요"}
    item=next(item for item in rectification_series(frame,cfg) if item['evaluation_abs_vd_v']==target)
    return {'status':'OK' if item['value'] is not None else 'SKIP','voltage_v':target,'unit':'1',
        'ratio_abs_i_positive_over_negative':item['value'],'metric_status':item['metric_status'],
        'i_positive_a':item['positive_current']['value'],'i_negative_a':item['negative_current']['value'],
        'reason':item['reason'],'method':'exact point first, adjacent valid interpolation only; no averaging/extrapolation'}


def transfer_metrics(frame, cfg):
    if cfg.data["analysis"]["x"] != "vg":
        return {"status": "SKIP", "reason": "Id–Vg에서만 전달곡선 지표 계산"}, None
    return transfer_observables(frame,cfg)


def compliance_checks(frame, settings, scope):
    checks = []
    for voltage, current in (("vd", "id"), ("vg", "ig")):
        limit = settings.get(voltage)
        if limit is None or limit <= 0 or current not in frame or not np.isfinite(frame[current]).all():
            continue
        ratio = float(frame[current].abs().max()) / limit
        checks.append(finding("compliance_proximity_" + current, "WARN" if ratio >= .98 else "PASS", scope, "Settings의 전류 compliance 대비 최대 측정 전류; 실제 compliance 상태 플래그를 뜻하지 않음", ratio, .98))
    return checks


def hysteresis(branches, cfg, scope):
    xcol = cfg.data["analysis"]["x"]
    found = []
    for index in range(len(branches) - 1):
        first, second = branches[index:index + 2]
        if first[0] == second[0] or "flat" in (first[0], second[0]):
            continue
        if any(item[1][xcol].duplicated().any() for item in (first,second)):
            continue
        if 'segment_id' in first[1] and set(first[1]['segment_id'])!=set(second[1]['segment_id']):continue
        if 'gate_reset_before' in second[1] and second[1]['gate_reset_before'].iloc[0]:continue
        a, b = [item[1].groupby(xcol, sort=True)["id"].mean() for item in (first, second)]
        lower, upper = max(a.index.min(), b.index.min()), min(a.index.max(), b.index.max())
        if len(a) < 3 or len(b) < 3 or lower >= upper:
            continue
        grid = np.unique(np.concatenate([a.index.to_numpy(), b.index.to_numpy()]))
        grid = grid[(grid >= lower) & (grid <= upper)]
        if len(grid) < 3:
            continue
        difference = np.abs(np.interp(grid, a.index, a) - np.interp(grid, b.index, b))
        area = float(np.trapezoid(difference, grid))
        mean = area / (upper - lower)
        threshold = cfg.data["qc"]["hysteresis_mean_difference_a"]
        item = finding("hysteresis", "WARN" if mean > threshold else "PASS", scope + f"/pair-{index + 1}", "인접 정·역스윕의 공통 범위 |전류 차| 적분/전압폭; 이전 실험 대비 증가를 의미하지 않음", mean, threshold)
        item.update({"area_a_v": area, "overlap_v": [float(lower), float(upper)]})
        found.append(item)
    return found or [finding("hysteresis", "SKIP", scope, "비교 가능한 인접 정·역스윕 없음")]


def analyze(sheets, cfg):
    groups, checks, curves = [], [], []
    gate_block, previous_gate = 1, None
    for sheet in sheets:
        xcol = sheet.get("axis", cfg.data["analysis"]["x"])
        options = {**cfg.data["analysis"], "x": xcol, "group_by": sheet.get("group_by", cfg.data["analysis"]["group_by"])}
        if xcol == "vg":
            options["models"] = cfg.data["analysis"]["transfer_models"]
        effective = SimpleNamespace(data={**cfg.data, "analysis": options})
        data, scientific_qc = point_qc(sheet["data"],sheet.get('compliance_a',{}),cfg)
        sheet['data_qc']=scientific_qc
        fraction = sheet["invalid_rows"] / max(sheet["raw_rows"], 1)
        blocked = fraction > cfg.data["qc"]["max_invalid_fraction"]
        checks.append(finding("invalid_rows", "FAIL" if blocked else "WARN" if fraction else "PASS", sheet["name"], "필수 비수치/비유한 행 비율; 임계값 초과 시 해당 시트 피팅 제외", fraction, cfg.data["qc"]["max_invalid_fraction"]))
        keys = [key for key in options["group_by"] if key in data]
        # Consecutive condition runs preserve gate resets/repeated blocks.
        if keys:
            run = data[keys].ne(data[keys].shift()).any(axis=1).cumsum()
            iterator = [(tuple(fixed.iloc[0][key] for key in keys),fixed) for _,fixed in data.groupby(run,sort=False)]
        else:
            iterator = [((),data)]
        for conditions, fixed in iterator:
            if not isinstance(conditions, tuple):
                conditions = (conditions,)
            context = dict(zip(keys, [float(value) for value in conditions]))
            if xcol=='vd' and 'vg' in context:
                if previous_gate is not None and context['vg']<previous_gate:gate_block+=1
                previous_gate=context['vg']
            label = sheet["name"] + "/" + ",".join(f"{key}={value:g}" for key, value in context.items())
            branches = split_sweeps(fixed, xcol)
            checks.extend(hysteresis(branches, effective, label))
            for branch_index, (direction, branch) in enumerate(branches, 1):
                if 'gate_reset_before' in branch and branch['gate_reset_before'].iloc[0]:gate_block+=1
                if len(groups) >= cfg.data["analysis"]["max_groups"]:
                    raise ValueError("analysis.max_groups 초과; 고정 조건 값/노이즈/컬럼 매핑을 확인하세요.")
                gid = f"g{len(groups) + 1:04d}"
                scope = label + f"/{direction}-{branch_index}"
                checks.extend(qc_branch(branch, effective, scope))
                checks.extend(compliance_checks(branch, sheet.get("compliance_a", {}), scope))
                x, y = branch[xcol].to_numpy(), branch["id"].to_numpy()
                eligible=branch['metric_eligible'].to_numpy(dtype=bool)
                fits, failures = ([], ["무효 행 비율이 임계값을 초과하여 피팅 중단"]) if blocked else fit_models(x[eligible], y[eligible], effective)
                for fit in fits:
                    aligned=np.full(len(branch),np.nan)
                    aligned[eligible]=fit['predicted']
                    fit['predicted']=aligned.tolist()
                    fit['model_status']='unstable' if fit['warnings'] else 'converged'
                    fit['assessment']='single_empirical_baseline' if len(options['models'])==1 else 'empirical_candidate_comparison'
                transfer, derivative = ({"status": "SKIP", "reason": "QC FAIL로 전달 지표 계산 제외"}, None) if blocked else transfer_metrics(branch, effective)
                # Avoid retaining point arrays in AI/result metadata; keep in curves.csv.
                for index, (_, row) in enumerate(branch.iterrows()):
                    curve = {"group_id": gid, "sheet": sheet["name"], "trace_id": sheet.get("trace_id"), "axis": xcol, "source_row": int(row["source_row"]), "x_v": float(x[index]), "id_a": float(y[index])}
                    for key in ('acquisition_order','source_sheet','source_id_cell','source_x_cell','point_flags','metric_eligible','segment_id','compliance_flag'):
                        if key in row:curve[key]=row[key].item() if isinstance(row[key],np.generic) else row[key]
                    curve.update({'sweep_id':f"{sheet['name']}/run-{len(groups)+1}",'gate_block_id':f"block-{gate_block:03d}",'branch_id':gid})
                    if derivative is not None:
                        for key,values in derivative.items():
                            value=values[index]
                            curve[key]=value.item() if isinstance(value,np.generic) else value
                    if "ig" in row and np.isfinite(row["ig"]):
                        curve["ig_a"] = float(row["ig"])
                    for fit in fits:
                        curve[fit["model"] + "_predicted_a"] = fit["predicted"][index]
                    curves.append(curve)
                for fit in fits:
                    fit.pop("predicted")
                rr = {"status": "SKIP", "reason": "QC FAIL로 RR 계산 제외"} if blocked else rectification(branch, effective)
                rr['voltage_v']=options['rr_voltage']; rr['unit']='1'
                rr_series=rectification_series(branch,effective) if xcol=='vd' and not blocked else []
                observables,resistance,conductance=output_observables(branch,effective) if xcol=='vd' and not blocked else ([],None,None)
                if conductance is not None:
                    for row,value in zip(curves[-len(branch):],conductance):row['did_dvd_a_per_v']=float(value)
                steps=np.diff(sheet['data'][xcol].to_numpy())
                programmed={}
                for field,key in (('start/level','programmed_start_v'),('stop','programmed_end_v'),('step','programmed_step_v')):
                    try:
                        value=float(sheet.get('sweep_program',{}).get(field))
                        if np.isfinite(value):programmed[key]=value
                    except (TypeError,ValueError):pass
                groups.append({"group_id": gid, "axis": xcol, "axis_source": sheet.get("axis_source", "configuration"), "trace_id": sheet.get("trace_id"), "sheet": sheet["name"], "conditions": context, "direction": direction, "branch_index": branch_index, "scope": scope, "n": len(branch), "x_min_v": float(x.min()), "x_max_v": float(x.max()), "id_min_a": float(y.min()), "id_max_a": float(y.max()), "fits": fits, "fit_failures": failures, "best_model": fits[0]["model"] if fits else None, "rectification": rr, "transfer_metrics": transfer,
                    'gate_block_id':f"block-{gate_block:03d}",'branch_id':gid,'sweep_id':f"{sheet['name']}/run-{len(groups)+1}",
                    'original_sweep':{'start_v':float(sheet['data'][xcol].iloc[0]),'end_v':float(sheet['data'][xcol].iloc[-1]),'min_v':float(sheet['data'][xcol].min()),'max_v':float(sheet['data'][xcol].max()),'steps_v':sorted(set(float(s) for s in steps)),'unit':'V','source':'uncropped measurement trace','programmed_source':'Settings' if programmed else None,**programmed},
                    'data_qc':scientific_qc,'model_status':'not_run' if not fits and not failures else 'failed' if not fits else 'converged',
                    'unit_status':'inferred' if any(m.get('unit_status')=='inferred' for k,m in sheet['column_mapping'].items() if k in (xcol,'id')) else 'confirmed',
                    'rr_series':rr_series,'output_observables':observables,'effective_differential_resistance':resistance,
                    'rectifier_models':fit_effective_models(branch,effective) if xcol=='vd' and not blocked else {'model_status':'not_run','reason':'not_applicable_or_parse_qc_failure','models':[]}})
    status = "FAIL" if any(c["status"] == "FAIL" for c in checks) else "WARN" if any(c["status"] == "WARN" for c in checks) else "PASS"
    axes = {group["axis"] for group in groups}
    return {"groups": groups, "axis": next(iter(axes)) if len(axes) == 1 else "mixed", "qc": {"overall": status, "checks": checks}, "model_caveat": "I–Vd의 linear/sinh와 Id–Vg의 linear는 경험적 기준선. AIC/BIC는 동일 그룹·동일 점·동일 잔차 가정 안에서만 비교; 전도 메커니즘 증명 아님. 서로 다른 trace는 독립적으로 보존."}, pd.DataFrame(curves)
