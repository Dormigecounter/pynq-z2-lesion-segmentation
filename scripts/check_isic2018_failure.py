"""Regression-only check on the old failure; never feeds policy selection."""
import io
from pathlib import Path
import sys
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'software'))
import numpy as np
from PIL import Image,ImageDraw
from lesion_fpga.common import ROOT,read_json,write_json
from lesion_fpga.quantization import ModelPackage
from lesion_fpga.backends import NativeBackend
from lesion_fpga.pipeline import Pipeline,Parameters
from lesion_fpga.imaging import overlay,letterbox
from lesion_fpga.app import save_result

out=ROOT/'artifacts/isic2018';manifest=read_json(out/'manifest.json')
row=next(r for r in manifest['rows'] if r['id']=='ISIC_0001186')
folder=out/'regression';folder.mkdir(exist_ok=True)
image=folder/(row['id']+'.jpg');truth=folder/(row['id']+'_Segmentation.png')
with zipfile.ZipFile(manifest['images_zip']) as z:image.write_bytes(z.read(row['image']))
with zipfile.ZipFile(manifest['masks_zip']) as z:truth.write_bytes(z.read(row['mask']))
results=[]
for name,model,policy in [('baseline',ROOT/'artifacts/release/artifacts/models/baseline',ROOT/'artifacts/release/artifacts/models/baseline/policy.json'),
                         ('improved',ROOT/'artifacts/models/isic2018',out/'policy_int8.json')]:
    p=ModelPackage(model);backend=NativeBackend(p,ROOT/'build/native/lesion.dll')
    result=Pipeline(backend).run(image,Parameters(**read_json(policy)['parameters']),ground_truth=truth)
    save_result(result,folder/name);results.append(result)
with Image.open(truth) as im:gt=np.asarray(im.convert('L'))>0
rgb=results[0]['rgb'];panels=[rgb,overlay(rgb,gt),overlay(rgb,results[0]['original_mask']),overlay(rgb,results[1]['original_mask'])]
canvas=Image.new('RGB',(1024,280));draw=ImageDraw.Draw(canvas)
labels=['Original','Ground truth','Baseline Dice %.3f'%results[0]['accuracy']['dice'],'Improved Dice %.3f'%results[1]['accuracy']['dice']]
for i,panel in enumerate(panels):
    canvas.paste(Image.fromarray(letterbox(panel,256)[0]),(i*256,24));draw.text((i*256+6,5),labels[i],fill='white')
canvas.save(out/'failure_before_after.png')
report=dict(id=row['id'],model_id=results[1]['model_id'],split=row['split'],policy_frozen_before_check=True,baseline=results[0]['accuracy'],improved=results[1]['accuracy'])
write_json(out/'failure_regression.json',report);print(report)
