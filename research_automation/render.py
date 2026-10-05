import shutil
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .util import atomic_text, slug
from .organization import component
from .plot_style import (EXPORT_DPI, RAINBOW, bias_colors, export_theme,
                         format_axes, palette, voltage_label)


@export_theme
def plots(curves, summary, destination):
    files = []
    context = summary.get("research_context", {})
    device = context.get("device_name") or "Measurement"
    lighting = context.get("illumination") or summary.get("illumination", {}).get("value")
    title_prefix = device + (f" / {lighting}" if lighting else "")
    from .note_figures import subtitle
    if summary.get('groups'):
        title_prefix = subtitle(summary, summary['groups'][0])
    for axis in sorted({group["axis"] for group in summary["groups"]}):
        figure, ax = plt.subplots(figsize=(8, 5))
        selected = [group for group in summary["groups"] if group["axis"] == axis]
        colors, values, norm, fixed = bias_colors(selected, axis)
        for group in sorted(selected, key=lambda group: (values.get(group["group_id"], float("-inf")), group["group_id"])):
            data = curves[curves["group_id"] == group["group_id"]]
            bias = values.get(group["group_id"])
            label = f"{fixed.upper()} = {bias:g} V" if bias is not None else "Fixed bias unknown"
            label += f" / {group['group_id']}"
            ax.plot(data["x_v"], data["id_a"], color=colors[group["group_id"]], label=label)
        format_axes(ax, axis, r"Drain current, $I_D$ (A)")
        ax.set_title(f"{title_prefix}\n{'Output' if axis == 'vd' else 'Transfer'} / {len(selected)} individual curves")
        if any(g.get('units_review_required') for g in selected):
            ax.text(.02,.97,'Units assumed: confirm V/A',transform=ax.transAxes,va='top',fontsize=8,bbox={'facecolor':'white','alpha':.9})
        if len(selected) <= 10:
            ax.legend(fontsize=7, loc="best")
        elif norm is not None and norm.vmin != norm.vmax:
            colorbar = figure.colorbar(matplotlib.cm.ScalarMappable(norm=norm, cmap=RAINBOW), ax=ax, pad=.03)
            colorbar.set_label(voltage_label(fixed))
            if len(set(values.values())) <= 9:
                colorbar.set_ticks(sorted(set(values.values())))
        elif values:
            ax.text(.02, .97, f"{fixed.upper()} = {next(iter(values.values())):g} V",
                    transform=ax.transAxes, va="top")
        if len(selected) > 10 and len(values) < len(selected):
            ax.text(.02, .03, "Gray: fixed bias unknown", transform=ax.transAxes,
                    fontsize=8, bbox={"facecolor": "white", "edgecolor": "gray"})
        figure.tight_layout()
        name = f"overview_{axis}.png"
        figure.savefig(destination / name, dpi=EXPORT_DPI)
        plt.close(figure)
        files.append(name)
    for group in summary["groups"]:
        gid = group["group_id"]
        group_title = subtitle(summary, group) + ('\nUnits assumed: confirm V/A' if group.get('units_review_required') else '')
        data = curves[curves["group_id"] == gid]
        figure, axes = plt.subplots(2, 1, figsize=(8, 7), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
        fits = sorted(group["fits"], key=lambda fit: fit["model"])
        colors = palette(len(fits) + 1)
        axes[0].plot(data["x_v"], data["id_a"], color=colors[0], marker=".", label="Measured")
        if 'metric_eligible' in data:
            excluded=data[~data['metric_eligible'].astype(bool)]
            axes[0].plot(excluded['x_v'],excluded['id_a'],'rx',label='Excluded from metrics')
        ordered = data.sort_values("x_v")
        for fit, color in zip(fits, colors[1:]):
            name = fit["model"]
            axes[0].plot(ordered["x_v"], ordered[name + "_predicted_a"], color=color, linestyle="--", label=name)
            axes[1].plot(data["x_v"], data["id_a"] - data[name + "_predicted_a"], color=color, marker=".", label=name)
        format_axes(axes[0], group["axis"], r"Drain current, $I_D$ (A)")
        format_axes(axes[1], group["axis"], "Current residual (A)")
        conditions = " / ".join(f"{key.upper()} = {value:g} V" for key, value in sorted(group["conditions"].items()))
        details = [conditions or "Fixed bias unknown", group["direction"]]
        if group.get("trace_id") is not None:
            details.append(f"Trace {group['trace_id']}")
        axes[0].set_title(group_title + "\n" + " / ".join(details))
        axes[0].legend()
        resistance=group.get('effective_differential_resistance')
        if resistance and resistance.get('window_v'):
            axes[0].axvspan(*resistance['window_v'],color='gray',alpha=.08,label='Zero-voltage slope support')
        axes[1].axhline(0, color="gray", linestyle="--")
        figure.tight_layout()
        name = f"{gid}_fit.png"
        figure.savefig(destination / name, dpi=EXPORT_DPI)
        plt.close(figure)
        files.append(name)
        if group["axis"] == "vg":
            figure, axes = plt.subplots(3, 1, figsize=(8, 9), sharex=True)
            absolute = data["id_a"].abs()
            axes[0].semilogy(data["x_v"], absolute.where(absolute > 0), ".-", color=RAINBOW(0.), label="|Id|")
            if "gm_a_per_v" in data:
                axes[1].plot(data["x_v"], data["gm_a_per_v"], ".-", color='#555555', label="Raw gm (endpoints retained)")
                smoothed=[c for c in data if c.startswith('gm_local_') and c.endswith('_a_per_v')]
                for column,color in zip(smoothed,palette(len(smoothed))):
                    if not data[column].notna().any():continue
                    axes[1].plot(data['x_v'],data[column],color=color,label=column.replace('gm_local_w','Local ').replace('_a_per_v',' V (full window width)'))
                if 'gm_raw_endpoint' in data:
                    end=data[data['gm_raw_endpoint'].astype(bool)]
                    axes[1].plot(end['x_v'],end['gm_a_per_v'],'rx',label='Raw endpoints')
                if smoothed:axes[1].legend(fontsize=7)
            axes[1].axhline(0, color="gray", linestyle="--")
            if "ig_a" in data:
                leakage = data["ig_a"].abs()
                axes[2].semilogy(data["x_v"], leakage.where(leakage > 0), ".-", color=RAINBOW(0.), label="|Ig|")
            format_axes(axes[0], "vg", r"Drain current, $|I_D|$ (A), log")
            format_axes(axes[1], "vg", r"Transconductance, $g_m$ (A/V)")
            format_axes(axes[2], "vg", r"Gate current, $|I_G|$ (A), log")
            axes[0].set_title(f"{group_title}\n{gid} / Vd={group['conditions'].get('vd', 'unknown')} V")
            for metric_name,color in [('vth','cyan'),('ss','gold')]:
                metric=group.get('transfer_metrics',{}).get(metric_name,{})
                if metric.get('window_v') and (metric.get('value') is not None or metric.get('candidate_value_assuming_si') is not None):
                    axes[0].axvspan(*metric['window_v'],color=color,alpha=.15,label=metric_name+' extraction window')
            if 'metric_eligible' in data:
                excluded=data[~data['metric_eligible'].astype(bool)]
                axes[0].plot(excluded['x_v'],excluded['id_a'].abs(),'rx',label='Excluded from metrics')
            figure.tight_layout()
            name = f"{gid}_transfer.png"
            figure.savefig(destination / name, dpi=EXPORT_DPI)
            plt.close(figure)
            files.append(name)
        effective=group.get('rectifier_models',{})
        models=[m for m in effective.get('models',[]) if 'predicted_current_a' in m]
        if models:
            import numpy as np
            figure,axes=plt.subplots(2,2,figsize=(10,8),sharex='col')
            for col,sign in enumerate((1,-1)):
                for model,color in zip(models,palette(len(models))):
                    u=np.asarray(model['voltage_abs_v']);mask=np.asarray(model['polarity'])==sign
                    axes[0,col].plot(u[mask],np.asarray(model['predicted_current_a'])[mask],color=color,label=model['model'])
                    axes[1,col].plot(u[mask],np.asarray(model['residual_current_a'])[mask],color=color)
                first=models[0];u=np.asarray(first['voltage_abs_v']);mask=np.asarray(first['polarity'])==sign
                held=np.asarray(first['heldout_mask']) & mask
                axes[0,col].plot(u[mask],np.asarray(first['observed_abs_current_a'])[mask],'k.',label='Measured')
                axes[0,col].plot(u[held],np.asarray(first['observed_abs_current_a'])[held],'rx',label='Held-out voltage region')
                axes[0,col].set_title(group_title+(' / +Vd' if sign==1 else ' / -Vd'))
                axes[0,col].legend(fontsize=7)
                for row,ylabel in ((0,r'Current magnitude, $|I_D|$ (A)'),(1,'Current residual (A)')):
                    format_axes(axes[row,col],'vd',ylabel)
                    axes[row,col].set_xlabel(r'Voltage magnitude, $|V_{DS}|$ (V)')
                    axes[row,col].axvspan(*effective['window_v'],color='gray',alpha=.08)
                axes[1,col].axhline(0,color='gray',linestyle='--')
            figure.tight_layout();name=f'{gid}_rectifier_models.png'
            figure.savefig(destination/name,dpi=EXPORT_DPI);plt.close(figure);files.append(name)
    for index,knee in enumerate(summary.get('comparisons',{}).get('rr_knees',[])):
        if knee.get('knee_vg_v') is None:continue
        points=[]
        for group in summary['groups']:
            if group['group_id'] in knee['group_ids']:
                for item in group.get('rr_series',[]):
                    if item['evaluation_abs_vd_v']==knee['evaluation_abs_vd_v'] and item['value'] is not None:points.append((item['vg_v'],item['value']))
        points=sorted(points);figure,ax=plt.subplots(figsize=(8,5))
        ax.plot([p[0] for p in points],[p[1] for p in points],color=RAINBOW(0.),marker='.')
        if knee['rr_axis']=='log':ax.set_yscale('log')
        format_axes(ax,'vg','Rectification ratio, RR (1)')
        ax.axvline(knee['knee_vg_v'],color='red',linestyle='--',label='Transition candidate')
        ax.set_title(title_prefix+f" / RR at |Vd|={knee['evaluation_abs_vd_v']:g} V / {knee['metric_status']}")
        ax.legend();figure.tight_layout();name=f'rr_knee_{index:03d}.png'
        figure.savefig(destination/name,dpi=EXPORT_DPI);plt.close(figure);files.append(name)
    from .note_figures import evidence_figures,parameter_figures
    files.extend(evidence_figures(curves, summary, destination))
    files.extend(parameter_figures(curves, summary, destination))
    return files


def escape(value):
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def vault_locations(summary):
    context = summary.get("research_context")
    if not context:
        note_name = f"{summary['created_at'][:10]}_{slug(summary['source_filename'])}_{summary['job_id'][:16]}"
        return f"Experiments/{note_name}.md", f"Attachments/{summary['job_id']}"
    subfolder = context["vault_subfolder"]
    if summary.get("schema_version",0)>=4:
        subfolder = "v" + summary["version"] + "/" + subfolder
    name = component(Path(summary['source_filename']).stem, 40) + "_" + summary['job_id'][:16] + ".md"
    return f"Experiments/{subfolder}/{name}", f"Attachments/{subfolder}/{summary['job_id'][:16]}"


def experiment_note(summary, result_dir, cfg):
    if summary.get("schema_version",0)>=4:
        from .science_exports import note
        return note(summary,result_dir,cfg)
    note_relative, assets_relative = vault_locations(summary)
    asset_dir = cfg.paths["vault"] / assets_relative
    asset_dir.mkdir(parents=True, exist_ok=True)
    metric_files = ["metrics.csv"] if (result_dir / "metrics.csv").exists() else []
    for name in ["normalized.csv", "fit_results.csv", "curves.csv", "result.json", *metric_files, *summary["figures"]]:
        shutil.copy2(result_dir / name, asset_dir / name)
    ai = summary["interpretation"]
    lines = ["---", "type: experiment", f"job_id: {summary['job_id']}", f"created: {summary['created_at']}", f"qc: {summary['qc']['overall']}", f"ai_status: {ai['status']}", f"source_sha256: {summary['source_sha256']}", "tags: [research, automated, review-required]", "---", f"# {escape(summary['source_filename'])}", "", "> 자동 생성 영역입니다. 수정 기록은 별도 연구노트에 작성해 이 노트를 링크하세요. AI 가설 및 예시 QC 기준은 연구자 검토가 필요합니다.", "", f"- 분석 축: {summary['axis']}–Id (V/A)", f"- 처리 시각: {summary['created_at']}", f"- 원본 SHA-256: `{summary['source_sha256']}`", f"- 코드 버전: {summary['version']}; 설정 SHA-256: `{summary['config_sha256']}`", f"- QC: **{summary['qc']['overall']}**; AI 상태: `{ai['status']}`", "", "## 입력 및 단위 확인"]
    context = summary.get("research_context", {})
    if context:
        properties = {key: context.get(key) for key in ("measurement_date", "device_name", "device_type", "fold", "measurement_type", "illumination", "condition_label", "device_path", "source_relative_path", "measurement_date_source", "device_name_source", "illumination_source")}
        properties["fixed_conditions_v"] = context["fixed_conditions_v"]
        properties["sweep_ranges_v"] = context["sweep_ranges_v"]
        properties["metadata_review_required"] = bool(context["warnings"])
        lines[8:8] = [f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in properties.items()]
        heading = lines.index("## 입력 및 단위 확인")
        details = ["## 측정 분류", "", f"- 소자 이름: {escape(context['device_name'] or '미확인')} ({escape(context['device_name_source'])})", f"- 소자 종류/재료: {escape(context['device_type'] or '미확인')}; fold: {escape(context['fold'] or '미확인')}", f"- 측정 날짜: {context['measurement_date'] or '미확인'} ({escape(context['measurement_date_source'])})", f"- 측정 조건: {escape(context['condition_label'])}", f"- 고정 전압 조건 (V): {escape(context['fixed_conditions_v'])}", f"- 스윕 범위 (V): {escape(context['sweep_ranges_v'])}", f"- 원본 상대 경로: {escape(context['source_relative_path'])}", "- 날짜·소자·조명 후보와 출처는 result.json의 research_context.evidence에 보존합니다."]
        details += [f"- 분류 확인: {escape(warning)}" for warning in context["warnings"]]
        lines[heading:heading] = details + [""]
    instrument = summary.get("instrument_settings", {})
    if instrument:
        lines += [f"- KTEI: {escape(instrument.get('ktei_version', 'unknown'))}; 측정 시각 원문: {escape(instrument.get('measurement_timestamp_raw', 'unknown'))} (원문 시간대 미확인)", f"- 고정 전압 설정: {escape(instrument.get('fixed_bias_v', {}))}; 설정값과 실측값은 구분합니다."]
    if "illumination" in summary:
        lines.append(f"- 조명 조건: {summary['illumination']['value']} ({summary['illumination']['source']})")
    for sheet in summary["sheets"]:
        lines.append(f"- {escape(sheet['name'])}: 원본 {sheet['raw_rows']}행, 제외 {sheet['invalid_rows']}행")
        for key, mapping in sheet["column_mapping"].items():
            lines.append(f"  - {key} ← {escape(mapping['source'])}; SI 변환 배수 {mapping['factor_to_si']:g}")
        for warning in sheet["warnings"]:
            lines.append(f"  - 확인: {escape(warning)}")
        for warning in sheet.get("reader_warnings", []):
            lines.append(f"  - 파일 읽기 경고 기록: {escape(warning)}")
    lines += [f"- 실행 코드 SHA-256: `{summary['code_sha256']}`"]
    for item in summary["ignored_sheets"]:
        lines.append(f"- 시트 제외: {escape(item['sheet'])} ({escape(item['reason'])})")
    lines += ["", "## QC", "", "| 항목 | 범위 | 상태 | 값 | 기준 |", "|---|---|---|---|---|"]
    for item in summary["qc"]["checks"]:
        lines.append("| " + " | ".join(escape(item.get(key, "")) if item.get(key) is not None else "—" for key in ("code", "scope", "status", "value", "threshold")) + " |")
    lines += ["", "QC 정의와 제외 사유는 첨부 result.json을 확인하세요.", "", "## 그룹별 피팅", "", "| 그룹 | 고정 조건 | 방향 | 점 수 | 모델 | RMSE (A) | AIC | BIC |", "|---|---|---|---|---|---|---|---|"]
    for group in summary["groups"]:
        for fit in group["fits"]:
            lines.append(f"| {group['group_id']} | {escape(group['conditions'])} | {group['direction']} | {fit['n']} | {fit['model']} | {fit['rmse_a']:.4g} | {fit['aic']:.3f} | {fit['bic']:.3f} |")
        for failure in group["fit_failures"]:
            lines.append(f"\n- {group['group_id']} 피팅 제외/실패: {escape(failure)}")
    lines += ["", "## 측정 유형별 지표", "", "같은 조건이라도 서로 다른 trace는 개별 곡선으로 보존합니다. 두 곡선이 모두 정방향이면 히스테리시스로 해석하지 않습니다.", "", "| 그룹 | 축 | trace | RR (+V/−V) | gm 최대 (A/V) | 측정 구간 최대/최소 전류 비율 |", "|---|---|---|---|---|---|"]
    for group in summary["groups"]:
        metrics = group.get("transfer_metrics", {})
        values = [group["group_id"], group["axis"], group.get("trace_id"), group["rectification"].get("ratio_abs_i_positive_over_negative"), metrics.get("gm_max_a_per_v"), metrics.get("current_range_ratio_abs")]
        lines.append("| " + " | ".join(f"{value:.5g}" if isinstance(value, float) else escape(value) if value is not None else "—" for value in values) + " |")
    lines += ["", "GM/GM2 계산 오류는 필수 측정행을 제외하지 않습니다. gm은 유효한 Id/Vg의 비평활 수치 미분이며 잡음 영향을 받습니다. 문턱전압/SS/이동도는 별도 추출 기준 없이 계산하지 않습니다."]
    lines += ["", summary["model_caveat"], "", "## 해석", "", f"해석 모델: `{ai.get('model') or '수치 요약'}`", "", ai["summary"]]
    for title, key in [("관측", "observations"), ("검증되지 않은 가설", "hypotheses"), ("다음 실험 제안", "next_steps")]:
        lines += ["", f"### {title}", ""] + [f"- {value}" for value in ai[key]]
    lines += ["", "## 그래프 및 데이터", ""]
    for name in summary["figures"]:
        lines.append(f"![[{assets_relative}/{name}]]")
    for name in ("normalized.csv", "curves.csv", "fit_results.csv", *metric_files, "result.json"):
        lines.append(f"[[{assets_relative}/{name}|{name}]]")
    path = cfg.paths["vault"] / note_relative
    atomic_text(path, "\n".join(lines) + "\n")
    return path


def measurement_catalog(cfg, jobs):
    from .note_index import publish_index
    latest={}
    for job in sorted(jobs,key=lambda j:j['completed_at']):
        try:
            summary=json.loads(Path(job['result_path']).read_text(encoding='utf-8'))
            if summary.get('version') != __import__('research_automation').__version__:continue
            relative=Path(job['note_path']).relative_to(cfg.paths['vault']).as_posix()
            if not (cfg.paths['vault']/relative).is_file():continue
            latest[summary['source_relative_path']]=(summary,relative)
        except (OSError,ValueError,KeyError,TypeError):continue
    return publish_index(cfg,list(latest.values()),jobs)
