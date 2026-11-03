"""Read-only model ablation on the previously identified failure, with 2018 labels."""
import io
from pathlib import Path
import sys
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'software'))
import numpy as np
from PIL import Image,ImageDraw
from lesion_fpga.common import ROOT,read_json,write_json
from lesion_fpga.quantization import ModelPackage,threshold_code
from lesion_fpga.backends import NativeBackend
from lesion_fpga.imaging import letterbox,morphology,components_and_fill,restore,overlap,overlay

out=ROOT/'artifacts/isic2018';m=read_json(out/'manifest.json')
row=next(r for r in m['rows'] if r['id']=='ISIC_0001186')
with zipfile.ZipFile(m['images_zip']) as z,Image.open(io.BytesIO(z.read(row['image']))) as im:rgb=np.asarray(im.convert('RGB'))
with zipfile.ZipFile(m['masks_zip']) as z,Image.open(io.BytesIO(z.read(row['mask']))) as im:truth=np.asarray(im.convert('L'))>0
package=ModelPackage(ROOT/'artifacts/release/artifacts/models/baseline')
backend=NativeBackend(package,ROOT/'build/native/lesion.dll')
x,g=letterbox(rgb);q,_=backend.infer(x,False);valid=g.valid()
raw=(q>=threshold_code(.45,package.tensors['head']['scale']))&valid
opened=morphology(raw,True,False);closed=morphology(opened,False,True)
largest,_=components_and_fill(closed,valid,True,False)
filled,_=components_and_fill(largest,valid,False,True)
stages=[('threshold .50',(q>=0)&valid),('threshold .45',raw),('opening',opened),('closing',closed),('largest',largest),('fill',filled)]
records=[];canvas=Image.new('RGB',(256*4,280*2));draw=ImageDraw.Draw(canvas)
panels=[('Original',rgb),('Ground truth',overlay(rgb,truth))]
for label,mask in stages:
    restored=restore(mask,g);record=dict(stage=label,**overlap(restored,truth));records.append(record)
    panels.append((label+' Dice '+format(record['dice'],'.3f'),overlay(rgb,restored)))
for i,(label,panel) in enumerate(panels):
    x=i%4*256;y=i//4*280;draw.text((x+6,y+4),label,fill='white');canvas.paste(Image.fromarray(letterbox(panel,256)[0]),(x,y+24))
canvas.save(out/'postprocess_ablation.png')
write_json(out/'postprocess_ablation.json',dict(id=row['id'],ground_truth='ISIC2018',stages=records))
print(records)
