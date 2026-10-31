# -*- coding: utf-8 -*-
"""生成 FinSocratic 课程作业演示 PPT（16:9，可编辑 .pptx）。"""
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn
import os

# ---------- 配色 ----------
NAVY   = RGBColor(0x1A, 0x2B, 0x4A)
NAVY2  = RGBColor(0x12, 0x1F, 0x38)
GOLD   = RGBColor(0xC9, 0xA2, 0x27)
TEAL   = RGBColor(0x2E, 0x86, 0xAB)
WHITE  = RGBColor(0xFF, 0xFF, 0xFF)
LIGHT  = RGBColor(0xF5, 0xF7, 0xFA)
GRAY   = RGBColor(0x5A, 0x6B, 0x7F)
RED    = RGBColor(0xC0, 0x39, 0x2B)

FONT = "微软雅黑"
SW, SH = Inches(13.333), Inches(7.5)

prs = Presentation()
prs.slide_width = SW
prs.slide_height = SH
BLANK = prs.slide_layouts[6]


def _set_font(run, size, color, bold=False, italic=False):
    run.font.name = FONT
    run.font.size = Pt(size)
    run.font.color.rgb = color
    run.font.bold = bold
    run.font.italic = italic
    r = run._r
    rPr = r.get_or_add_rPr()
    ea = rPr.find(qn('a:ea'))
    if ea is None:
        ea = rPr.makeelement(qn('a:ea'), {})
        rPr.append(ea)
    ea.set('typeface', FONT)


def add_rect(slide, x, y, w, h, color, line=False):
    sh = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, x, y, w, h)
    sh.fill.solid()
    sh.fill.fore_color.rgb = color
    if line:
        sh.line.color.rgb = color
    else:
        sh.line.fill.background()
    sh.shadow.inherit = False
    return sh


def add_text(slide, x, y, w, h, text, size, color, bold=False, align=PP_ALIGN.LEFT,
             anchor=MSO_ANCHOR.TOP, line_spacing=1.15):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = line_spacing
        # 支持「**加粗**」与「//次要//」标记
        segs = ln.split("**")
        for j, seg in enumerate(segs):
            if not seg:
                continue
            r = p.add_run()
            r.text = seg
            _set_font(r, size, color, bold=bold or (j % 2 == 1))
    return tb


def bullet_slide(title, items, kicker=None, accent=GOLD):
    s = prs.slides.add_slide(BLANK)
    add_rect(s, 0, 0, SW, SH, WHITE)
    add_rect(s, 0, 0, Inches(0.22), SH, NAVY)
    add_rect(s, Inches(0.7), Inches(0.62), Inches(0.9), Inches(0.09), accent)
    if kicker:
        add_text(s, Inches(0.7), Inches(0.24), Inches(11.9), Inches(0.34), kicker,
                 13, GRAY, bold=True)
    add_text(s, Inches(0.7), Inches(0.82), Inches(12.0), Inches(0.9), title,
             30, NAVY, bold=True)
    top = Inches(1.9)
    for it in items:
        # it: (层级, 文本)  层级 0=主条目, 1=子条目
        lvl, txt = it
        x = Inches(0.95) if lvl == 0 else Inches(1.35)
        w = Inches(11.4) if lvl == 0 else Inches(11.0)
        if lvl == 0:
            add_rect(s, Inches(0.72), top + Inches(0.16), Inches(0.12), Inches(0.12), accent)
            add_text(s, x, top, w, Inches(0.5), txt, 17, NAVY, bold=True)
        else:
            add_text(s, x, top, w, Inches(0.45), "— " + txt, 14, GRAY)
        top += Inches(0.62) if lvl == 0 else Inches(0.5)
    return s


def kpi_slide(title, kpis, kicker=None):
    s = prs.slides.add_slide(BLANK)
    add_rect(s, 0, 0, SW, SH, WHITE)
    add_rect(s, 0, 0, Inches(0.22), SH, NAVY)
    add_rect(s, Inches(0.7), Inches(0.62), Inches(0.9), Inches(0.09), GOLD)
    if kicker:
        add_text(s, Inches(0.7), Inches(0.24), Inches(11.9), Inches(0.34), kicker, 13, GRAY, bold=True)
    add_text(s, Inches(0.7), Inches(0.82), Inches(12.0), Inches(0.9), title, 30, NAVY, bold=True)
    n = len(kpis)
    gap = Inches(0.4)
    cw = (Inches(12.0) - gap * (n - 1)) / n
    x = Inches(0.72)
    y = Inches(2.1)
    h = Inches(3.9)
    for num, label, note in kpis:
        card = add_rect(s, x, y, cw, h, LIGHT)
        add_rect(s, x, y, cw, Inches(0.12), NAVY)
        add_text(s, x + Inches(0.35), y + Inches(0.55), cw - Inches(0.7), Inches(1.2),
                 num, 40, NAVY, bold=True, align=PP_ALIGN.CENTER)
        add_text(s, x + Inches(0.35), y + Inches(1.95), cw - Inches(0.7), Inches(0.9),
                 label, 16, GRAY, bold=True, align=PP_ALIGN.CENTER)
        add_text(s, x + Inches(0.35), y + Inches(2.75), cw - Inches(0.7), Inches(1.0),
                 note, 12, GRAY, align=PP_ALIGN.CENTER, line_spacing=1.1)
        x += cw + gap
    return s


# ================= 1. 封面 =================
s = prs.slides.add_slide(BLANK)
add_rect(s, 0, 0, SW, SH, NAVY2)
add_rect(s, 0, 0, SW, Inches(0.18), GOLD)
add_text(s, Inches(0.9), Inches(1.1), Inches(11.5), Inches(0.5),
         "课程作业 · AI 金融研究 Agent", 15, GOLD, bold=True)
add_text(s, Inches(0.9), Inches(1.9), Inches(11.5), Inches(1.8),
         "FinSocratic", 60, WHITE, bold=True)
add_text(s, Inches(0.9), Inches(3.35), Inches(11.5), Inches(1.3),
         "FOF 基金经理证据尽调 Agent —— 维护证据与更新判断，而非只产出文字",
         22, RGBColor(0xBD, 0xC7, 0xD6), bold=True)
add_rect(s, Inches(0.92), Inches(5.15), Inches(1.6), Inches(0.06), GOLD)
add_text(s, Inches(0.9), Inches(5.5), Inches(11.5), Inches(1.0),
         "净值/持仓/报告核对 · 贝叶斯能力估计 · 神经网络风险学习 · 研究记忆与版本差异 · 前瞻验证",
         14, RGBColor(0x8E, 0x9A, 0xAC))
add_text(s, Inches(0.9), Inches(6.7), Inches(11.5), Inches(0.5),
         "2026-11-02  ·  提交演示", 13, RGBColor(0x6A, 0x76, 0x88))

# ================= 2. 问题与用户 =================
bullet_slide(
    "问题：FOF 研究为什么低效",
    [
        (0, "资料分散：净值在销售平台、持仓在定期报告 PDF、任职在公告，口径与披露范围不一致"),
        (0, "重复计算：收益、回撤、同类超额收益每次重算，方法不固定、结果不可复现"),
        (0, "结论不可追溯：报告里的关键数字，无法回到「哪份原文、哪次计算」"),
        (0, "跨期判断难延续：新季度报告出来后，不知道上一版结论里哪些被支持、哪些被削弱"),
    ],
    kicker="01 · 问题与用户",
)
add_rect(s, Inches(0.72), Inches(5.9), Inches(11.9), Inches(0.9), NAVY)
add_text(s, Inches(1.0), Inches(6.02), Inches(11.4), Inches(0.66),
         "用户：FOF 初筛与尽调研究人员  ·  主任务：核验「相对收益优势是否持续、材料能否支撑经理能力」",
         14, WHITE, bold=True, anchor=MSO_ANCHOR.MIDDLE)

# ================= 3. 直接聊天的不足 =================
s = prs.slides.add_slide(BLANK)
add_rect(s, 0, 0, SW, SH, WHITE)
add_rect(s, 0, 0, Inches(0.22), SH, NAVY)
add_rect(s, Inches(0.7), Inches(0.62), Inches(0.9), Inches(0.09), GOLD)
add_text(s, Inches(0.7), Inches(0.24), Inches(11.9), Inches(0.34), "02 · 产品差异", 13, GRAY, bold=True)
add_text(s, Inches(0.7), Inches(0.82), Inches(12.0), Inches(0.9),
         "相比「直接把文件交给 AI」，我们强在哪", 28, NAVY, bold=True)

rows = [
    ("研究动作", "直接把文件交给 AI", "FinSocratic"),
    ("准备数据", "用户整理、上传、说明口径", "自动关联基金、报告期、净值与持仓"),
    ("复算数字", "每次重新要求计算", "固定方法、相同输入可复现、保留口径"),
    ("找矛盾", "高度依赖提示词", "自动核对陈述、计算与披露范围"),
    ("更新判断", "再问一次、自己比答案", "明确「新证据改变了什么判断、为什么」"),
]
tbl_y = Inches(1.95)
col_w = [Inches(2.6), Inches(4.6), Inches(4.6)]
col_x = [Inches(0.72), Inches(0.72)+col_w[0], Inches(0.72)+col_w[0]+col_w[1]]
row_h = Inches(0.82)
for ri, row in enumerate(rows):
    for ci, cell in enumerate(row):
        bg = NAVY if ri == 0 else (LIGHT if ri % 2 == 1 else WHITE)
        add_rect(s, col_x[ci], tbl_y + row_h*ri, col_w[ci], row_h, bg)
        color = WHITE if ri == 0 else (NAVY if ci == 0 else GRAY)
        bold = ri == 0 or ci == 0
        add_text(s, col_x[ci]+Inches(0.2), tbl_y + row_h*ri, col_w[ci]-Inches(0.4), row_h,
                 cell, 14 if ri else 15, color, bold=bold, anchor=MSO_ANCHOR.MIDDLE)

# ================= 4. Agent 研究流程 =================
bullet_slide(
    "Agent 研究流程：一次可复现的尽调",
    [
        (0, "委派：选择基金 → 提出研究假设（如「相对收益优势是否持续」）"),
        (0, "调查：Agent 自主拆解问题，调用净值复算、持仓核对、报告检索四类工具"),
        (0, "审计：逐条核验论断与证据，识别支持 / 反证 / 证据缺口"),
        (0, "成稿：生成结论与反证表、计算口径、原文定位，可回查可导出"),
        (0, "延续：保存假设与输入快照，新资料入库后优先检索并记录判断变化"),
    ],
    kicker="03 · 核心流程",
)

# ================= 5. 真实任务案例 =================
kpi_slide(
    "真实案例：华夏聚惠 FOFA（当前快照）",
    [
        ("3,253", "净值跨度（天）", "覆盖完整历史区间"),
        ("31", "共同季度样本", "与同类 FOF 对齐比较"),
        ("72.2%", "相对同类收益为正的后验", "贝叶斯后验概率"),
        ("B", "研究就绪度", "4/7 项检查通过，证据可用需补强"),
    ],
    kicker="04 · 真实数据",
)

# ================= 6. 新增证据闭环 =================
bullet_slide(
    "新增证据闭环：判断如何随资料更新",
    [
        (0, "输入指纹：对净值、持仓、原文、档案、模型五类输入做版本指纹"),
        (0, "区分「新证据」与「模型换了一种解释」：相同输入明确标注「未变」"),
        (0, "一键重新检查最新入库资料，生成版本变化记录（支持 / 削弱 / 未改变）"),
        (0, "真实复验：Agent 完成 15 个记录步骤，识别证据变化并引用新增季报 8 条证据"),
        (0, "报告含历史版本与原始证据，可打印归档"),
    ],
    kicker="05 · 研究记忆与版本差异",
)

# ================= 7. 贝叶斯与神经网络 =================
bullet_slide(
    "统计学习：可追溯的贝叶斯与神经网络",
    [
        (0, "贝叶斯能力估计：估计同类 FOF 的季度超额收益均值，输出后验、95% 可信区间、先验敏感性"),
        (1, "明确边界：这是「相对同类的优势后验」，不是「经理能力概率」"),
        (0, "神经网络风险学习：6 特征 → 32 ReLU → 16 ReLU → 1，预测下一月年化波动"),
        (1, "3 网络集成 + 时间验证集早停；混合模型（50% 网络 + 50% 基线）测试 MAE 3.180，优于基线 3.398"),
        (1, "未同时超过简单基线时明确标记为「实验结果」，不参与经理能力判定"),
    ],
    kicker="06 · 方法论",
)

# ================= 8. 前瞻验证协议 =================
kpi_slide(
    "前瞻验证：先冻结、后评估",
    [
        ("42", "已冻结基金", "2026 年 11 月预测已登记"),
        ("523", "因数据/特征不足排除", "明确单列，不伪装覆盖"),
        ("0", "当前独立验证成绩", "最早 12 月评估，不提前宣称提升"),
        ("SHA-256", "模型权重与输入哈希", "同月重复登记不覆盖"),
    ],
    kicker="07 · 时间外验证",
)

# ================= 9. 系统架构 =================
bullet_slide(
    "系统架构与开源组件",
    [
        (0, "后端：FastAPI + Uvicorn + SQLite(WAL)，pandas / NumPy / SciPy / scikit-learn"),
        (0, "前端：React + Vite + TypeScript + Mantine，由 FastAPI 兜底提供静态资源"),
        (0, "数据：约 1,100 只基金、约 93 万条净值记录，存于 D 盘（FINSOCRATIC_HOME）"),
        (0, "开源组件：Mantine、Recharts、react-markdown、Vite 等，许可证已列明"),
        (0, "外部模型：DeepSeek，配置留在本地环境文件，不随源码交付"),
    ],
    kicker="08 · 技术栈",
)

# ================= 10. 验证与限制 =================
bullet_slide(
    "验证与限制：诚实呈现边界",
    [
        (0, "48 项单元测试通过，前端生产构建与关键接口检查通过"),
        (0, "数据快照为合成样例 + 真实公开净值；结论需与管理人原始披露交叉核对"),
        (0, "尚不支持：全市场完整任职与持仓覆盖、任意扫描件 OCR、多用户权限、实时监控"),
        (0, "统计信号 ≠ 经理因果能力：区间跨零、近期持续性不足时会明确降级表述"),
        (0, "模型服务波动时保留超时/失败记录，不伪装成功"),
    ],
    kicker="09 · 验证与限制",
)

# ================= 11. 下一步 =================
s = prs.slides.add_slide(BLANK)
add_rect(s, 0, 0, SW, SH, NAVY2)
add_rect(s, 0, 0, SW, Inches(0.18), GOLD)
add_text(s, Inches(0.9), Inches(1.1), Inches(11.5), Inches(0.5), "10 · 下一步", 15, GOLD, bold=True)
add_text(s, Inches(0.9), Inches(1.9), Inches(11.5), Inches(1.0),
         "从「检索型 AI」到「持续维护研究判断的研究入口」", 30, WHITE, bold=True)
add_rect(s, Inches(0.92), Inches(3.0), Inches(1.6), Inches(0.06), GOLD)
for i, t in enumerate([
    "补充经理任职区间与跨期底层持仓，提升研究就绪度",
    "扩大真实 FOF 覆盖与披露口径对齐，减少解析漏并",
    "前瞻验证到期后，用真实 11 月净值回填评估",
    "把「证据 → 判断 → 更新」沉淀为可复用的研究员工作台",
]):
    add_text(s, Inches(0.9), Inches(3.5) + Inches(0.7)*i, Inches(11.5), Inches(0.6),
             f"{i+1}.  {t}", 16, RGBColor(0xBD, 0xC7, 0xD6))
add_text(s, Inches(0.9), Inches(6.6), Inches(11.5), Inches(0.5),
         "谢谢 · 欢迎提问", 15, GOLD, bold=True)

out = r"D:\FinSocratic-ResearchAgent\exports\FinSocratic_演示PPT.pptx"
os.makedirs(os.path.dirname(out), exist_ok=True)
prs.save(out)
print("SAVED:", out, "slides =", len(prs.slides._sldIdLst))
