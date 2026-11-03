"""Publish a separate candidate bundle only after saved validation/test gates pass."""
from pathlib import Path
import shutil
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'software'))
from lesion_fpga.common import ROOT,read_json,write_json,sha256

out=ROOT/'artifacts/isic2018';model=ROOT/'artifacts/models/isic2018'
meta=read_json(model/'model.json');policy=read_json(out/'policy_int8.json')
validation=read_json(out/'evaluation_validation_int8.json');test=read_json(out/'evaluation_test_int8.json')
verification=read_json(out/'export_verification.json')
if not all(read_json(out/'split_verification.json').values()):raise ValueError('Dataset isolation failed')
if policy['checkpoint_sha256']!=meta['checkpoint_sha256'] or verification['model_id']!=meta['model_id']:
    raise ValueError('Model/provenance mismatch')
for report in [validation,test]:
    if report['policy']['checkpoint_sha256']!=meta['checkpoint_sha256'] or report['policy']['manifest_sha256']!=sha256(out/'manifest.json'):
        raise ValueError('Evaluation/model/manifest mismatch')
if not (validation['quantization_gate_pass'] and test['quantization_gate_pass'] and verification['passed']):
    raise ValueError('Quantization/consistency gate failed; candidate not packaged')
if test['improved']['dice']<=test['baseline']['dice'] or test['improved']['boundary_iou_512']<=test['baseline']['boundary_iou_512']:
    raise ValueError('No measured improvement in both region and boundary; candidate not packaged')
write_json(model/'policy.json',dict(policy,model_id=meta['model_id']))
bundle=out/'deployment';bundle.mkdir(exist_ok=True)
shutil.copytree(ROOT/'software/lesion_fpga',bundle/'software/lesion_fpga',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
shutil.copytree(model,bundle/'artifacts/models/isic2018',dirs_exist_ok=True)
shutil.copytree(out/'demo',bundle/'data/demo',dirs_exist_ok=True)
shutil.copy2(ROOT/'pyproject.toml',bundle/'pyproject.toml')
readme='''# ISIC2018 candidate deployment

This bundle preserves the existing bitstream and old release. It has passed desktop
evaluation, not a new physical PYNQ board acceptance test.

On PYNQ, copy this directory to a NEW folder. Use the existing compatible bit/hwh
and hardware_manifest.json together. From this directory:

```bash
export PYTHONPATH="$PWD/software"
sudo -E python3 -m lesion_fpga.app --backend fpga --model artifacts/models/isic2018 --images data/demo --bitstream /absolute/path/to/existing/hdmi_full/lesion.bit
```

The bitstream path is a placeholder: replace it with the actual existing board path.
Final score interpolation runs on ARM. Check memory and latency on large images
before accepting this candidate. Shape metrics use the network coordinate grid;
saved masks and final area ratio use original image coordinates.
'''
(bundle/'README.md').write_text(readme,encoding='utf-8')
files={str(p.relative_to(bundle)).replace('\\','/'):sha256(p) for p in bundle.rglob('*') if p.is_file() and p.name!='bundle_manifest.json'}
write_json(bundle/'bundle_manifest.json',dict(model_id=meta['model_id'],board_validated=False,files=files,
    validation_report_sha256=sha256(out/'evaluation_validation_int8.json'),test_report_sha256=sha256(out/'evaluation_test_int8.json')))
shutil.make_archive(str(out/'deployment'),'zip',bundle)
lines=['# ISIC2018 改进实测结果','',f"模型 ID：`{meta['model_id']}`。第 {meta['training_epoch']} 轮最佳权重；同结构 128×128 SmallUNet，旧权重微调。",'',
       '数据：2594 对，训练 1819、验证 217、内部留出测试 217、旧测试重叠排除 341。无患者标识，不能宣称患者级独立。','',
       '| 集合 / 指标 | 旧 INT8 + 旧策略 | 新 INT8 + 冻结策略 |','|---|---:|---:|']
for label,report in [('验证',validation),('留出测试',test)]:
    for key,title in [('dice','Dice'),('iou','IoU'),('boundary_iou_512','边界 IoU (512)'),('low_dice_count','Dice < 0.5 张数'),('zero_dice_count','Dice = 0 张数')]:
        a=report['baseline'][key];b=report['improved'][key]
        lines.append(f'| {label} / {title} | {a:.4f} | {b:.4f} |' if isinstance(a,float) else f'| {label} / {title} | {a} | {b} |')
lines += ['', 'Dice/IoU 在原图尺寸计算。边界 IoU 在最大边 512 的统一网格上，以 2 像素内边界带计算；不能直接与其他容差定义的文献指标比较。', '',
          '冻结策略：阈值 '+str(policy['parameters']['threshold'])+'；参数见 `policy_int8.json`。训练/后处理选择只使用训练和验证集，测试结果未反馈调参。', '',
          '验证集与测试集的平均 FP32→INT8 Dice/IoU 降幅均通过 0.01 门槛。一张验证图的 25 张量 C++/NumPy 整数对照逐元素一致。', '',
          '交付：`deployment.zip` 为独立候选部署包，`deployment/README.md` 为板端命令；旧发布包和 bitstream 未覆盖。', '',
          '未做本轮实际板卡验收。原图细化在 ARM/CPU 执行，超大图内存和延迟需要上板复测。部分困难样本仍分割失败，不能宣称全部修复。']
regression=out/'failure_regression.json'
if regression.exists():
    reg=read_json(regression)
    if reg.get('model_id')==meta['model_id']:
        lines+=['',f"旧失败样本 {reg['id']} 的独立回归：Dice {reg['baseline']['dice']:.3f} → {reg['improved']['dice']:.3f}，见 `failure_before_after.png`；该图属于旧测试排除集合。"]
(out/'结果摘要.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(bundle)
