"""Author the technical report from the supplied anonymous contest template."""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import re
import zipfile

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from PIL import Image, ImageDraw, ImageFont
from lxml import etree

ROOT=Path(__file__).resolve().parents[1]
TMP=ROOT/'artifacts/technical_report_20261103'
REF=Path('C:/Users/33879/Downloads/2658aa94-81d0-454c-b2ac-fc040ff2c01a.docx')
OUTPUT=ROOT/'docs/皮肤病灶分割系统技术报告_20261103.docx'
TEMPLATE_SHA='d15a2aa186f600cb9c234bffd9deff0c4e9b05c569643d8a81d536f66f424f0c'
W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'

def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def sha(data):return hashlib.sha256(data).hexdigest()

if sha(REF.read_bytes())!=TEMPLATE_SHA:raise RuntimeError('Template changed')
if not (TMP/'artifact.md').exists():raise RuntimeError('Missing template contract')
TMP.mkdir(parents=True,exist_ok=True)
test=read(ROOT/'artifacts/isic2018/evaluation_test_int8.json')
val=read(ROOT/'artifacts/isic2018/evaluation_validation_int8.json')
policy=read(ROOT/'artifacts/models/isic2018/policy.json')
meta=read(ROOT/'artifacts/models/isic2018/model.json')
budget=read(ROOT/'artifacts/models/isic2018/model_budget.json')
board_zip=ROOT/'artifacts/board_start/results/pynq_result_20250504_013843_799015.zip'
with zipfile.ZipFile(board_zip) as z:
    board=json.loads(z.read('report.json'))
    (TMP/'board_screen.png').write_bytes(z.read('lesion/screen.png'))
    (TMP/'board_overlay.png').write_bytes(z.read('lesion/overlay.png'))
b=board['cases'][0]
assert board['passed'] and len(board['cases'])==1 and len(b['layer_different_elements'])==25
assert not any(b['layer_different_elements'].values())
assert board['model_id']==meta['model_id']==policy['model_id']

# The images are engineering diagrams, created from the actual module boundaries.
font_path='C:/Windows/Fonts/simsun.ttc'
def diagram(filename,size,boxes,arrows,notes=()):
    im=Image.new('RGB',size,'white');d=ImageDraw.Draw(im)
    font=ImageFont.truetype(font_path,36);small=ImageFont.truetype(font_path,28)
    for box,label in boxes:
        d.rectangle(box,outline='#333333',width=3,fill='#F2F4F7')
        bb=d.multiline_textbbox((0,0),label,font=font,spacing=12,align='center')
        x=(box[0]+box[2]-(bb[2]-bb[0]))/2;y=(box[1]+box[3]-(bb[3]-bb[1]))/2-bb[1]
        d.multiline_text((x,y),label,font=font,fill='black',spacing=12,align='center')
    for a,c in arrows:
        d.line([a,c],fill='#444444',width=5)
        if a[1]==c[1]:
            direction=1 if c[0]>a[0] else -1
            d.polygon([c,(c[0]-18*direction,c[1]-10),(c[0]-18*direction,c[1]+10)],fill='#444444')
        else:d.polygon([c,(c[0]-10,c[1]-18),(c[0]+10,c[1]-18)],fill='#444444')
    for pos,label in notes:d.text(pos,label,font=small,fill='#333333')
    path=TMP/filename;im.save(path);return path

architecture=diagram('architecture.png',(1800,910),[
    ((45,40,525,220),'开发电脑\n数据审计与模型微调'),
    ((660,40,1140,220),'模型包与位流\n权重  描述字  bit/hwh'),
    ((1275,40,1755,220),'MicroSD 与串口\n传输文件  PuTTY 控制'),
    ((45,380,525,595),'ARM 处理系统 PS\n读图  等比缩放与补边\n描述字调度与缓存同步'),
    ((660,380,1140,595),'FPGA 可编程逻辑 PL\nINT8 卷积等网络算子\n基础阈值与形态算子'),
    ((1275,380,1755,595),'ARM 最终后处理\n连续分数恢复  填洞\n指标与图像合成'),
    ((1275,715,1755,875),'结果输出\nPNG 与 JSON 或 HDMI')
], [((525,130),(660,130)),((1140,130),(1275,130)),((1515,220),(1515,300)),
    ((525,487),(660,487)),((1140,487),(1275,487)),((1515,595),(1515,715))],
    [((820,645),'PS 与 PL 共享 DDR 连续内存；控制寄存器通过 AXI 访问'),
     ((55,700),'离线训练在电脑完成；最终推理可在板上执行'),
     ((55,755),'本轮已通过无 HDMI 的单张小图 FPGA 对照')])
# Add the transfer-to-PS path without crossing data-plane arrows.
im=Image.open(architecture);d=ImageDraw.Draw(im);d.line([(1515,300),(285,300),(285,380)],fill='#444444',width=5);d.polygon([(285,380),(275,362),(295,362)],fill='#444444');im.save(architecture)

flow=diagram('pipeline.png',(1800,690),[
    ((25,35,540,190),'load_rgb 与 letterbox\n原图 RGB → 128×128\n保存尺寸与补边位置'),
    ((640,35,1160,190),'backend.infer\nINT8 输入 → 连续 logits'),
    ((1260,35,1775,190),'restore_scores\n裁去补边\n双线性恢复原尺寸'),
    ((1260,350,1775,520),'阈值与连通域处理\n阈值 0.60  填洞\n不强制保留最大区域'),
    ((640,350,1160,520),'指标与可视化\n原图掩膜与面积比例\n合成原图叠加图'),
    ((25,350,540,520),'保存与回归\nPNG  JSON  逐层参考对照')
],[((540,112),(640,112)),((1160,112),(1260,112)),((1515,190),(1515,350)),
   ((1260,435),(1160,435)),((640,435),(540,435))],
    [((40,585),'同一原图坐标下生成最终掩膜、叠加图与保存结果，避免显示补边造成视觉错位')])

doc=Document(REF)
source_paras=[deepcopy(p._p) for p in doc.paragraphs]
sect=deepcopy(doc._element.body.sectPr)
for child in list(doc._element.body):
    if child.tag!=qn('w:sectPr'):doc._element.body.remove(child)

def font_run(run,size=12,bold=False,east='宋体'):
    run.font.name='Times New Roman';run.font.size=Pt(size);run.bold=bold;run.font.color.rgb=RGBColor(0,0,0)
    rpr=run._element.get_or_add_rPr();rf=rpr.find(qn('w:rFonts'))
    if rf is None:rf=OxmlElement('w:rFonts');rpr.insert(0,rf)
    for k in ['asciiTheme','hAnsiTheme','eastAsiaTheme','cstheme']:
        rf.attrib.pop(qn('w:'+k),None)
    rf.set(qn('w:eastAsia'),east);rf.set(qn('w:ascii'),'Times New Roman');rf.set(qn('w:hAnsi'),'Times New Roman')

def paragraph(text='',role='body',page=False):
    source=0 if role=='title' else 5 if role=='part' else 6 if role=='head' else 7
    el=deepcopy(source_paras[source]);
    for child in list(el):
        if child.tag!=qn('w:pPr'):el.remove(child)
    ppr=el.find(qn('w:pPr'))
    for tag in ['numPr','rPr','ind','tabs','pageBreakBefore','keepNext','keepLines']:
        for node in list(ppr.findall(qn('w:'+tag))):ppr.remove(node)
    from docx.text.paragraph import Paragraph
    doc._element.body.insert(len(doc._element.body)-1,el)
    p=Paragraph(el,doc._body);p.paragraph_format.line_spacing=1.5
    p.paragraph_format.space_before=Pt(0);p.paragraph_format.space_after=Pt(6)
    p.paragraph_format.widow_control=True
    if role=='body':
        p.alignment=WD_ALIGN_PARAGRAPH.JUSTIFY;p.paragraph_format.first_line_indent=Pt(24)
    elif role in ['part','head']:
        p.alignment=WD_ALIGN_PARAGRAPH.LEFT;p.paragraph_format.keep_with_next=True
        p.paragraph_format.space_before=Pt(12 if role=='part' else 8)
    elif role=='title':
        if 'Title' not in doc.styles:
            from docx.enum.style import WD_STYLE_TYPE
            doc.styles.add_style('Title',WD_STYLE_TYPE.PARAGRAPH)
        p.style=doc.styles['Title'];p.alignment=WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after=Pt(12)
    elif role in ['caption','date']:
        p.alignment=WD_ALIGN_PARAGRAPH.CENTER;p.paragraph_format.first_line_indent=Pt(0)
        p.paragraph_format.space_after=Pt(6)
    elif role=='ref':
        p.alignment=WD_ALIGN_PARAGRAPH.LEFT;p.paragraph_format.first_line_indent=Pt(-18);p.paragraph_format.left_indent=Pt(18)
    # Let the template's continuous flow paginate naturally; avoid sparse pages.
    r=p.add_run(text);font_run(r,18 if role=='title' else 14 if role=='part' else 10.5 if role in ['caption','date','ref'] else 12,role in ['title','part','head'])
    if role in ['part','head']:
        outline=OxmlElement('w:outlineLvl');outline.set(qn('w:val'),'0' if role=='part' else '1');p._p.get_or_add_pPr().append(outline)
    return p

def heading(text,part=False,page=False):return paragraph(text,'part' if part else 'head',page)
def body(text):return paragraph(text)
def picture(path,caption,width=14.3):
    p=paragraph('','caption');p.paragraph_format.keep_with_next=True
    p.add_run().add_picture(str(path),width=Cm(width))
    paragraph(caption,'caption')

def table(headers,rows,widths=None,caption=None):
    if caption:
        p=paragraph(caption,'caption');p.paragraph_format.keep_with_next=True
    t=doc.add_table(rows=1,cols=len(headers));t.alignment=WD_TABLE_ALIGNMENT.CENTER;t.autofit=False
    if widths is None:widths=[14.65/len(headers)]*len(headers)
    for c,w in zip(t.columns,widths):c.width=Cm(w)
    for i,text in enumerate(headers):t.rows[0].cells[i].text=str(text)
    for row in rows:
        cells=t.add_row().cells
        for i,v in enumerate(row):cells[i].text=str(v)
    borders=OxmlElement('w:tblBorders')
    for name in ['top','left','bottom','right','insideH','insideV']:
        e=OxmlElement('w:'+name);e.set(qn('w:val'),'single');e.set(qn('w:sz'),'4');e.set(qn('w:color'),'D9D9D9');borders.append(e)
    t._tbl.tblPr.append(borders)
    for ri,row in enumerate(t.rows):
        pr=row._tr.get_or_add_trPr();cant=OxmlElement('w:cantSplit');pr.append(cant)
        if ri==0:pr.append(OxmlElement('w:tblHeader'))
        for ci,cell in enumerate(row.cells):
            cell.width=Cm(widths[ci]);cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
            tcpr=cell._tc.get_or_add_tcPr();margin=OxmlElement('w:tcMar')
            for side,val in [('top',70),('bottom',70),('left',90),('right',90)]:
                node=OxmlElement('w:'+side);node.set(qn('w:w'),str(val));node.set(qn('w:type'),'dxa');margin.append(node)
            tcpr.append(margin)
            if ri==0:
                shd=OxmlElement('w:shd');shd.set(qn('w:fill'),'EFEFEF');tcpr.append(shd)
            for p in cell.paragraphs:
                p.paragraph_format.line_spacing=1.15;p.paragraph_format.space_after=Pt(0)
                p.alignment=WD_ALIGN_PARAGRAPH.CENTER if ci>0 or ri==0 else WD_ALIGN_PARAGRAPH.LEFT
                for run in p.runs:font_run(run,10.5,ri==0)
    paragraph('','caption').paragraph_format.space_after=Pt(0)
    return t

def equation(label,numerator,denominator):
    p=paragraph('','caption');math=OxmlElement('m:oMath')
    def run(text):
        r=OxmlElement('m:r');t=OxmlElement('m:t');t.text=text;r.append(t);return r
    math.append(run(label+' = '));frac=OxmlElement('m:f')
    num=OxmlElement('m:num');num.append(run(numerator));den=OxmlElement('m:den');den.append(run(denominator))
    frac.extend([num,den]);math.append(frac);p._p.append(math)

abstract='本作品面向皮肤病灶边界分割与嵌入式可视化实验，构建基于PYNQ-Z2的软硬件协同系统。电脑端完成数据核验、轻量U-Net训练及INT8模型导出，板上ARM处理器负责文件输入、任务调度、原图尺度后处理和结果合成，FPGA执行卷积、池化、上采样等网络算子。针对小病灶被最大连通域误删、低分辨率掩膜直接放大导致阶梯边缘的问题，系统增加连续分数恢复流程，并通过验证集冻结后处理策略。ISIC2018数据经重复与旧测试重叠检查后，划分为1819张训练、217张验证、217张内部留出测试，另排除341张旧测试重叠图像。在相同留出测试集上，旧版与新版INT8系统的平均Dice由0.7783提高至0.8498，IoU由0.6844提高至0.7669，Dice为0的图像由5张降为0张。新版已完成真实FPGA单张缩小图对照，25个张量和最终掩膜与电脑参考逐元素一致，记录的单次网络推理耗时为3.459秒。现有成果支持模型精度与软硬件一致性验证；新版大图内存、HDMI交互和长期稳定性仍需继续验收。本作品用于工程教学与算法研究，不承担临床诊断功能。'
overview=[
('1.1 功能与特性','系统读取RGB皮肤图像，生成病灶二值掩膜、轮廓叠加图、面积比例和形态指标。界面支持切图、阈值调整、开闭运算、填洞、区域筛选、视图切换与结果保存；参数调整可复用已缓存的网络输出。无显示器时，可通过串口运行FPGA测试，将PNG图像和JSON记录保存到存储卡后在电脑查看。系统保留原图与网络图的几何关系，最终掩膜、叠加图和保存结果使用同一原图坐标。'),
('1.2 应用领域','作品适用于FPGA图像处理课程、嵌入式人工智能竞赛、病灶分割算法研究和软硬件协同设计实验。它能够演示从标注数据、模型训练、定点量化到实际板卡推理的完整过程，并为算法替换、边界细化和硬件调度研究提供验证平台。现有评估来自公开皮肤镜数据和内部留出划分，不代表临床有效性或跨医院、跨设备的泛化能力。'),
('1.3 主要技术特点','采用四级编码器和三级解码器的轻量U-Net，通道为16、32、64、128，输入128×128。FPGA与电脑参考共用图结构和描述字，采用有符号INT8数据、INT32累加及Q24重定标。ARM与PL通过连续DDR缓冲区交换数据，并显式执行缓存刷新和失效。最终边界从连续logits恢复，先裁补边再双线性插值，随后阈值化与填洞；验证选择关闭最大域和开闭运算。模型、位流及策略均绑定校验值，支持逐层定位差异。'),
('1.5 主要创新点','①在同一轻量网络及硬件接口下，通过数据隔离、增量微调与策略验证改善小目标失败。②连续分数恢复和统一坐标输出同时减轻阶梯边缘与显示错位。③把逐层整数对照、最终掩膜对照和版本校验纳入部署流程，提高问题定位与复现能力。上述内容为工程实现改进，不宣称提出新的基础网络理论。'),
('1.6 设计流程','需求分解→数据与标注核验→按旧样本重叠关系隔离数据→从旧权重微调→验证集选权重→训练集校准导出INT8→验证集冻结后处理→留出测试→C++与整数参考对照→小图真实FPGA对照→HDMI及稳定性验收。最后两类验收按版本分别留存证据。')]
limits={'摘要':(abstract,800),**{name:(text,400 if name[:3] in ['1.1','1.2','1.3'] else 200) for name,text in overview}}
for key,(value,limit) in limits.items():assert len(value)<=limit,(key,len(value),limit)

paragraph('PYNQ Z2皮肤病灶分割与可视化系统','title')
paragraph('技术报告  2026年11月3日','date')
heading('摘要');body(abstract)
heading('第一部分  作品概述',True)
for title,text in overview[:3]:heading(title);body(text)
heading('1.4 主要性能指标')
table(['项目','已取得指标'],[
('网络输入与数值格式','128×128 RGB；INT8权重/激活，INT32累加'),
('留出测试平均Dice与IoU','0.8498 / 0.7669；217张，电脑INT8参考'),
('真实板端单图网络推理','3459.44 ms；单次小图，无HDMI'),
('计算与显示配置','计算100 MHz；HDMI输出1280×720、60 Hz'),
('整机实现资源','LUT 46.61%；DSP 75.45%；BRAM 17.14%')],[4.3,10.35])
for title,text in overview[3:]:heading(title);body(text)

heading('第二部分  系统组成及功能说明',True,page=True)
heading('2.1 整体介绍')
body('系统由开发电脑、PYNQ-Z2、MicroSD存储和可选的HDMI显示外设构成。开发电脑处理训练与构建任务，部署后网络推理由板上可编程逻辑完成；ARM处理器运行Linux及Python调度程序。训练模型、控制描述字和硬件文件通过存储卡传入板端。输出既可保存为文件，也可经图像合成后送至HDMI。图1给出各模块和数据关系。')
picture(architecture,'图1  系统组成与PS和PL的数据关系')
body('PYNQ中的Overlay用于把位流加载到PL，并由配套HWH描述硬件层次与寄存器；allocate提供CPU与PL均可访问的连续物理内存[4-5]。本系统使用同一个完整Overlay容纳推理IP和视频层，避免显示程序再次加载其他位流而覆盖正在运行的计算逻辑。电脑端C++后端是功能参考，不计入真实FPGA推理成果。')
heading('2.2 硬件系统介绍')
heading('2.2.1 硬件整体介绍')
body('硬件平台为PYNQ-Z2，目标器件为xc7z020clg400-1。PS负责操作系统、存储访问及任务控制，PL承载可复用的计算核心和已有视频层。计算时钟为100 MHz。MicroSD保存Linux系统、应用和模型；PROG UART Micro USB提供串口控制及本轮使用的USB供电。HDMI OUT用于接显示器或采集卡；HDMI IN属于输入链路，首轮静态图像分割测试不使用该接口。')
table(['连接或资源','输入与输出关系','在项目中的作用'],[
('MicroSD','启动文件、图像、模型、结果文件','系统启动及离线文件传输'),
('PROG UART','电脑USB ↔ 板端串口','PuTTY登录和运行命令'),
('PS与PL共享DDR','输入、权重、特征图与描述字','网络各算子的帧存储调度'),
('AXI控制接口','启动、完成、地址及返回值','操作码派发、ABI与超时检查'),
('HDMI OUT','RGB合成帧 → 视频输出','可选720p界面展示'),
('USB HOST','鼠标事件 → ARM界面','可选交互输入')],[3.0,6.1,5.55])
heading('2.2.2 机械设计介绍')
body('作品采用现成开发板及其板载接口，没有自研机壳、支架或运动机构，因此本阶段不涉及机械传动、结构CAD或加工件。集成时保持板底绝缘、接口可接近和散热片周围通风。最终展示装配应固定板卡和线缆，并在断电后调整跳帽；采用USB供电时J9置USB，采用合规外接电源时按板卡说明切换到REG。')
heading('2.2.3 电路各模块介绍')
body('计算核心通过arena和params两块连续内存与PS交互。arena保存CHW排布的图像、权重、特征图和临时掩膜；params保存16个INT32描述字段以及偏置和统计输出。描述字携带算子类型、输入尺寸、通道、卷积核、输入输出偏移和重定标参数。PS写入物理地址后启动IP，轮询完成状态并读取返回值；超时后拒绝继续复用该执行上下文。')
body('卷积模块采用8×8空间分块、8路输入通道和8路输出通道分组，使用3×3或1×1卷积核。片上像素和权重数组按并行维度分割，部分循环以流水线和展开方式实现。池化、最近邻上采样、拼接重定标、阈值、3×3腐蚀/膨胀、RGB预处理和整数矩统计共享同一操作码接口。该实现属于逐算子帧存储调度，不应描述为整网像素流一拍一像素。')
body('已有完整位流包含PS、AXI互连、计算IP和HDMI视频层。PS的控制访问经AXI-Lite寄存器完成，IP的数据访问经AXI主接口进入DDR。视频层从合成帧缓冲区读取RGB数据并输出HDMI。当前设计未修改开发板原有PCB，也未制作新的模拟采集或传感电路。HDMI输入侧的三条既有异步复位CDC提示仍需在未来启用输入链路时专项验证。')

heading('2.3 软件系统介绍')
heading('2.3.1 软件整体介绍')
body('软件分为电脑开发工具、板端应用和验证工具。电脑端包含数据清单、训练缓存、微调脚本、量化导出和留出评估；板端应用复用同一Python流水线，按后端选择本地整数参考、C++参考或PYNQ FPGA。界面以Pillow合成四宫格，显示原图、预处理图、最终掩膜和叠加图，同时提供阈值与后处理开关。运行结果以图像和JSON留存，便于离线复核。')
picture(ROOT/'artifacts/isic2018/ui_snapshot.png','图2  新版电脑端应用快照  同一原图坐标显示掩膜与叠加图')
heading('2.3.2 软件各模块介绍')
body('输入层由load_rgb、letterbox和Geometry组成。load_rgb读取RGB并处理图像方向；letterbox在保持长宽比的前提下缩放到128×128画布，以黑色补边；Geometry保存原图尺寸、缩放后宽高以及左右和上下偏移。训练标签使用最近邻缩放，图像使用双线性缩放，有效域标记用于屏蔽补边损失。图3给出单次推理的主要函数与关键变量。')
picture(flow,'图3  单次推理与最终结果的处理流程')
body('模型模块采用U-Net编码器—解码器及跳跃连接思想[1]。四级编码通道为16、32、64、128，每级包含两次3×3卷积与ReLU，前三级后接2×2最大池化；三级解码依次最近邻放大、拼接相应编码特征并执行双卷积，最后用1×1卷积输出单通道logits。模型没有BN或Dropout，便于统一训练图、整数参考图和硬件描述图。')
table(['阶段','空间尺寸','主要通道与操作'],[
('输入','128×128','RGB 3通道'),('编码0','128×128','16；双卷积'),('编码1','64×64','32；双卷积'),
('编码2','32×32','64；双卷积'),('编码3','16×16','128；双卷积'),('解码2至0','32→64→128','上采样、跳跃拼接、双卷积'),('输出','128×128','1×1卷积，单通道logits')],[3.0,3.7,7.95])
body('数据模块直接读取ISIC2018图像和Task 1分割标注压缩包[2]，检查图像与标签尺寸、二值取值和方向，并计算ISIC编号与解码像素散列。与旧测试集重叠的341张图像排除出本轮训练；新验证与新留出测试仅从旧清单未出现的编号和像素组划分。划分种子为20261026。由于没有患者标识，现有隔离不等于患者级独立，也不能排除所有近重复内容。')
body('训练模块从旧发布包FP32权重初始化同结构网络，使用Adam、学习率0.0001、批量8、最多20轮和5轮未提升早停。采用有效域BCE与Dice损失联合优化，加入图像和标签同步的翻转、仿射旋转、缩放和平移，以及图像颜色增益和亮度扰动。RGB用双线性采样，标签与有效域用最近邻采样。第18轮权重在验证集上取得最佳网络尺度分数，保存为本次导出检查点。')
body('量化模块使用训练集随机选取的256张样本校准张量范围，导出有符号对称INT8权重与激活、INT32偏置及累加、Q24乘法重定标参数。舍入采用半值远离零，溢出按输出数值范围饱和。模型包包含arena.bin、params.bin、model.json和冻结策略；model.json记录图节点、张量地址、比例因子和文件散列。FP32文件用于电脑参考，不要求板端安装PyTorch。')
body('执行层通过ArenaBackend调度各描述字。NativeBackend调用同源C++ DLL；PynqBackend加载bit/hwh后分配连续缓冲区，核对硬件清单与ABI，设置物理地址，并依次执行节点。CPU写入在启动前flush，PL写入在CPU读取或再次flush前invalidate，防止旧缓存覆盖硬件结果。只有明确指定FPGA后端才执行板端逻辑，发生错误时不自动切换到CPU以伪装成功。')
body('最终后处理先把INT8 logits按比例恢复到连续数值，裁去网络画布补边，再双线性插值到原图尺寸。概率阈值0.60转换为对应logit阈值后生成掩膜，随后填洞；不启用开闭运算，不强制保留最大连通域。全图有效时省去额外有效域大数组，并在连通域标签使用完毕后释放内存。这一ARM处理路径与旧网络尺寸二值输出分开保留，便于回归。')
body('统计与界面层从最终原图掩膜计算面积像素数与面积比例。周长、主轴、次轴和不对称度仍在128×128网络坐标中计算，细化模式先把最终掩膜映射回该坐标，界面明确标注net px，不能把这些数值直接当作原图像素或毫米。非空、贴边和组件数量作为辅助标志，不能代替分割准确率。')
body('缓存层以路径、修改时间、文件大小、预处理开关和模型ID识别网络输出。阈值、填洞或显示参数调整通常不重跑网络。异步界面为每次请求设置版本号，拒绝显示过期结果；输入变化或异常时清空旧结果。保存函数输出最终mask.png、overlay.png和参数绑定的result.json，保证显示、保存和评估能够追溯到同一图像及策略。')

heading('第三部分  完成情况及性能参数',True,page=True)
heading('3.1 整体介绍')
body('目前已形成“数据—模型—整数导出—软硬件执行—结果回收”的工程链路。旧模型版本的完整HDMI位流曾有板端ABI、首帧、界面自动检查和启动顺序记录；新模型版本新增217张留出评估和一张实际FPGA小图对照。两类证据属于不同模型和测试范围，不能把旧版HDMI验收直接算作新版整机验收。当前系统使用现成开发板集成，没有定制整机机械外壳。')
heading('3.2 工程成果')
heading('3.2.1 机械成果')
body('本作品没有独立机械加工成果。硬件以开发板和既有散热片为基础，首轮测试采用MicroSD和PROG UART串口连接。最终展示仍需完成线缆固定与供电条件检查，并补录整机连接状态的现场照片；本报告中的软件截图不替代整机实物或供电测量证据。')
heading('3.2.2 电路成果')
body('已归档完整推理加HDMI位流及HWH硬件描述，硬件ID为abe0c39aea79af7e。计算核心源文件、生成RTL快照、HLS脚本和Vivado集成脚本均有对应目录。新模型保持原有输入形状、图操作和内存偏移，使用该位流完成了真实板端对照，因此本次权重改进未重新综合电路。表1给出此完整位流的布线后资源与时序记录。')
table(['指标','实现记录','说明'],[
('LUT','24795 / 53200  46.61%','包含视频层的完整设计'),('寄存器','36617 / 106400  34.41%','布线后实现报告'),
('Block RAM Tile','24 / 140  17.14%','器件资源占用'),('DSP','166 / 220  75.45%','含卷积乘加计算'),
('计算时钟','100 MHz','clk_fpga_0周期10 ns'),('全设计WNS / WHS','+0.222 ns / +0.017 ns','该版时序约束满足')],[3.5,5.1,6.05],'表1  现有完整位流的资源和时序')
body('该资源表来自hdmi_full中的实际Vivado报告，而不是模型参数预算。模型调度arena约5008640字节，权重区486592字节，特征张量预算4374528字节，单次网络约667942912次乘加；这些是存储与运算预算，不等于实际峰值DDR占用、带宽、功耗或速度。')
heading('3.2.3 软件成果')
body('已提供新版FP32及INT8模型、冻结后处理、训练和评估脚本、统一应用界面、独立部署ZIP及首测套件。新版应用快照显示原图、掩膜和叠加结果采用相同比例；保存准确率与评估脚本的同图结果一致。首测包包含横向、纵向及既往失败类型的缩小图和逐层参考，可在无显示器情况下运行，结果经FAT启动分区导出后在电脑查看。')
picture(ROOT/'artifacts/isic2018/failure_before_after.png','图4  既往失败样本的回归  从左至右为原图 标注 旧版与新版')
body('在ISIC_0001186上，旧模型和旧策略的Dice为0，新模型加冻结策略的Dice为0.9439。逐项消融发现，旧阈值及开闭处理后仍有约0.55的Dice，但最大域筛选保留了较大误检区域，使Dice降为0。该图属于旧测试重叠排除集合，没有参与本轮训练或新策略选择；此处作为独立回归案例，不计入217张新留出测试平均值。')
heading('3.3 特性成果')
heading('3.3.1 数据隔离与精度结果')
body('ISIC2018共核验2594对图像及二值标注，其中1819张用于训练、217张用于验证、217张用于内部留出测试，341张旧测试重叠样本排除。基线与新版在相同留出图像及原图尺寸上比较，报告的是逐图指标的平均值。该内部测试划分不是ISIC官方隐藏测试集，也不用于证明临床有效性。')
equation('Dice','2|P ∩ G|','|P| + |G|')
equation('IoU','|P ∩ G|','|P ∪ G|')
body('其中P为预测前景像素集合，G为标注前景。边界IoU借鉴边界评价思想[3]，在本项目中先把掩膜最大边缩放至512，再取2像素内边界带计算交并比。该容差定义与文献中的其他尺度设置不一定相同，因此只作本工程同条件比较。')
metrics=[('平均Dice','dice'),('平均IoU','iou'),('边界IoU 512尺度','boundary_iou_512'),('Dice小于0.5的张数','low_dice_count'),('Dice等于0的张数','zero_dice_count')]
rows=[]
for name,key in metrics:
    a=test['baseline'][key];c=test['improved'][key]
    rows.append((name,f'{a:.4f}' if isinstance(a,float) else str(a),f'{c:.4f}' if isinstance(c,float) else str(c)))
table(['指标','旧INT8及旧策略','新INT8及冻结策略'],rows,[5.8,4.4,4.45],'表2  217张内部留出测试结果')
body('新版平均Dice提高0.0715，即约7.15个百分点；平均IoU提高约8.25个百分点。Dice为0的样本由5张降为0张，但仍有11张Dice低于0.5，说明困难样本问题尚未全部解决。改进同时包含训练与后处理变化，不能把整项平均提升全部归因于某一个单独模块。')
body('验证集在相同原图口径下，旧版与新版平均Dice分别为0.7787和0.8394。策略以验证集的Dice为0张数、Dice低于0.5张数和平均Dice依次筛选，冻结为阈值0.60、填洞及连续分数恢复，关闭最大域和开闭运算。留出测试在冻结后执行，没有把测试结果反馈用于调参。校准仅使用训练图像；验证和测试中平均FP32到INT8的Dice及IoU降幅均不超过0.01。')
heading('3.3.2 真实FPGA单图对照')
body('已回收的板端结果包使用fpga-int8后端，模型ID为e71034b765f1de21，硬件ID为abe0c39aea79af7e，包含一张缩小的lesion案例。25个网络张量的不同元素数均为0，预处理输入、网络掩膜和最终原图掩膜均与电脑参考一致；最终掩膜与参考IoU为1.0。该案例对人工标注的Dice为0.9060、IoU为0.8282，不应把它当成整套数据的板端平均准确率。')
picture(TMP/'board_screen.png','图5  从真实FPGA结果包回收的单图应用快照  未启动HDMI输出')
table(['板端记录项','单次结果','统计口径'],[
('网络推理','3459.44 ms','一次Pipeline调用，无HDMI'),('后处理与形态统计','204.49 ms','包含原图细化等CPU操作'),
('流水线处理','3942.00 ms','含读图与预处理，不含截图与导出'),('网络张量不同元素','25个张量均为0','包括输入及各图节点输出'),
('最终掩膜不同像素','0','与电脑参考逐像素对照'),('可用内存 / 空闲CMA','338016 / 39368 KiB','运行前状态，不是峰值测量')],[4.0,4.6,6.05],'表3  新版单张小图的真实板端记录')
body('结果包内环境为PYNQ 3.1.1、NumPy 1.21.5、OpenCV 4.5.4、Pillow 9.0.1。其文件名包含20250504，属于板上系统时钟值，不能据此判定真实实验日期。上述计时只来自一次案例，且测试脚本另有逐层参考采集开销，不构成100帧统计、吞吐率或加速比。720p60只表示显示输出格式，不表示每秒60次分割。')
heading('3.3.3 回归与部署检查')
body('现有桌面26项测试通过，涵盖几何恢复、形态学、边界、定点舍入、原生C++算子、缓存、显示和保存一致性。新版在一张验证图上完成C++和独立NumPy整数参考逐层一致性检查；首测包的三张缩小图在电脑C++后端全部通过，但当前回收的真实FPGA包仅含一张案例。ZIP结构、文件散列和应用快照与评估一致性也已核对。')
body('首测流程保留原有MicroSD系统，在独立目录解包，不改BOOT.BIN、image.ub或QSPI。预检核验模型和位流散列、剩余内存、CMA和旧服务状态；只有明确选择FPGA后端后才加载已知位流。串口采用115200、8N1和无流控。结果以新文件导出到FAT启动分区，执行Linux关机后再断电取卡，降低误刷卡与文件系统损坏风险。')
heading('3.3.4 完成边界与后续验收')
table(['内容','目前证据','下一步'],[
('新模型留出精度','217张电脑INT8评估完成','保留划分，补充独立来源验证'),
('新模型FPGA正确性','真实单张小图逐层与掩膜一致','完成三图及更多样本回归'),
('新版HDMI与鼠标','旧版有历史记录；新版未完整验收','现场确认画面、点击和输入拔插'),
('原始大图与内存','现有768边长首测；大图峰值未测','逐级增大图像，记录内存与延迟'),
('性能与稳定性','仅有单次小图计时','100次统计、超时恢复和冷启动'),
('功耗与临床应用','没有相应验收证据','仪器测量；不作临床承诺')],[3.2,6.0,5.45],'表4  各版本的验证范围')
body('本报告关键数值可追溯到evaluation_test_int8.json、evaluation_validation_int8.json、model_budget.json，完整位流的utilization.rpt与timing_summary.rpt，以及回收的pynq_result_20250504_013843_799015.zip内report.json。旧版显示与自动启动记录来自record/section7_20260930。机器状态标志尚未集中更新到同一清单，验收时应优先核对模型ID、硬件ID和实际报告内容，避免沿用过期的完成标志。')

heading('第四部分  总结',True,page=True)
extensions='后续优先完成新版三图及多图板端回归、HDMI交互、100次性能和内存峰值测试，再调整自启动。算法方面可在固定数据隔离下比较更高输入分辨率、局部二次分割和原图引导的边缘细化；硬件方面可评估片上特征复用、算子融合和DDR访问优化。任何结构或数值格式变更均需重新导出并验证软件、RTL与板端一致性。扩展目标应以实测收益与PYNQ-Z2资源约束共同决定。'
reflection='本项目的关键经验是把分割错误、坐标映射、后处理与硬件计算分别验证。画面中病灶区域偏离，既可能是模型识别失败，也可能是最大连通域规则删除了正确的小目标。对ISIC_0001186逐项消融后，才能确认最大域筛选把尚有重叠的结果变成了完全错误；仅调整显示坐标或加大平滑核无法解决这类问题。边缘方面，低分辨率二值掩膜放大会放大网格结构，保留连续分数到恢复尺寸之后再阈值化，才能在统一坐标下改善轮廓。\n数据管理同样影响结论。新数据包含旧编号和旧像素，直接混合随机划分会夸大泛化效果。工程因此把旧测试重叠样本排除出训练，把权重和后处理选择限制在验证集，并保留独立留出测试。固定模型ID、校验文件和逐层张量，使电脑端平均精度与板端正确性可以分别复现。\n实际部署表明，bitstream能够加载只是开始。缓存同步、连续内存、旧服务抢占、依赖版本与安全关机都决定系统是否可靠。真实单图结果已证明新版模型能在现有PL计算核心上执行，但单次计时不能替代长期统计，旧版HDMI记录也不能替代新版验收。后续工作应围绕未完成的验收项逐条补充证据。'
assert len(extensions)<=300 and len(reflection)<=1000
heading('4.1 可扩展之处');body(extensions)
heading('4.2 心得体会')
for text in reflection.split('\n'):body(text)

heading('第五部分  参考文献',True)
references=[
'[1] RONNEBERGER O, FISCHER P, BROX T. U-Net: Convolutional Networks for Biomedical Image Segmentation[EB/OL]. 2015[2026-11-03]. https://arxiv.org/abs/1505.04597.',
'[2] CODELLA N, ROTEMBERG V, TSCHANDL P, et al. Skin Lesion Analysis Toward Melanoma Detection 2018: A Challenge Hosted by the International Skin Imaging Collaboration (ISIC)[EB/OL]. 2019[2026-11-03]. https://arxiv.org/abs/1902.03368.',
'[3] CHENG B, GIRSHICK R, DOLLÁR P, et al. Boundary IoU: Improving Object-Centric Image Segmentation Evaluation[EB/OL]. 2021[2026-11-03]. https://arxiv.org/abs/2103.16562.',
'[4] PYNQ. Overlay[EB/OL]. PYNQ 3.1 Documentation[2026-11-03]. https://pynq.readthedocs.io/en/v3.1/pynq_libraries/overlay.html.',
'[5] XILINX PYNQ. PS/PL Interfaces[EB/OL]. [2026-11-03]. https://github.com/Xilinx/PYNQ/blob/master/docs/source/overlay_design_methodology/pspl_interface.rst.'
]
for text in references:paragraph(text,'ref')

# Keep source layout and parts byte-for-byte except the explicitly editable body,
# relationship/media additions and append-only Title role.
doc.core_properties.title='PYNQ Z2皮肤病灶分割与可视化系统技术报告'
intermediate=TMP/'working.docx';doc.save(intermediate)
ns={'w':W}
with zipfile.ZipFile(REF) as original,zipfile.ZipFile(intermediate) as generated:
    src_parts={n:original.read(n) for n in original.namelist() if not n.endswith('/')}
    gen_parts={n:generated.read(n) for n in generated.namelist() if not n.endswith('/')}
    src_doc=etree.fromstring(src_parts['word/document.xml']);new_doc=etree.fromstring(gen_parts['word/document.xml'])
    orig_sect=src_doc.find('w:body/w:sectPr',ns);new_sect=new_doc.find('w:body/w:sectPr',ns)
    assert etree.tostring(orig_sect)==etree.tostring(new_sect),'Section geometry drift'
    final=dict(src_parts)
    for n in ['word/document.xml','word/_rels/document.xml.rels','[Content_Types].xml']:final[n]=gen_parts[n]
    styles=etree.fromstring(src_parts['word/styles.xml']);gstyles=etree.fromstring(gen_parts['word/styles.xml'])
    if not styles.xpath('./w:style[w:name/@w:val="Title"]',namespaces=ns):
        title_style=gstyles.xpath('./w:style[w:name/@w:val="Title"]',namespaces=ns)[0];styles.append(deepcopy(title_style))
        final['word/styles.xml']=etree.tostring(styles,xml_declaration=True,encoding='UTF-8',standalone=True)
    for n,data in gen_parts.items():
        if n not in src_parts:final[n]=data
    with zipfile.ZipFile(OUTPUT,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for n,data in final.items():z.writestr(n,data)
    editable={'word/document.xml','word/_rels/document.xml.rels','[Content_Types].xml','word/styles.xml'}
    unchanged=[n for n in src_parts if n not in editable]
    assert all(final[n]==src_parts[n] for n in unchanged)
    audit=dict(template_sha256=TEMPLATE_SHA,output_sha256=sha(OUTPUT.read_bytes()),
               original_page_count=3,section_count=1,original_parts_preserved=len(unchanged),
               changed_parts=[n for n in src_parts if final[n]!=src_parts[n]],
               added_parts=[n for n in final if n not in src_parts],
               bounded_section_lengths={key:dict(characters=len(text),limit=limit) for key,(text,limit) in limits.items()},
               summary_characters=len(reflection),extensions_characters=len(extensions),
               board_report_sha256=sha(board_zip.read_bytes()),board_cases=1,
               source_parts={n:dict(bytes=len(v),sha256=sha(v)) for n,v in src_parts.items()})
    (TMP/'fidelity_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
assert sha(REF.read_bytes())==TEMPLATE_SHA
print(OUTPUT)
print('Preserved original package parts:',len(unchanged))
