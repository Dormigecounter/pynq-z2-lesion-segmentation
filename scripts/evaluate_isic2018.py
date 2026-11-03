"""Validation-selected postprocessing and locked held-out comparison at original resolution."""
import argparse
import io
import itertools
import json
from pathlib import Path
import sys
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'software'))
import cv2
import numpy as np
from PIL import Image, ImageDraw
import torch
from lesion_fpga.common import ROOT, read_json, write_json, sha256
from lesion_fpga.model import SmallUNet
from lesion_fpga.imaging import (Geometry, overlap, restore, restore_scores, morphology, letterbox,
    components_and_fill, overlay)
from lesion_fpga.quantization import ModelPackage, IntegerBackend
from lesion_fpga.backends import NativeBackend

OUT=ROOT/'artifacts/isic2018'


def summary(rows):
    return dict(count=len(rows),dice=float(np.mean([r['dice'] for r in rows])),
        iou=float(np.mean([r['iou'] for r in rows])),
        boundary_iou_512=float(np.mean([r['boundary_iou_512'] for r in rows])),
        low_dice_count=sum(r['dice']<.5 for r in rows),zero_dice_count=sum(r['dice']==0 for r in rows))


def boundary(mask):
    h,w=mask.shape;ratio=512/max(h,w)
    m=cv2.resize(mask.astype(np.uint8),(max(1,round(w*ratio)),max(1,round(h*ratio))),interpolation=cv2.INTER_NEAREST)
    # Fixed 2 pixels on a maximum-512 evaluation grid; explicitly not original-pixel boundary IoU.
    return m & ~cv2.erode(m,np.ones((5,5),np.uint8),borderType=cv2.BORDER_CONSTANT,borderValue=0)


def score(pred,truth,truth_boundary):
    return dict(**overlap(pred,truth),boundary_iou_512=overlap(boundary(pred),truth_boundary)['iou'])


def predict(model,x):
    with torch.inference_mode():return model(torch.from_numpy(x.astype(np.float32)/255)).numpy()[:,0]


def make_mask(logits,g,policy,restored=None):
    cutoff=np.log(policy['threshold']/(1-policy['threshold']))
    if policy['refine']:
        m=((restore_scores(logits,g) if restored is None else restored)>=cutoff).astype(np.uint8)
        m=morphology(m,policy['opening'],policy['closing'])
        return components_and_fill(m,np.ones(m.shape,bool),policy['largest'],policy['fill'])[0]
    m=morphology((logits>=cutoff)&g.valid(),policy['opening'],policy['closing'])
    m=components_and_fill(m,g.valid(),policy['largest'],policy['fill'])[0]
    return restore(m,g)


def main(split,quantized=False):
    torch.set_num_threads(8)
    manifest=read_json(OUT/'manifest.json');checkpoint=OUT/'checkpoints/best.pt'
    state=torch.load(checkpoint,map_location='cpu',weights_only=False)
    if state['manifest_sha256']!=sha256(OUT/'manifest.json'):raise ValueError('Training manifest changed')
    improved=SmallUNet(state['config']['channels']);improved.load_state_dict(state['model']);improved.eval()
    base_dir=ROOT/'artifacts/release/artifacts/models/baseline'
    baseline=SmallUNet(state['config']['channels'])
    with np.load(base_dir/'fp32.npz') as z:baseline.load_state_dict({'layers.'+k:torch.from_numpy(z[k]) for k in z.files})
    baseline.eval()
    with np.load(OUT/'cache128.npz') as z:
        if z['ids'].tolist()!=[r['id'] for r in manifest['rows']]:raise ValueError('Cache/manifest order mismatch')
        images=z['images']
    indices=[i for i,r in enumerate(manifest['rows']) if r['split']==split]
    old_policy=dict(read_json(base_dir/'policy.json')['parameters'],refine=False)
    policy_file=OUT/('policy_int8.json' if quantized else 'policy_fp32.json')
    if split=='validation':
        candidates=[dict(threshold=t,opening=False,closing=False,largest=l,fill=f,refine=True)
                    for t,l,f in itertools.product([.4,.5,.6],[False,True],[False,True])]
        candidates.append(old_policy)
    else:
        frozen=read_json(policy_file)
        if frozen['checkpoint_sha256']!=sha256(checkpoint) or frozen['manifest_sha256']!=sha256(OUT/'manifest.json'):
            raise ValueError('Frozen policy/checkpoint/manifest mismatch')
        candidates=[frozen['parameters']]
    qbackend=None;qbaseline=None
    if quantized:
        package=ModelPackage(ROOT/'artifacts/models/isic2018')
        if package.meta['checkpoint_sha256']!=sha256(checkpoint):raise ValueError('INT8/checkpoint mismatch')
        library=ROOT/'build/native/lesion.dll'
        qbackend=NativeBackend(package,library) if library.exists() else IntegerBackend(package)
        base_package=ModelPackage(base_dir)
        qbaseline=NativeBackend(base_package,library) if library.exists() else IntegerBackend(base_package)
    rows_by_policy=[[] for _ in candidates];base_rows=[];raw_rows=[];float_rows=[]
    with zipfile.ZipFile(manifest['masks_zip']) as mz,zipfile.ZipFile(manifest['images_zip']) as iz:
        for start in range(0,len(indices),8):
            ix=indices[start:start+8];x=images[ix]
            b=predict(baseline,x);f=predict(improved,x)
            for j,index in enumerate(ix):
                row=manifest['rows'][index];w,h=row['width'],row['height'];r=min(128/w,128/h)
                nw,nh=max(1,round(w*r)),max(1,round(h*r));g=Geometry(w,h,128,nw,nh,(128-nw)//2,(128-nh)//2)
                with Image.open(io.BytesIO(mz.read(row['mask']))) as im:truth=(np.asarray(im.convert('L'))>0)
                tb=boundary(truth)
                base_logits=b[j]
                if qbaseline:
                    base_logits=qbaseline.infer(x[j].transpose(1,2,0),False)[0].astype(np.float32)*qbaseline.package.tensors['head']['scale']
                base=make_mask(base_logits,g,old_policy)
                base_rows.append(dict(id=row['id'],**score(base,truth,tb)))
                logits=f[j]
                if qbackend:
                    logits=qbackend.infer(x[j].transpose(1,2,0),False)[0].astype(np.float32)*qbackend.package.tensors['head']['scale']
                raw=restore(((logits>=0)&g.valid()).astype(np.uint8),g)
                raw_rows.append(dict(id=row['id'],**score(raw,truth,tb)))
                fpraw=restore(((f[j]>=0)&g.valid()).astype(np.uint8),g)
                float_rows.append(dict(id=row['id'],**score(fpraw,truth,tb)))
                restored=restore_scores(logits,g)
                for k,policy in enumerate(candidates):
                    pred=make_mask(logits,g,policy,restored)
                    rows_by_policy[k].append(dict(id=row['id'],**score(pred,truth,tb)))
                if split=='test' and len(base_rows)<=12:
                    image_bytes=iz.read(row['image'])
                    with Image.open(io.BytesIO(image_bytes)) as im:rgb=np.asarray(im.convert('RGB'))
                    demo=OUT/'demo';demo.mkdir(exist_ok=True)
                    (demo/(row['id']+'.jpg')).write_bytes(image_bytes)
                    (demo/(row['id']+'_Segmentation.png')).write_bytes(mz.read(row['mask']))
                    panels=[rgb,overlay(rgb,truth),overlay(rgb,base),overlay(rgb,pred)]
                    preview=np.concatenate([letterbox(a,256)[0] for a in panels],axis=1)
                    folder=OUT/('previews_int8' if quantized else 'previews_fp32');folder.mkdir(exist_ok=True)
                    canvas=Image.new('RGB',(1024,280));canvas.paste(Image.fromarray(preview),(0,24))
                    draw=ImageDraw.Draw(canvas)
                    for k,label in enumerate(['Original','Ground truth','Baseline','Improved']):draw.text((k*256+8,5),label,fill='white')
                    canvas.save(folder/(row['id']+'.png'))
            print(split,'int8' if quantized else 'fp32',min(start+8,len(indices)),'/',len(indices),flush=True)
    summaries=[summary(rows) for rows in rows_by_policy]
    # Selection on validation ONLY: avoid trading more catastrophic failures for a tiny mean gain.
    best=min(range(len(candidates)),key=lambda k:(summaries[k]['zero_dice_count'],summaries[k]['low_dice_count'],-summaries[k]['dice'])) if split=='validation' else 0
    selected=dict(checkpoint_sha256=sha256(checkpoint),manifest_sha256=sha256(OUT/'manifest.json'),
                  parameters=candidates[best],selection='validation: zero Dice count, Dice<0.5 count, then mean original-resolution Dice',
                  backend=qbackend.name if quantized else 'pytorch-fp32',limited=False)
    if split=='validation':write_json(policy_file,selected)
    report=dict(split=split,backend=selected['backend'],baseline=summary(base_rows),improved_raw=summary(raw_rows),
        improved_fp32_raw=summary(float_rows),improved=summary(rows_by_policy[best]),
        policy=selected,alternatives=[dict(parameters=p,metrics=s) for p,s in zip(candidates,summaries)],
        per_image=[dict(id=a['id'],baseline=a,improved=b) for a,b in zip(base_rows,rows_by_policy[best])],
        boundary_note='Inner boundary band: 2 px after resizing mask to max dimension 512; Dice/IoU at original resolution')
    if quantized:
        report['quantization_gate_pass']=all(report['improved_fp32_raw'][k]-report['improved_raw'][k]<=.01 for k in ['dice','iou'])
    write_json(OUT/f'evaluation_{split}_{"int8" if quantized else "fp32"}.json',report)
    print(json.dumps({k:report[k] for k in ['baseline','improved','improved_raw']},indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--split',choices=['validation','test'],required=True)
    p.add_argument('--int8',action='store_true');a=p.parse_args();main(a.split,a.int8)
