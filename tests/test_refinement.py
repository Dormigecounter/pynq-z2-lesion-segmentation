import numpy as np
import pytest
from lesion_fpga.imaging import letterbox, restore_scores, refined_mask, components_and_fill


@pytest.mark.parametrize('shape',[(57,103),(103,57),(63,63)])
def test_refinement_keeps_off_center_object_and_excludes_padding(shape):
    _,g=letterbox(np.zeros((*shape,3),np.uint8))
    scores=np.full((128,128),100.,np.float32)
    scores[g.valid()]=-10
    x=g.left+g.width//4;y=g.top+g.height//3
    scores[y-3:y+4,x-3:x+4]=10
    result,_=refined_mask(scores,g,.5)
    yy,xx=np.nonzero(result)
    assert result.sum()>0 and result.mean()<.1
    assert abs(xx.mean()/g.original_w-.25)<.05
    assert abs(yy.mean()/g.original_h-1/3)<.05
    assert not result[0].any() and not result[-1].any()


def test_int8_scale_matches_float_and_preserves_small_components():
    _,g=letterbox(np.zeros((256,384,3),np.uint8))
    q=np.full((128,128),-10,np.int8);q[40:42,30:32]=10;q[60:70,70:80]=10
    a,_=refined_mask(q,g,.6,.2)
    b,_=refined_mask(q.astype(np.float32)*.2,g,.6)
    np.testing.assert_array_equal(a,b)
    import cv2
    assert cv2.connectedComponents(a)[0]==3


def test_scores_do_not_wrap_and_threshold_endpoints():
    _,g=letterbox(np.zeros((45,79,3),np.uint8))
    q=np.full((128,128),-10,np.int8)
    assert (restore_scores(q,g)==-10).all()
    assert refined_mask(q,g,0)[0].all()
    assert not refined_mask(q,g,1)[0].any()
    with pytest.raises(ValueError):refined_mask(q,g,1.1)


@pytest.mark.parametrize('largest',[False,True])
@pytest.mark.parametrize('fill',[False,True])
def test_full_image_validity_fast_path_is_exact(largest,fill):
    rng=np.random.default_rng(55)
    for shape in [(1,9),(11,1),(31,47)]:
        for mask in [np.zeros(shape,np.uint8),np.ones(shape,np.uint8),(rng.random(shape)>.5).astype(np.uint8)]:
            expected,flags=components_and_fill(mask,np.ones(shape,bool),largest,fill)
            actual,newflags=components_and_fill(mask,None,largest,fill)
            np.testing.assert_array_equal(actual,expected)
            assert flags==newflags
