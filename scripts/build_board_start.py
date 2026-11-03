"""Prepare a small offline first-test kit without changing any SD card files."""
from pathlib import Path
import shutil
import sys
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'software'))
import numpy as np
from PIL import Image
from lesion_fpga.common import ROOT,read_json,write_json,sha256
from lesion_fpga.imaging import load_rgb,letterbox
from lesion_fpga.quantization import ModelPackage
from lesion_fpga.backends import NativeBackend
from lesion_fpga.pipeline import Pipeline,Parameters

out=ROOT/'artifacts/board_start';kit=out/'pynq_start_20261026'
kit.mkdir(parents=True,exist_ok=False)
shutil.copytree(ROOT/'software/lesion_fpga',kit/'software/lesion_fpga',ignore=shutil.ignore_patterns('__pycache__'))
model=ROOT/'artifacts/models/isic2018'
shutil.copytree(model,kit/'artifacts/models/isic2018')
(kit/'hardware').mkdir()
for name in ['lesion.bit','lesion.hwh','hardware_manifest.json']:
    shutil.copy2(ROOT/'artifacts/hardware/hdmi_full'/name,kit/'hardware'/name)
hardware=read_json(kit/'hardware/hardware_manifest.json')
for name,digest in hardware['files'].items():
    if sha256(kit/'hardware'/name)!=digest:raise ValueError('Hardware checksum mismatch')
shutil.copy2(ROOT/'scripts/board_first_test.py',kit/'board_test.py')
(kit/'board_env.sh').write_text('''# Source from the extracted kit directory; no installation or system writes.
export BOARD_PY=/usr/local/share/pynq-venv/bin/python3
export XILINX_XRT=/usr
export PYTHONPATH="$PWD/software:/home/xilinx/lesion_fpga/.board_deps"
if [ ! -x "$BOARD_PY" ]; then
  echo "STOP: expected PYNQ Python is missing. Do not substitute/install packages blindly."
  return 1
fi
''',encoding='utf-8')
(kit/'samples').mkdir();(kit/'reference').mkdir()
package=ModelPackage(model);backend=NativeBackend(package,ROOT/'build/native/lesion.dll')
params=Parameters(**read_json(model/'policy.json')['parameters']);cases=[]
sources=[('lesion',ROOT/'artifacts/isic2018/demo/ISIC_0006914.jpg'),
         ('previous_failure',ROOT/'artifacts/isic2018/regression/ISIC_0001186.jpg'),
         ('portrait',ROOT/'artifacts/isic2018/demo/ISIC_0006914.jpg')]
for name,source in sources:
    with Image.open(source) as im:rgb=im.convert('RGB');rgb.thumbnail((768,768),Image.Resampling.LANCZOS)
    with Image.open(source.with_name(source.stem+'_Segmentation.png')) as im:gt=im.convert('L').resize(rgb.size,Image.Resampling.NEAREST)
    if name=='portrait':rgb=rgb.transpose(Image.Transpose.ROTATE_90);gt=gt.transpose(Image.Transpose.ROTATE_90)
    image=kit/'samples'/f'{name}.png';truth=kit/'samples'/f'{name}_truth.png'
    rgb.save(image);gt.save(truth)
    pipeline=Pipeline(backend);result=pipeline.run(image,params,ground_truth=truth)
    input_rgb=letterbox(load_rgb(image))[0];traces,_=backend.infer(input_rgb,False,True)
    ref=kit/'reference'/f'{name}.npz'
    np.savez_compressed(ref,input_rgb=input_rgb,network_mask=result['mask'],original_mask=result['original_mask'],
                        **{'trace_'+k:v for k,v in traces.items()})
    cases.append(dict(name=name,image=str(image.relative_to(kit)).replace('\\','/'),truth=str(truth.relative_to(kit)).replace('\\','/'),
                      reference=str(ref.relative_to(kit)).replace('\\','/'),source_id=source.stem,size=list(rgb.size),
                      desktop_accuracy=result['accuracy'],note='Resized board smoke test; not an independent model evaluation sample'))
write_json(kit/'cases.json',cases)
guide=ROOT/'docs/PYNQ-Z2首次上板_仅USB与电脑.md'
if guide.exists():shutil.copy2(guide,kit/'开始前必读.md')
files={str(p.relative_to(kit)).replace('\\','/'):sha256(p) for p in kit.rglob('*') if p.is_file()}
write_json(kit/'kit_manifest.json',dict(model_id=package.meta['model_id'],hardware_id=hardware['hardware_id'],files=files,board_validated=False))
archive=out/'pynq_start_20261026.zip'
with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as z:
    for p in kit.rglob('*'):
        if p.is_file():z.write(p,str(p.relative_to(out)))
(out/'pynq_start_20261026.sha256').write_text(sha256(archive)+'  pynq_start_20261026.zip\n',encoding='ascii')
print(archive,archive.stat().st_size,sha256(archive))
