"""Reproducible ZIP audit and warm-start training; never overwrites baseline."""
import argparse
import hashlib
import io
import json
import random
import time
import zipfile
from collections import Counter
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'software'))
import cv2
import numpy as np
from PIL import Image
import torch
from torch.nn import functional as F
from lesion_fpga.common import ROOT, read_json, write_json, sha256
from lesion_fpga.imaging import letterbox, fit_mask
from lesion_fpga.model import SmallUNet
from lesion_fpga.train import loss_fn

OUT = ROOT/'artifacts/isic2018'
SEED = 20261026


def prepare(images_zip, masks_zip):
    OUT.mkdir(parents=True, exist_ok=True)
    old = read_json(ROOT/'artifacts/data_manifest.json')['rows']
    old_ids = {r['id']: r['split'] for r in old}
    old_hash = {r['pixel_sha256']: r['split'] for r in old}
    rows, images, masks, valids = [], [], [], []
    with zipfile.ZipFile(images_zip) as iz, zipfile.ZipFile(masks_zip) as mz:
        ins = {Path(n).stem:n for n in iz.namelist() if n.lower().endswith('.jpg') and not n.startswith('__MACOSX/')}
        gts = {Path(n).stem.lower().removesuffix('_segmentation'):n for n in mz.namelist() if n.lower().endswith('.png') and not n.startswith('__MACOSX/')}
        if set(k.lower() for k in ins) != set(gts):
            raise ValueError('Unpaired image/mask ZIP entries')
        for ident, name in sorted(ins.items()):
            raw = iz.read(name)
            with Image.open(io.BytesIO(raw)) as im:
                # Reject orientation ambiguity rather than rotate only one side.
                if im.getexif().get(274, 1) != 1:
                    raise ValueError('Nontrivial EXIF requires paired orientation audit: '+ident)
                rgb = np.asarray(im.convert('RGB'))
            mask_raw = mz.read(gts[ident.lower()])
            with Image.open(io.BytesIO(mask_raw)) as im:
                gt = np.asarray(im.convert('L'))
            if gt.shape != rgb.shape[:2] or not set(np.unique(gt)).issubset({0,255}):
                raise ValueError('Invalid mask: '+ident)
            digest = hashlib.sha256(rgb.tobytes()).hexdigest()
            prior = {old_ids.get(ident), old_hash.get(digest)} - {None}
            split = ('excluded_legacy_test' if prior & {'test','excluded_overlap'} else
                     'train' if prior else 'new')
            small, g = letterbox(rgb, 128)
            rows.append(dict(id=ident, image=name, mask=gts[ident.lower()], split=split,
                             pixel_sha256=digest, sha256=hashlib.sha256(raw).hexdigest(),
                             mask_sha256=hashlib.sha256(mask_raw).hexdigest(),
                             width=rgb.shape[1], height=rgb.shape[0],
                             foreground_ratio=float((gt>0).mean()), legacy_overlap=bool(prior)))
            images.append(small.transpose(2,0,1)); masks.append(fit_mask(gt,g)[None]); valids.append(g.valid()[None])
            if len(rows)%100 == 0: print('audit',len(rows),flush=True)
    groups = {}
    for r in rows: groups.setdefault(r['pixel_sha256'],[]).append(r)
    fresh = sorted(k for k,v in groups.items() if all(r['split']=='new' for r in v))
    random.Random(SEED).shuffle(fresh)
    n=max(1,round(len(fresh)*.15))
    assignment={k:('validation' if i<n else 'test' if i<2*n else 'train') for i,k in enumerate(fresh)}
    for digest, group in groups.items():
        existing={r['split'] for r in group}
        split='excluded_legacy_test' if 'excluded_legacy_test' in existing else 'train' if 'train' in existing else assignment[digest]
        for r in group:r['split']=split
    manifest=dict(schema_version=1,seed=SEED,rows=rows,counts=dict(Counter(r['split'] for r in rows)),
                  images_zip=str(Path(images_zip).resolve()), masks_zip=str(Path(masks_zip).resolve()),
                  grouping='ISIC ID and exact decoded pixels; patient identity unavailable; near duplicates not ruled out',
                  validation_note='Only IDs/pixels unseen in the entire legacy manifest; old test overlap excluded from training',
                  duplicate_groups=[[r['id'] for r in v] for v in groups.values() if len(v)>1])
    np.savez_compressed(OUT/'cache128.npz',images=np.array(images),masks=np.array(masks),valids=np.array(valids),ids=[r['id'] for r in rows])
    write_json(OUT/'manifest.json',manifest)
    holdouts=[r for r in rows if r['split'] in {'validation','test'}]
    training=[r for r in rows if r['split']=='train']
    blocked=[r for r in old if r['split'] in {'test','excluded_overlap'}]
    blocked_ids={r['id'] for r in blocked};blocked_hash={r['pixel_sha256'] for r in blocked}
    checks=dict(new_holdouts_unseen_by_legacy=all(r['id'] not in old_ids and r['pixel_sha256'] not in old_hash for r in holdouts),
        legacy_test_excluded_from_train=all(r['id'] not in blocked_ids and r['pixel_sha256'] not in blocked_hash for r in training),
        unique_ids=len({r['id'] for r in rows})==len(rows),
        pixel_groups_not_split=all(len({r['split'] for r in group})==1 for group in groups.values()))
    write_json(OUT/'split_verification.json',checks)
    if not all(checks.values()):raise ValueError('Dataset isolation failed')
    print(manifest['counts'],flush=True)


def augment(x,y,v):
    # Paired affine transform; nearest labels, bilinear RGB. Never interpolate labels linearly.
    n=x.shape[0];device=x.device
    angle=(torch.rand(n,device=device)-.5)*.5
    scale=.9+.2*torch.rand(n,device=device)
    theta=torch.zeros(n,2,3,device=device)
    theta[:,0,0]=torch.cos(angle)*scale;theta[:,0,1]=-torch.sin(angle)*scale
    theta[:,1,0]=torch.sin(angle)*scale;theta[:,1,1]=torch.cos(angle)*scale
    theta[:,:,2]=(torch.rand(n,2,device=device)-.5)*.1
    grid=F.affine_grid(theta,x.shape,align_corners=False)
    x=F.grid_sample(x,grid,align_corners=False)
    y=F.grid_sample(y,grid,mode='nearest',align_corners=False)
    v=F.grid_sample(v,grid,mode='nearest',align_corners=False)
    if random.random()<.5:x,y,v=(a.flip(-1) for a in (x,y,v))
    if random.random()<.5:x,y,v=(a.flip(-2) for a in (x,y,v))
    gain=.85+.3*torch.rand(n,3,1,1,device=device)
    offset=(torch.rand(n,1,1,1,device=device)-.5)*.08
    return ((x*gain+offset).clamp(0,1)*v),y,v


def evaluate(model, data, indices, device):
    model.eval();scores=[]
    with torch.inference_mode():
        for start in range(0,len(indices),8):
            ix=indices[start:start+8]
            x=torch.from_numpy(data['images'][ix].astype(np.float32)/255).to(device)
            q=model(x).cpu().numpy()[:,0]>=0
            t=data['masks'][ix,0].astype(bool);v=data['valids'][ix,0]
            q=q & v;t=t & v
            inter=(q&t).sum((1,2));den=q.sum((1,2))+t.sum((1,2))
            scores.extend(np.divide(2*inter,den,out=np.ones_like(den,dtype=float),where=den>0).tolist())
    return dict(dice=float(np.mean(scores)),low_dice_count=int(np.sum(np.array(scores)<.5)),count=len(scores))


def train(epochs, threads):
    random.seed(SEED);np.random.seed(SEED);torch.manual_seed(SEED);torch.set_num_threads(threads)
    device=torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    manifest=read_json(OUT/'manifest.json')
    with np.load(OUT/'cache128.npz') as z:data={k:z[k] for k in z.files}
    if data['ids'].tolist()!=[r['id'] for r in manifest['rows']]:raise ValueError('Cache/manifest order mismatch')
    train_idx=np.array([i for i,r in enumerate(manifest['rows']) if r['split']=='train'])
    val_idx=np.array([i for i,r in enumerate(manifest['rows']) if r['split']=='validation'])
    package=ROOT/'artifacts/release/artifacts/models/baseline'
    meta=read_json(package/'model.json');model=SmallUNet(meta['channels']).to(device)
    if sha256(package/'fp32.npz')!=meta['fp32_sha256']:raise ValueError('Baseline checksum mismatch')
    with np.load(package/'fp32.npz') as w:
        model.load_state_dict({'layers.'+k:torch.from_numpy(w[k]) for k in w.files})
    checkpoint_dir=OUT/'checkpoints';checkpoint_dir.mkdir(exist_ok=True)
    baseline=evaluate(model,data,val_idx,device);print('baseline validation',baseline,flush=True)
    cfg=read_json(ROOT/'configs/default.json');cfg['seed']=SEED;cfg['train'].update(epochs=epochs,learning_rate=.0001,threads=threads,patience=5)
    opt=torch.optim.Adam(model.parameters(),lr=.0001)
    best=baseline['dice'];stale=0;history=[]
    def snapshot(epoch):
        return dict(model={k:v.detach().cpu().clone() for k,v in model.state_dict().items()},config=cfg,
                    epoch=epoch,best=best,limited_training=False,manifest_sha256=sha256(OUT/'manifest.json'),
                    initialized_from=meta['model_id'],optimizer=opt.state_dict())
    torch.save(snapshot(-1),checkpoint_dir/'best.pt')
    for epoch in range(epochs):
        tick=time.perf_counter();model.train();order=np.random.permutation(train_idx);losses=[]
        for start in range(0,len(order),8):
            ix=order[start:start+8]
            x,y,v=(torch.from_numpy(data[k][ix].astype(np.float32)).to(device) for k in ['images','masks','valids'])
            x,y,v=augment(x/255,y,v)
            opt.zero_grad(set_to_none=True);loss=loss_fn(model(x),y,v)
            loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),5);opt.step();losses.append(loss.item())
        score=evaluate(model,data,val_idx,device);improved=score['dice']>best
        stale=0 if improved else stale+1;best=max(best,score['dice'])
        if improved:torch.save(snapshot(epoch),checkpoint_dir/'best.pt')
        torch.save(snapshot(epoch),checkpoint_dir/'last.pt')
        row=dict(epoch=epoch+1,loss=float(np.mean(losses)),validation=score,best=best,seconds=time.perf_counter()-tick)
        history.append(row);print(json.dumps(row),flush=True)
        write_json(OUT/'training.json',dict(baseline_validation=baseline,history=history,device=str(device),
                  status='running',manifest_sha256=sha256(OUT/'manifest.json')))
        if stale>=5:break
    report=read_json(OUT/'training.json');report['status']='complete';write_json(OUT/'training.json',report)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','train'])
    p.add_argument('--images-zip');p.add_argument('--masks-zip');p.add_argument('--epochs',type=int,default=20)
    p.add_argument('--threads',type=int,default=8);a=p.parse_args()
    if a.action=='prepare':
        if not a.images_zip or not a.masks_zip:p.error('prepare requires both ZIP paths')
        prepare(a.images_zip,a.masks_zip)
    else:train(a.epochs,a.threads)
