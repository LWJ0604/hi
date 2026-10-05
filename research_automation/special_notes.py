"""Presentation for parsing failures and scientifically gated photo comparisons."""
import json
from pathlib import Path
import shutil
from . import __version__
from .note_presentation import QUESTIONS,cell,number,fold,LABELS
from .util import atomic_text,now
from .plot_style import export_theme,format_axes,palette,EXPORT_DPI


def failure_note(diagnostic,cfg):
    data=json.loads(Path(diagnostic).read_text(encoding='utf-8'))
    if data.get('parse_status')!='failed':return None
    stamp=now(cfg).strftime('%Y%m%d-%H%M%S-%f')
    assets=f'Attachments/v{__version__}/ReadFailures/{stamp}'
    target=cfg.paths['vault']/assets;target.mkdir(parents=True,exist_ok=False)
    shutil.copy2(diagnostic,target/'diagnostic.json')
    path=cfg.paths['vault']/f'Experiments/v{__version__}/읽기 실패/{data["job_id"]}_{stamp}.md'
    text=['# '+cell(Path(data['source_relative_path']).name),'',
          '## ① 연구 질문','','이 파일에 분석 가능한 측정 전압·전류가 기록되어 있는가?','',
          '## ② 조건 한 줄','','측정 날짜 미확인 · 소자 미확인 · 광 조건 미확인 · 고정 전압·원래 sweep·방향·블록·delay 미확인','',
          '## ③ 현재 판단','','**파일 읽기 실패**','',
          '측정 파일을 읽지 못해 곡선과 정량 지표를 제공할 수 없습니다. 이 실패는 소자의 측정 결과가 나쁘다는 뜻이 아닙니다.','',
          '## ④ 대표 근거 그림','','파싱 실패로 대표 측정 그림을 생성하지 못했습니다. 전압·전류 열을 읽지 못했으므로 곡선에 대한 해석은 보류합니다.','',
          '## ⑤ 핵심 수치 (최대 3개)','','추출하지 않음 · 파일 읽기 실패','',
          '## ⑥ 의미와 한계','','측정에서 관측한 것: 읽기 실패로 요약할 근거가 없습니다. 모델로 추정한 것: 피팅을 수행하지 않았습니다. 아직 확인되지 않은 해석: 소자 성능을 판단할 수 없습니다.','',
          '## ⑦ 다음 확인 한 가지','','원본 파일의 데이터 시트에서 전압·전류 열 이름과 첫 측정행을 확인하고, 파라미터 분석표인지 실제 측정 파일인지 실험 기록에 구분해 기록하세요.','',
          '## ⑧ 접힌 상세 정보','']
    text+=fold('원래 실패 진단·버전·해시·처리 시각',[f'원본: `{cell(data["source_relative_path"])}`',
                    f'처리 시각: {cell(data.get("processed_at"))} (측정 날짜와 별개)',
                    f'[[{assets}/diagnostic.json|원래 오류·상태·단계·해시 JSON]]'])
    atomic_text(path,'\n'.join(text)+'\n');return path


@export_theme
def photo_figure(pair,directory):
    if not pair.get('points') or pair.get('metric_status') not in ('valid','candidate'):return None
    import matplotlib.pyplot as plt
    points=pair['points'];axis=points[0]['axis']
    fig,ax=plt.subplots(figsize=(9,5))
    ax.plot([p['evaluation_voltage_v'] for p in points],[p['signed_delta_id_a'] for p in points],color=palette(1)[0],label='signed ΔId = Id(light) − Id(dark)')
    format_axes(ax,axis,'Signed current difference, ΔId (A)')
    ax.axhline(0,color='gray',linestyle='--');ax.legend(fontsize=8)
    context=pair.get('presentation_conditions','동일 원래 조건 dark/light')
    import textwrap
    context='\n'.join(textwrap.wrap(context,width=70,break_long_words=False))
    ax.set_title(context+'\n광응답 후보 · 원래 조건·이력 비교 규칙 통과 (검증 전)',fontsize=9)
    fig.tight_layout();name='note_photo_signed_delta.png';fig.savefig(directory/name,dpi=EXPORT_DPI);plt.close(fig);return name


def photo_note(pairs, assets, directory, exclusions=None, date_pending=0):
    eligible=[p for p in pairs if p.get('metric_status') in ('valid','candidate') and p.get('points')]
    # The saved pair order is retained; no largest response or nicest curve selection.
    pair=next(iter(eligible),next(iter(pairs),{}));figure=photo_figure(pair,directory)
    available=bool(eligible)
    text=['# Dark/light 비교 검토','','## ① 연구 질문','',QUESTIONS['photo'],'',
          '## ② 조건 한 줄','',pair.get('presentation_conditions','비교 조건 미확인 · 소자·측정 날짜·광 조건·고정 전압·원래 sweep·방향·블록·delay 확인 필요'),'',
          '## ③ 현재 판단','', '**'+('곡선 열람 가능 · 비교 지표 참고 후보'+(' · 일부 지표 보류' if any(p.get('responsivity_a_per_w') is None for p in pair.get('points',[])) else '') if available else '조건 확인 필요 · 일부 지표 보류')+'**','',
          (f'원래 조건·이력의 비교 규칙을 통과한 데이터 {len(eligible)}쌍의 저장된 전류 차이를 열람할 수 있습니다. 이 값은 검증 전 후보이며 광응답의 물리적 원인을 확정하지 않습니다.' if available else
           '동일 조건의 유효한 dark/light 짝을 확인하지 못해 전류 차이의 정량 판단을 보류합니다. 제외된 조합은 조건별 개수로 요약했습니다.'),'',
          '## ④ 대표 근거 그림','']
    if figure:text += [f'![[{assets}/{figure}|640]]',f'[[{assets}/{figure}|원본 해상도로 보기]]','',
                       '동일 원래 조건에서 light 전류에서 dark 전류를 뺀 signed ΔId를 그렸습니다.',
                       '0 위·아래에서 전류 차이의 부호를 확인하세요. Δ|Id|와 signed ΔId는 서로 다른 정의이며, 광파워가 미확인이면 감응도는 추출하지 않습니다.']
    else:text+=['짝 조건이 확인되지 않아 전류 차이 그림을 생성하지 않았습니다. 원래 ±20 V와 ±40 V는 공통 구간을 잘라도 동일 조건이 아닙니다.']
    text+=['','대표 선택: 저장된 비교 순서에서 비교 규칙을 통과한 첫 짝, 동률이면 원본 순서. 최대 응답으로 고르지 않습니다.',
           f'개별 곡선: {cell(pair.get("dark_group_id"))} ↔ {cell(pair.get("light_group_id"))}','',
           '## ⑤ 핵심 수치 (최대 3개)','']
    if available:
        point=min(pair['points'],key=lambda p:abs(p['evaluation_voltage_v']))
        v=number(point['evaluation_voltage_v'],'V');axis=point['axis'].capitalize()
        text+=['대표 평가점: 원본 dark 측정 좌표 중 0 V에 가장 가까운 점 (동률이면 획득 순서).','',
               '| 항목 | 값·단위 | 평가 조건 | 상태 |','|---|---|---|---|',
               f'| signed ΔId | {number(point["signed_delta_id_a"],"A")} | {axis}={v} · 대표 짝 | 참고 후보 · 검증 전 |',
               fr'| Δ\|Id\| | {number(point["delta_abs_id_a"],"A")} | {axis}={v} · 대표 짝 | 참고 후보 · 검증 전 |']
        if point.get('responsivity_a_per_w') is not None:
            text.append(f'| signed 감응도 | {number(point["responsivity_a_per_w"],"A/W")} | {axis}={v} · 확인된 광파워 | 참고 후보 · 검증 전 |')
        else:text+=['','감응도: 추출하지 않음 · 입사 광파워 미확인.']
    else:text+=['정량 수치 보류 · 유효하게 짝지어진 데이터가 없습니다.']
    text+=['','## ⑥ 의미와 한계','',
           '측정에서 관측한 것: '+('같은 평가 전압에서 두 저장 곡선의 전류 차이입니다.' if available else '비교 조건의 확인이 부족합니다.'),
           '모델로 추정한 것: 이 비교 노트에서는 모델 피팅이나 Rs를 추출하지 않았습니다.',
           '아직 확인되지 않은 해석: 전류 차이만으로 광전도·접촉 변화·가열 등의 원인을 분리하지 않았습니다.','',
           '## ⑦ 다음 확인 한 가지','',
           ('현재 비교 지표는 검증 전 후보입니다. 두 원본 노트의 원본 셀과 광 조사 기록에서 동일 전압·극성·조사 상태를 대조하고, 확인 출처를 실험 기록에 남기세요.' if available else
            '같은 소자의 원래 sweep·고정 전압·방향·delay·hold·이력을 두 원본 노트에서 대조하고, 미확인 항목을 GUI의 ‘메타데이터 검토’에 기록하세요.'),
           '', '## ⑧ 접힌 상세 정보','']
    counts=['명백히 다른 소자·원래 조건은 개별 조합을 길게 나열하지 않습니다. 제외 개수는 각 조합의 첫 차단 이유로 분류하며 비교 규칙은 완화하지 않았습니다.',
            f'다른 날짜 비교: 사용자 선택 대기 {date_pending}개 곡선 조합. CLI preview-photo --dark <원본 상대경로> --light <원본 상대경로>로 직접 선택하세요.']
    counts += [f'- {label}: {n}개 곡선 조합' for label,n in sorted((exclusions or {}).items())]
    for p in pairs[:5]:counts += [f'- [[{p["dark_note"]}|dark]] ↔ [[{p["light_note"]}|light]] / {cell(p.get("dark_group_id"))} ↔ {cell(p.get("light_group_id"))} · '+('참고 후보 · 검증 전' if p['metric_status']=='candidate' else '비교 보류')]
    for p in pairs[:5]:
        if p.get('cross_date_explicitly_selected'):
            counts.append(f'다른 날짜를 사용자가 선택했습니다: {cell(p.get("measurement_date_dark"))} ↔ {cell(p.get("measurement_date_light"))}; 각 원본 노트의 hold/pre-bias/반복 이력과 경과 시간을 대조하세요. 날짜 선택은 이력 동일성을 확정하지 않습니다.')
    counts += [f'전체 저장 비교 {len(pairs)}쌍. 원래 조건·이력·날짜 차이와 보류 사유는 아래 JSON에 보존했습니다.',
               f'[[{assets}/comparison.json|전체 조건·검토 사유·원본 셀·내부 상태 JSON]]',f'[[{assets}/photoresponse.csv|전체 광응답 지표 CSV · 정밀값·단위]]']
    text+=fold('비교 후보 5개 이내·제외 이유별 개수·전체 근거',counts)
    return '\n'.join(text)+'\n'
