from dataclasses import replace
from types import SimpleNamespace
import numpy as np
from PIL import Image
from lesion_fpga.pipeline import Pipeline,Parameters
from lesion_fpga.imaging import moments
from lesion_fpga.ui import hit_button,render

class CountingBackend:
    name='test'
    def __init__(self):self.package=SimpleNamespace(meta={'model_id':'test','input_size':16});self.calls=0
    def infer(self,rgb,gaussian):self.calls+=1;return np.zeros((16,16),np.int8),rgb
    def postprocess(self,logits,threshold,valid,opening,closing):return valid.astype(np.uint8) if threshold<=.5 else np.zeros_like(valid,np.uint8)
    def moments(self,mask):return moments(mask)

def test_parameter_updates_reuse_network_and_clear_empty(tmp_path):
    path=tmp_path/'image.jpg';Image.fromarray(np.zeros((30,40,3),np.uint8)).save(path)
    b=CountingBackend();p=Pipeline(b);r=p.run(path,Parameters(),1)
    r2=p.run(path,replace(Parameters(),threshold=.9),2)
    assert b.calls==1 and r2['timing']['network_reused'] and r2['metrics']['area_px2']==0
    assert r2['frame_id']>r['frame_id'] and r2['parameter_version']==2 and r2['accuracy'] is None
    p.reset();p.run(path);assert b.calls==2
    assert render(r,'test',Parameters()).shape==(720,1280,3)
    assert hit_button(30,670)=='prev' and hit_button(0,0) is None


def test_refined_pipeline_uses_signed_logits_and_final_area(tmp_path):
    path=tmp_path/'image.jpg';Image.fromarray(np.zeros((60,90,3),np.uint8)).save(path)
    b=CountingBackend();b.package.tensors={'head':{'scale':.25}}
    def infer(rgb,gaussian):
        q=np.full((16,16),-8,np.int8);q[6:10,3:6]=8
        return q,rgb
    b.infer=infer
    result=Pipeline(b).run(path,Parameters(refine=True,largest=False,fill=False))
    assert 0<result['original_mask'].mean()<.2
    assert result['metrics']['final_area_original_px2']==int(result['original_mask'].sum())
    assert result['metrics']['source']=='final_mask_resampled'
    from lesion_fpga.app import save_result
    folder=save_result(result,tmp_path/'saved')
    np.testing.assert_array_equal(np.asarray(Image.open(folder/'mask.png')),result['original_mask']*255)
