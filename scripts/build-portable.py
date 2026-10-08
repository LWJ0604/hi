"""Build a clean portable Windows release from an existing Python runtime.

This script downloads nothing and never copies active configuration or QA data.
Pass --runtime and --site-packages for a previously installed, trusted Python 3.12.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from research_automation import __version__,code_fingerprint
from research_automation.config import DEFAULT

EXCLUDED={'.git','.venv','.agents','.codex','downloads','__pycache__','qa-layout','qa-runtime',
          'config.json','config.local.json','gui-startup-smoke.json','analysis','vault','state',
          'logs','backups','data_inbox','build','dist'}
IGNORE=shutil.ignore_patterns('__pycache__','*.pyc','*.sqlite3','*.sqlite','*.db','.env*','*.egg-info')

def archive(directory,target):
    if target.exists():raise FileExistsError(target)
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=1) as z:
        for p in sorted(directory.rglob('*')):
            if p.is_file():z.write(p,p.relative_to(directory.parent).as_posix())
    return {'name':target.name,'size_bytes':target.stat().st_size,
            'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--site-packages',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--source-commit',required=True)
    parser.add_argument('--measurement-profile',type=Path,help='현재 사용자가 확인한 단위 프로필. Windows 로컬 QA 설정에만 적용')
    parser.add_argument('--electrode-pair',help='현재 사용자가 선택한 전극쌍 키. Windows 로컬 QA 설정에만 적용')
    args=parser.parse_args()
    if not (args.runtime/'python.exe').is_file():parser.error('Windows Python runtime missing')
    if not args.site_packages.is_dir():parser.error('site-packages missing')
    if args.output.resolve().is_relative_to(ROOT):parser.error('output must be outside the source checkout')
    args.output.mkdir(parents=True,exist_ok=True)
    name=f'research-automation-windows-v{__version__}';bundle=args.output/name
    bundle.mkdir(exist_ok=False)
    for p in ROOT.iterdir():
        if p.name in EXCLUDED or p.name.startswith('.env') or p.name.endswith('.egg-info'):continue
        if p.is_dir():shutil.copytree(p,bundle/p.name,ignore=IGNORE)
        else:shutil.copy2(p,bundle/p.name)
    runtime=bundle/'runtime'
    shutil.copytree(args.runtime,runtime,ignore=IGNORE)
    site=runtime/'Lib/site-packages'
    shutil.copytree(args.site_packages,site,dirs_exist_ok=True,ignore=IGNORE)
    # Editable install metadata points at the developer checkout. The source in
    # the release root is imported directly and does not need these files.
    for p in site.iterdir():
        if p.name.startswith('__editable__') or p.name.startswith('research_automation-'):
            if not p.resolve().is_relative_to(bundle.resolve()):raise ValueError('unsafe metadata path')
            if p.is_dir():shutil.rmtree(p)
            else:p.unlink()
    config=copy.deepcopy(DEFAULT)
    config['paths']={k:'qa-runtime/'+v for k,v in config['paths'].items()}
    if args.measurement_profile:
        profile=json.loads(args.measurement_profile.read_text(encoding='utf-8'))
        if set(profile)!=set(DEFAULT['measurement_profile']) or profile['confirmed'] is not True or profile['voltage_unit']!='V' or profile['current_unit']!='A' or not isinstance(profile['source'],str) or not profile['source'].strip():
            raise ValueError('사용자 확인 V/A 단위 프로필을 지정하세요.')
        config['measurement_profile']=profile
    if args.electrode_pair:config['benchmark']['electrode_pair']=args.electrode_pair
    (bundle/'qa-config.json').write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
    launcher='@echo off\r\nsetlocal\r\ncd /d "%~dp0"\r\nset "TCL_LIBRARY=runtime/tcl/tcl8.6"\r\nset "TK_LIBRARY=runtime/tcl/tk8.6"\r\n"%~dp0runtime\\python.exe" -c "from research_automation.config import Config; Config(\'qa-config.json\').ensure_dirs()"\r\nif errorlevel 1 exit /b 1\r\n"%~dp0runtime\\pythonw.exe" -m research_automation.gui --config "%~dp0qa-config.json" %*\r\nexit /b %errorlevel%\r\n'
    (bundle/'Start-Local-QA.cmd').write_bytes(launcher.encode('ascii'))
    tests='@echo off\r\nsetlocal\r\ncd /d "%~dp0"\r\nset "TCL_LIBRARY=runtime/tcl/tcl8.6"\r\nset "TK_LIBRARY=runtime/tcl/tk8.6"\r\n"%~dp0runtime\\python.exe" -m unittest discover -s tests -v\r\npause\r\n'
    (bundle/'Run-Local-Tests.cmd').write_bytes(tests.encode('ascii'))
    manifest={'source_commit':args.source_commit,'application_version':__version__,
              'code_sha256':code_fingerprint(),'report_format':'fet-template-report-1','template_version':'1.0.0+hi.1',
              'metric_storage_schema':3,'actual_user_data_included':False}
    manifest['observation_report_format']='branch-observations-1.0'
    manifest['benchmark_report_format']='basic-parameters-1'
    manifest['current_user_units_confirmed']=bool(args.measurement_profile)
    manifest['local_source_modified']=args.source_commit=='local-uncommitted'
    (bundle/'release-build.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    source=args.output/f'research-automation-source-v{__version__}';source.mkdir(exist_ok=False)
    for p in bundle.iterdir():
        if p.name=='runtime':continue
        if p.is_dir():shutil.copytree(p,source/p.name)
        else:shutil.copy2(p,source/p.name)
    generic=copy.deepcopy(config);generic['measurement_profile']=copy.deepcopy(DEFAULT['measurement_profile']);generic['benchmark']['electrode_pair']=None
    (source/'qa-config.json').write_text(json.dumps(generic,ensure_ascii=False,indent=2),encoding='utf-8')
    source_manifest=copy.deepcopy(manifest);source_manifest['current_user_units_confirmed']=False
    (source/'release-build.json').write_text(json.dumps(source_manifest,indent=2),encoding='utf-8')
    results=[archive(bundle,args.output/(name+'.zip')),archive(source,args.output/(source.name+'.zip'))]
    (args.output/'SHA256SUMS.txt').write_text(''.join(r['sha256']+'  '+r['name']+'\n' for r in results),encoding='utf-8')
    (args.output/'release-artifacts.json').write_text(json.dumps({'build':manifest,'artifacts':results},indent=2),encoding='utf-8')
    print(json.dumps(results,indent=2))

if __name__=='__main__':main()
