from dataclasses import dataclass, asdict
import time
import numpy as np
from .imaging import letterbox, load_rgb, components_and_fill, shape_metrics, overlap, restore, refined_mask, fit_mask


@dataclass(frozen=True)
class Parameters:
    threshold: float=.5
    opening: bool=False
    closing: bool=False
    largest: bool=True
    fill: bool=True
    gaussian: bool=False
    refine: bool=False


class Pipeline:
    def __init__(self, backend):
        self.backend=backend;self.cached=None;self.sequence=0

    def run(self, path, parameters=Parameters(), version=0, ground_truth=None):
        tick=time.perf_counter();p=self.backend.package;path=str(path)
        # File identity includes mtime/size, to avoid caching a replaced image.
        from pathlib import Path
        stat=Path(path).stat();key=(path,stat.st_mtime_ns,stat.st_size,parameters.gaussian,p.meta['model_id'])
        cached=self.cached is not None and self.cached['key']==key
        self.sequence+=1
        if not cached:
            rgb=load_rgb(path);input_rgb,g=letterbox(rgb,p.meta['input_size'])
            it=time.perf_counter();logits,processed=self.backend.infer(input_rgb,parameters.gaussian)
            inference=time.perf_counter()-it
            self.cached={'key':key,'rgb':rgb,'geometry':g,'input':input_rgb,'processed':processed,
                         'logits':logits,'inference_ms':inference*1000}
        c=self.cached;g=c['geometry'];valid=g.valid();post_tick=time.perf_counter()
        mask=self.backend.postprocess(c['logits'],parameters.threshold,valid,parameters.opening,parameters.closing)
        mask,flags=components_and_fill(mask,valid,parameters.largest,parameters.fill)
        original_mask=restore(mask,g);accuracy=None
        if parameters.refine:
            scale=p.tensors['head']['scale'] if np.issubdtype(c['logits'].dtype,np.integer) else 1.
            original_mask,flags=refined_mask(c['logits'],g,parameters.threshold,scale,
                parameters.opening,parameters.closing,parameters.largest,parameters.fill)
        metric_mask=fit_mask(original_mask,g) if parameters.refine else mask
        sums=self.backend.moments(metric_mask);metrics=shape_metrics(metric_mask,valid,sums)
        metrics['coordinate_space']='network_letterbox'
        metrics['source']='final_mask_resampled' if parameters.refine else 'network_mask'
        metrics['final_area_original_px2']=int(original_mask.sum())
        metrics['final_area_ratio']=float(original_mask.mean())
        post_ms=(time.perf_counter()-post_tick)*1000
        if ground_truth is not None:
            from PIL import Image
            with Image.open(ground_truth) as im:gt=np.asarray(im.convert('L'))>0
            accuracy=overlap(original_mask,gt)
        return {'frame_id':self.sequence,'parameter_version':version,'model_id':p.meta['model_id'],
                'backend':self.backend.name,'path':path,'parameters':asdict(parameters),
                'hardware_id':getattr(self.backend,'hardware_id',None),
                'rgb':c['rgb'],'processed':c['processed'],'mask':mask,'original_mask':original_mask,
                'geometry':g,'metrics':metrics,'flags':flags,'accuracy':accuracy,
                'timing':{'inference_ms':0. if cached else c['inference_ms'],'cached_inference_ms':c['inference_ms'],
                          'network_reused':cached,'postprocess_ms':post_ms,
                          'processing_ms':(time.perf_counter()-tick)*1000}}

    def reset(self):self.cached=None
