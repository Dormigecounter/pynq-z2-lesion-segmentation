"""First PYNQ-Z2 test: explicit FPGA mode, no HDMI startup or system changes."""
import argparse
from datetime import datetime
import hashlib
import importlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'software'))


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def write(path,value):Path(path).write_text(json.dumps(value,indent=2,ensure_ascii=False),encoding='utf-8')
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_files():
    manifest=read(ROOT/'kit_manifest.json')
    for name,expected in manifest['files'].items():
        if digest(ROOT/name)!=expected:raise RuntimeError('File checksum mismatch: '+name)
    print('FILE_CHECK_PASS',len(manifest['files']),flush=True)
    return manifest


def service(name):
    p=subprocess.run(['systemctl','show',name,'--property=ActiveState','--value'],capture_output=True,text=True)
    return p.stdout.strip() if p.returncode==0 else 'not-found'


def preflight():
    verify_files()
    if platform.system()!='Linux' or not platform.machine().startswith('arm'):
        raise RuntimeError('Run this command on the PYNQ-Z2 Linux console, not Windows')
    versions={}
    for name in ['numpy','cv2','PIL','pynq']:
        module=importlib.import_module(name);versions[name]=getattr(module,'__version__','unknown')
    mem={}
    for line in Path('/proc/meminfo').read_text().splitlines():
        k,v=line.split(':',1)
        if k in {'MemAvailable','MemTotal','CmaFree','CmaTotal'}:mem[k]=int(v.strip().split()[0])
    states={name:service(name) for name in ['bootpy.service','lesion-fpga.service']}
    print(json.dumps(dict(python=sys.executable,versions=versions,memory_kib=mem,services=states),indent=2),flush=True)
    if os.environ.get('XILINX_XRT')!='/usr':raise RuntimeError('Source board_env.sh first: XILINX_XRT must be /usr')
    if states['bootpy.service']=='activating':raise RuntimeError('Boot initialization is still running. Wait and repeat preflight.')
    if states['lesion-fpga.service'] in {'active','activating','deactivating','reloading'}:
        raise RuntimeError('Old lesion-fpga.service is running. Stop it manually before testing.')
    if mem.get('MemAvailable',0)<128*1024:raise RuntimeError('Less than 128 MiB available RAM; stop and inspect memory usage.')
    if 'CmaFree' in mem and mem['CmaFree']<8*1024:raise RuntimeError('Less than 8 MiB free CMA; stop and inspect allocations.')
    print('PREFLIGHT_PASS (no bitstream loaded)',flush=True)
    return dict(versions=versions,memory_kib=mem,services=states)


def run(count,native_library=None):
    info=preflight() if native_library is None else {'desktop_reference_only':True}
    if native_library is not None:verify_files()
    if native_library is None and os.geteuid()!=0:raise RuntimeError('FPGA run requires sudo; see the guide.')
    import numpy as np
    from PIL import Image
    from lesion_fpga.quantization import ModelPackage
    from lesion_fpga.backends import PynqBackend,NativeBackend
    from lesion_fpga.pipeline import Pipeline,Parameters
    from lesion_fpga.imaging import overlap,overlay
    from lesion_fpga.ui import render
    model=ROOT/'artifacts/models/isic2018';package=ModelPackage(model);policy=read(model/'policy.json')
    if policy['model_id']!=package.meta['model_id'] or policy['limited']:raise RuntimeError('Invalid policy')
    params=Parameters(gaussian=package.meta['gaussian'],**policy['parameters'])
    stamp=datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    folder=ROOT/'results'/stamp;folder.mkdir(parents=True,exist_ok=False)
    report=dict(backend='native-cpp-reference' if native_library else 'fpga-int8',
                model_id=package.meta['model_id'],environment=info,cases=[],passed=False)
    backend=None
    try:
        print('LOADING_KNOWN_OVERLAY (volatile PL configuration only)',flush=True)
        backend=NativeBackend(package,native_library) if native_library else PynqBackend(package,ROOT/'hardware/lesion.bit')
        report['hardware_id']=getattr(backend,'hardware_id',None)
        pipeline=Pipeline(backend)
        for case in read(ROOT/'cases.json')[:count]:
            with np.load(ROOT/case['reference']) as data:
                values,_=backend.infer(data['input_rgb'],False,True)
                differences={k:int(np.count_nonzero(values[k]!=data['trace_'+k])) for k in values}
                r=pipeline.run(ROOT/case['image'],params,ground_truth=ROOT/case['truth'])
                prepared_equal=bool(np.array_equal(pipeline.cached['input'],data['input_rgb']))
                network_equal=bool(np.array_equal(r['mask'],data['network_mask']))
                delta=int(np.count_nonzero(r['original_mask']!=data['original_mask']))
                mask_iou=overlap(r['original_mask'],data['original_mask'])['iou']
            target=folder/case['name'];target.mkdir()
            Image.fromarray(r['original_mask']*255).save(target/'mask.png')
            Image.fromarray(overlay(r['rgb'],r['original_mask'])).save(target/'overlay.png')
            Image.fromarray(render(r,'Board first test / '+backend.name,params)).save(target/'screen.png')
            row=dict(name=case['name'],layer_different_elements=differences,input_equal=prepared_equal,
                     network_mask_equal=network_equal,final_mask_different_pixels=delta,final_mask_reference_iou=mask_iou,
                     ground_truth_accuracy=r['accuracy'],timing=r['timing'],
                     passed=bool(not any(differences.values()) and prepared_equal and network_equal and delta==0))
            report['cases'].append(row)
            write(folder/'report.json',report)
            print('CASE_PASS' if row['passed'] else 'CASE_DIFFERENCE',case['name'],json.dumps(row),flush=True)
        report['passed']=bool(report['cases'] and all(r['passed'] for r in report['cases']))
    except Exception as exc:
        report['error']=type(exc).__name__+': '+str(exc)
        print('TEST_FAILED',report['error'],flush=True)
        if isinstance(exc,TimeoutError):print('Do not retry after timeout. Save logs, shut down safely, and investigate.',flush=True)
    finally:
        if backend is not None:backend.close()
        write(folder/'report.json',report)
        write(ROOT/'last_run.json',dict(directory=str(folder.relative_to(ROOT))))
    print('ALL_PASS' if report['passed'] else 'NOT_PASSED',folder,flush=True)
    return 0 if report['passed'] else 1


def export_last():
    latest=read(ROOT/'last_run.json');folder=(ROOT/latest['directory']).resolve()
    if not folder.is_relative_to((ROOT/'results').resolve()):raise RuntimeError('Invalid result path')
    report=read(folder/'report.json')
    if report['backend']!='fpga-int8':raise RuntimeError('Refusing to export desktop results as board results')
    target=subprocess.check_output(['findmnt','-n','-o','TARGET','--target','/boot'],text=True).strip()
    fstype=subprocess.check_output(['findmnt','-n','-o','FSTYPE','--target','/boot'],text=True).strip()
    if target!='/boot' or fstype not in {'vfat','fat','msdos'}:raise RuntimeError('/boot is not a separate FAT boot partition. Stop and inspect lsblk.')
    if shutil.disk_usage('/boot').free<10*1024*1024:raise RuntimeError('Not enough free space on boot partition')
    dest=Path('/boot')/('pynq_result_'+folder.name+'.zip')
    with zipfile.ZipFile(dest,'x',compression=zipfile.ZIP_DEFLATED) as archive:
        for file in folder.rglob('*'):
            if file.is_file():archive.write(file,str(file.relative_to(folder)))
    os.sync()
    print('RESULT_EXPORTED',dest,flush=True)
    print('Next: sudo shutdown -h now; wait for halt, switch OFF, then remove the card.',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--preflight',action='store_true');g.add_argument('--run',action='store_true');g.add_argument('--export-last',action='store_true')
    p.add_argument('--count',type=int,choices=[1,3],default=1)
    p.add_argument('--native-library',help='Explicit desktop test only; never automatic fallback')
    a=p.parse_args()
    if a.preflight:preflight()
    elif a.export_last:export_last()
    else:sys.exit(run(a.count,a.native_library))
