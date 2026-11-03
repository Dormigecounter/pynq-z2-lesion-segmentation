"""Check new exported graph against the independent NumPy integer reference."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'software'))
import numpy as np
from lesion_fpga.common import ROOT,read_json,write_json
from lesion_fpga.quantization import ModelPackage,IntegerBackend
from lesion_fpga.backends import NativeBackend

out=ROOT/'artifacts/isic2018';manifest=read_json(out/'manifest.json')
index=next(i for i,r in enumerate(manifest['rows']) if r['split']=='validation')
with np.load(out/'cache128.npz') as z:x=z['images'][index].transpose(1,2,0)
p=ModelPackage(ROOT/'artifacts/models/isic2018')
a,ap=NativeBackend(p,ROOT/'build/native/lesion.dll').infer(x,False,True)
b,bp=IntegerBackend(p).infer(x,False,True)
rows=[dict(tensor=k,different_elements=int(np.count_nonzero(a[k]!=b[k])),
           max_abs=int(np.abs(a[k].astype(np.int32)-b[k].astype(np.int32)).max())) for k in a]
report=dict(model_id=p.meta['model_id'],id=manifest['rows'][index]['id'],layers=rows,
            processed_equal=bool(np.array_equal(ap,bp)),
            passed=bool(np.array_equal(ap,bp) and all(r['different_elements']==0 for r in rows)),
            scope='One validation image, native C++ versus NumPy integer reference; not a board test')
write_json(out/'export_verification.json',report)
print(report)
if not report['passed']:raise SystemExit(1)
