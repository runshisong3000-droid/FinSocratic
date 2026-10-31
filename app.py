from __future__ import annotations

import io
import json
from datetime import datetime
from html import escape
from pathlib import Path

import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from finsocratic.analysis import assess_claims, fund_research_report, markdown_report, portfolio_metrics, screen_funds
from finsocratic.agent import render_markdown, run_diligence
from finsocratic.data import UPLOADS, all_metrics, load_samples, load_uploaded_table, normalize_nav
from finsocratic.library import add_document, extract_document, load_library, retrieve


st.set_page_config(page_title="FinSocratic | FOF 研究工作台", page_icon="◈", layout="wide", initial_sidebar_state="auto")
st.markdown("""
<style>
:root { --ink:#17273b; --muted:#66788b; --teal:#087e77; --line:#e3eaf0; --paper:#f5f7fa; }
html, body, [class*="css"] { font-family:'Segoe UI','Microsoft YaHei UI',Arial,sans-serif; }
.stApp { background:var(--paper); color:var(--ink); }
.block-container { padding-top:2rem; padding-bottom:2.5rem; max-width:1500px; }
[data-testid="stSidebar"] { background:#112334; border-right:1px solid #243c50; }
[data-testid="stSidebar"] * { color:#e9f3f5 !important; }
[data-testid="stSidebar"] [data-testid="stRadio"] label { border-radius:9px; padding:2px 4px; }
[data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked) { background:#1b4651; }
[data-testid="stSidebar"] hr { border-color:#344b5a; }
.brand { display:flex; align-items:center; gap:.65rem; font-size:1.25rem; font-weight:760; letter-spacing:-.03em; margin:.3rem 0 .1rem; }
.brand-mark { display:inline-grid; place-items:center; width:33px; height:33px; border-radius:9px; background:#22b9a4; color:#0e2631 !important; }
.brand-sub { color:#a8c0c9 !important; font-size:.75rem; margin:0 0 1.6rem 2.8rem; }
.hero { padding:1.55rem 1.75rem; border-radius:15px; background:#fff; border:1px solid var(--line); border-left:5px solid #0a8b80; box-shadow:0 7px 26px rgba(20,42,62,.035); margin-bottom:1.35rem; }
.hero h1 { color:var(--ink); margin:.28rem 0 0; font-size:1.8rem; letter-spacing:-.035em; font-weight:760; }
.hero p { color:var(--muted); margin:.55rem 0 0; font-size:.92rem; line-height:1.6; }
.eyebrow { text-transform:uppercase; letter-spacing:.16em; font-weight:750; font-size:.69rem; color:#078c83; }
.section-label { color:#a8c0c9; font-size:.72rem; font-weight:700; letter-spacing:.1em; text-transform:uppercase; }
div[data-testid="stMetric"] { background:#fff; border:1px solid var(--line); border-radius:12px; padding:14px 17px; min-height:105px; box-shadow:0 3px 16px rgba(18,41,56,.025); }
div[data-testid="stMetricLabel"] p { color:var(--muted); font-size:.8rem; }
div[data-testid="stMetricValue"] { color:#142d3d; }
.stTabs [data-baseweb="tab-list"] { gap:13px; }
.stTabs [data-baseweb="tab"] { height:44px; background:transparent; }
.stButton>button[kind="primary"] { background:#087e77; border-color:#087e77; font-weight:680; }
.stButton>button[kind="primary"]:hover { background:#076c67; border-color:#076c67; }
div[data-testid="stVerticalBlockBorderWrapper"] > div { border-color:var(--line) !important; border-radius:12px !important; }
.agent-steps { display:flex; gap:9px; flex-wrap:wrap; margin:0 0 1.2rem; }
.agent-step { background:#e8f3f2; border:1px solid #cfe8e4; border-radius:999px; padding:.38rem .75rem; font-size:.76rem; font-weight:650; color:#286e69; }
.status-pill { display:inline-block; background:#eef3f8; color:#436077; border-radius:999px; padding:.25rem .65rem; font-size:.75rem; font-weight:700; }
.evidence-ref { font-family:Consolas,monospace; color:#087e77; font-weight:700; }
</style>
""", unsafe_allow_html=True)


def init_state() -> None:
    if "funds" not in st.session_state:
        funds, nav, holdings = load_samples()
        nav["source_file"] = "nav_monthly.csv（合成演示）"
        holdings["source_file"] = "holdings.csv（合成演示）"
        st.session_state.funds = funds
        st.session_state.nav = nav
        st.session_state.holdings = holdings
        st.session_state.data_origin = "内置演示数据（合成）"
    if "source_file" not in st.session_state.nav.columns:
        st.session_state.nav["source_file"] = "当前工作区净值"
    if "source_file" not in st.session_state.holdings.columns:
        st.session_state.holdings["source_file"] = "当前工作区持仓"


def fmt_pct(value: object) -> str:
    try:
        return f"{float(value):.2%}" if pd.notna(value) else "—"
    except (TypeError, ValueError):
        return "—"


def fmt_ratio(value: object) -> str:
    try:
        return f"{float(value):.2f}" if pd.notna(value) else "—"
    except (TypeError, ValueError):
        return "—"


def fmt_pval(value: object) -> str:
    try:
        return f"{float(value):.3g}" if pd.notna(value) else "—"
    except (TypeError, ValueError):
        return "—"


def header(kicker: str, title: str, desc: str) -> None:
    st.markdown(f'<div class="hero"><div class="eyebrow">{escape(kicker)}</div><h1>{escape(title)}</h1><p>{escape(desc)}</p></div>', unsafe_allow_html=True)


init_state()
funds: pd.DataFrame = st.session_state.funds
nav: pd.DataFrame = st.session_state.nav
holdings: pd.DataFrame = st.session_state.holdings

with st.sidebar:
    st.markdown('<div class="brand"><span class="brand-mark">◈</span> FinSocratic</div><div class="brand-sub">FOF RESEARCH INTELLIGENCE</div>', unsafe_allow_html=True)
    page = st.radio("导航", ["尽调 Agent", "研究总览", "基金筛选", "基金分析", "组合体检", "观点核验", "研究资料库", "数据管理", "方法与数据源"], label_visibility="collapsed")
    st.divider()
    st.markdown('<span class="section-label">当前数据</span>', unsafe_allow_html=True)
    st.write(f"**{len(funds)}** 只基金 · **{len(nav)}** 条净值记录")
    st.caption(st.session_state.data_origin)
    st.caption("本机优先 · 结果可追溯")

if page == "尽调 Agent":
    header("FOF / EVIDENCE AUDIT", "基金经理尽调 Agent", "上传报告与净值，自动拆解管理人陈述、核对可计算事实、标出证据缺口，并生成带来源编号的研究简报。")
    st.markdown('<div class="agent-steps"><span class="agent-step">01 选择研究对象</span><span class="agent-step">02 导入现期与前期材料</span><span class="agent-step">03 自动审计</span><span class="agent-step">04 复核并导出</span></div>', unsafe_allow_html=True)
    st.caption("运行方式：本机确定性分析。演示数据为合成样本；不会自动联网，也不会把文档相似度当成事实证据。")
    if "agent_result" not in st.session_state and "FOF-001" in funds.get("fund_id", pd.Series(dtype=str)).astype(str).tolist():
        demo_fund = funds.loc[funds.fund_id.astype(str) == "FOF-001"].iloc[0]
        note_path = Path(__file__).parent / "data" / "sample" / "manager_note.txt"
        raw = note_path.read_bytes()
        demo_doc = {"name": "manager_note.txt（合成演示）", "chunks": extract_document(note_path.name, raw)}
        demo_benchmark = pd.read_csv(Path(__file__).parent / "data" / "sample" / "benchmark_monthly.csv", parse_dates=["date"])
        demo_benchmark["source_file"] = "benchmark_monthly.csv（合成演示）"
        st.session_state.agent_result = run_diligence(demo_fund, nav, holdings, [demo_doc], benchmark=demo_benchmark)
        st.session_state.agent_is_demo = True
    if funds.empty:
        st.warning("工作区没有基金档案。请先到“数据管理”导入 fund_id、name、manager、strategy。")
    else:
        left, right = st.columns([1.35, 1], gap="large")
        with left:
            with st.container(border=True):
                st.subheader("研究任务")
                fund_id = st.selectbox("基金 / 管理人", funds["fund_id"].astype(str).tolist(),
                                       format_func=lambda x: f"{funds.loc[funds.fund_id.astype(str) == x, 'name'].iloc[0]}  ·  {funds.loc[funds.fund_id.astype(str) == x, 'manager'].iloc[0]}",
                                       key="agent_fund")
                report_file = st.file_uploader("现期报告或沟通纪要", type=["pdf", "docx", "txt"], key="agent_current",
                                               help="支持可提取文本的 PDF、DOCX 和 TXT；扫描版 PDF 需先做 OCR。")
                prior_file = st.file_uploader("前期报告（可选，用于比较叙事变化）", type=["pdf", "docx", "txt"], key="agent_prior")
                library_docs = load_library()
                chosen_names = st.multiselect("追加资料库文件（可选）", [d["name"] for d in library_docs], key="agent_library")
                extra_text = st.text_area("需要核对的补充陈述（可选）", height=80,
                                          placeholder="例如：最大回撤控制在 5% 以内。", key="agent_extra")
            with st.container(border=True):
                st.subheader("基准序列 · 可选")
                benchmark_file = st.file_uploader("CSV / Excel，包含日期和净值列", type=["csv", "xlsx", "xlsm"], key="agent_benchmark")
                benchmark_frame = None
                benchmark_date = benchmark_value = None
                if benchmark_file is not None:
                    try:
                        benchmark_frame = load_uploaded_table(benchmark_file.name, benchmark_file.getvalue())
                        if benchmark_frame.empty:
                            st.warning("基准文件没有记录。")
                        else:
                            bc1, bc2 = st.columns(2)
                            benchmark_date = bc1.selectbox("日期列", list(benchmark_frame.columns), key="agent_bench_date")
                            benchmark_value = bc2.selectbox("净值列", list(benchmark_frame.columns), index=min(1, len(benchmark_frame.columns)-1), key="agent_bench_value")
                    except Exception as exc:
                        st.error(f"基准文件读取失败：{exc}")
                        benchmark_frame = None
        with right:
            with st.container(border=True):
                st.subheader("这次运行会检查")
                st.markdown("""**数据质量** · 日期、净值、持仓快照和基准对齐  
**量化陈述** · 收益、回撤、配置比例与基准比较  
**叙事变化** · 前后期相同主题的表述差异  
**审计留痕** · 原文位置、计算证据编号与追问清单""")
                st.info("“相符”只表示在当前数据和口径内相符；定性归因、持续领先等说法会明确保留待核验状态。")
            c_run, c_demo = st.columns(2)
            run_clicked = c_run.button("运行尽调 Agent", type="primary", width="stretch",
                                       disabled=not (report_file or chosen_names or extra_text.strip()))
            demo_clicked = c_demo.button("运行内置案例", width="stretch")
            st.caption("内置案例使用合成 FOF 数据和 `data/sample/manager_note.txt`，适合课堂演示。")

        if run_clicked or demo_clicked:
            try:
                if demo_clicked:
                    demo_rows = funds.loc[funds.fund_id.astype(str) == "FOF-001"]
                    if demo_rows.empty:
                        raise ValueError("当前工作区没有 FOF-001；请恢复样例数据，或上传报告运行自选基金。")
                    chosen_fund = demo_rows.iloc[0]
                    note_path = Path(__file__).parent / "data" / "sample" / "manager_note.txt"
                    raw = note_path.read_bytes()
                    current_docs = [{"name": "manager_note.txt（合成演示）", "chunks": extract_document(note_path.name, raw)}]
                    prior_docs = None
                    benchmark = pd.read_csv(Path(__file__).parent / "data" / "sample" / "benchmark_monthly.csv", parse_dates=["date"])
                    benchmark["source_file"] = "benchmark_monthly.csv（合成演示）"
                else:
                    chosen_fund = funds.loc[funds.fund_id.astype(str) == fund_id].iloc[0]
                    current_docs = [d for d in library_docs if d["name"] in chosen_names]
                    if report_file is not None:
                        current_docs.append({"name": report_file.name, "chunks": extract_document(report_file.name, report_file.getvalue())})
                    if extra_text.strip():
                        current_docs.append({"name": "手工输入陈述", "chunks": extract_document("input.txt", extra_text.encode("utf-8"))})
                    prior_docs = ([{"name": prior_file.name, "chunks": extract_document(prior_file.name, prior_file.getvalue())}]
                                  if prior_file is not None else None)
                    benchmark = None
                    if benchmark_frame is not None and not benchmark_frame.empty and benchmark_date and benchmark_value:
                        benchmark, bench_warnings = normalize_nav(benchmark_frame, benchmark_date, benchmark_value, "BENCHMARK")
                        benchmark["source_file"] = benchmark_file.name
                        for warning in bench_warnings:
                            st.warning(f"基准数据：{warning}")
                with st.spinner("正在执行数据检查、陈述拆解和证据审计…"):
                    st.session_state.agent_result = run_diligence(chosen_fund, nav, holdings, current_docs,
                                                                    benchmark=benchmark, prior_documents=prior_docs)
                    st.session_state.agent_is_demo = bool(demo_clicked)
                st.success("审计完成。请逐项复核结论和原始证据。")
            except Exception as exc:
                st.error(f"审计未完成：{exc}")

        result = st.session_state.get("agent_result")
        if result:
            st.divider()
            st.markdown(f"### {escape(result['fund']['name'])} · 证据审计结果")
            if st.session_state.get("agent_is_demo"):
                st.caption("当前展示内置合成案例。上传自己的资料并运行后，结果会按新数据重算。")
            claims = result["claims"]
            counts = {key: sum(item["status"] == key for item in claims)
                      for key in ("supported_within_scope", "contradicted", "inconclusive", "unverifiable")}
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("可定位证据", len(result["evidence"]))
            m2.metric("已拆解陈述", len(claims))
            m3.metric("数据矛盾", counts["contradicted"])
            m4.metric("待核验 / 证据不足", counts["inconclusive"] + counts["unverifiable"])
            st.info(result["manager_summary"])
            t1, t2, t3, t4 = st.tabs(["陈述核验", "证据台账", "跨期变化与追问", "数据口径与导出"])
            with t1:
                if not claims:
                    st.warning("材料中尚未识别出可审计的陈述。请检查文本提取结果或补充待核对陈述。")
                for item in claims[:40]:
                    with st.expander(f"{item['status_label']}  ·  {item['text'][:72]}", expanded=item["status"] == "contradicted"):
                        st.write(item["explanation"])
                        st.caption(f"原文：{item['source']} · {item['location']} · {item['source_evidence_id']}")
                        st.caption(f"对照证据：{', '.join(item['check_evidence_ids']) or '暂无独立量化证据'}")
                        st.caption(f"核验边界：{item['limitation']}")
                if len(claims) > 40:
                    st.caption(f"页面展示前 40 条；导出的报告保留全部 {len(claims)} 条。")
            with t2:
                st.dataframe(pd.DataFrame([{"证据编号": e["id"], "类型": e["kind"], "来源": e["source"],
                                            "位置": e["location"], "原文 / 计算说明": e["text"]}
                                           for e in result["evidence"]]), hide_index=True, width="stretch")
                st.caption("编号把原文和计算结果连回报告；原始文件只在当前运行中处理，资料库文件遵循“研究资料库”的本机保存规则。")
            with t3:
                comparisons = result["period_comparison"]
                if comparisons:
                    st.subheader("跨期同主题表述")
                    for item in comparisons:
                        st.markdown(f"**{item['topic']}** · {item['assessment']}")
                        st.caption(f"前期：{item['prior_text']}  ｜  现期：{item['current_text']}")
                else:
                    st.caption("没有可比较的前期材料，或未识别到同主题陈述。")
                st.subheader("建议向管理人追问")
                if result["follow_up_questions"]:
                    for item in result["follow_up_questions"]:
                        st.markdown(f"**{item['priority']}优先级** · {item['question']}")
                else:
                    st.caption("当前没有自动生成的追问。")
            with t4:
                metrics_result = result["metrics"]
                s1, s2, s3, s4 = st.columns(4)
                s1.metric("区间收益", fmt_pct(metrics_result.get("total_return")))
                s2.metric("年化收益", fmt_pct(metrics_result.get("annual_return")))
                s3.metric("年化波动", fmt_pct(metrics_result.get("volatility")))
                s4.metric("最大回撤", fmt_pct(metrics_result.get("max_drawdown")))
                st.caption(f"净值区间：{metrics_result.get('start') or '—'} 至 {metrics_result.get('end') or '—'} · {metrics_result.get('observations')} 个有效点 · {metrics_result.get('frequency')}")
                comparison = result["benchmark_comparison"]
                if comparison.get("relative_return_pp") is not None:
                    st.write(f"同日端点相对基准收益：**{comparison['relative_return_pp']:+.2f} 个百分点**；匹配 {comparison['matched_observations']} 个日期。")
                attribution = comparison.get("attribution")
                if attribution:
                    st.markdown("**风险调整归因（相对基准）**")
                    attrib_view = pd.DataFrame([
                        {"指标": "Beta（相对基准）", "数值": fmt_ratio(attribution.get("beta"))},
                        {"指标": "Jensen Alpha（年化，rf=0）", "数值": fmt_pct(attribution.get("alpha_annualized"))},
                        {"指标": "与基准相关性", "数值": fmt_ratio(attribution.get("correlation"))},
                        {"指标": "R²（基准解释比例）", "数值": fmt_ratio(attribution.get("r_squared"))},
                        {"指标": "Beta 显著性 p 值", "数值": fmt_pval(attribution.get("beta_pvalue"))},
                        {"指标": "跟踪误差（年化）", "数值": fmt_pct(attribution.get("tracking_error"))},
                        {"指标": "信息比率", "数值": fmt_ratio(attribution.get("information_ratio"))},
                        {"指标": "主动收益（年化）", "数值": fmt_pct(attribution.get("active_return_annualized"))},
                        {"指标": "上行捕获率", "数值": fmt_ratio(attribution.get("up_capture_ratio"))},
                        {"指标": "下行捕获率", "数值": fmt_ratio(attribution.get("down_capture_ratio"))},
                    ])
                    st.dataframe(attrib_view, hide_index=True, width="stretch")
                    st.caption(f"由 {comparison.get('attribution_observations')} 个同日收益期按确定性公式计算（OLS 回归由 scipy 提供）；无风险利率设为0。")
                for issue in result["data_quality"]["issues"]:
                    (st.error if issue["severity"] == "error" else st.warning)(issue["message"])
                st.download_button("下载审计简报 Markdown", render_markdown(result),
                                   file_name=f"{result['fund']['fund_id']}_diligence.md", mime="text/markdown")
                st.download_button("下载证据台账 JSON", json.dumps(result, ensure_ascii=False, indent=2),
                                   file_name=f"{result['fund']['fund_id']}_evidence.json", mime="application/json")

elif page == "研究总览":
    header("FUND RESEARCH DESK", "从数据到判断，每一步都能回看。", "并列查看基金表现、组合暴露和管理人陈述；遇到证据不足时明确标出缺口。")
    metrics = all_metrics(funds, nav)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("覆盖基金", f"{len(funds)}", "结构化档案")
    c2.metric("净值观测", f"{len(nav):,}", "已导入记录")
    c3.metric("持仓快照", f"{holdings['fund_id'].nunique() if not holdings.empty else 0}", "只基金")
    c4.metric("研究资料", f"{sum(len(d.get('chunks', [])) for d in load_library())}", "可检索文本片段")
    left, right = st.columns([1.55, 1])
    with left:
        st.subheader("基金表现一览")
        view = metrics[["基金", "管理人", "策略", "区间收益", "年化收益", "年化波动", "最大回撤", "夏普比率", "索提诺比率", "卡玛比率", "偏度", "峰度", "95%VaR", "Omega比率"]].copy()
        for col in ["区间收益", "年化收益", "年化波动", "最大回撤", "95%VaR"]:
            view[col] = view[col].map(fmt_pct)
        for col in ["夏普比率", "索提诺比率", "卡玛比率", "偏度", "峰度", "Omega比率"]:
            view[col] = view[col].map(lambda x: f"{x:.2f}" if pd.notna(x) else "—")
        st.dataframe(view, hide_index=True, width="stretch")
    with right:
        st.subheader("净值走势")
        if not nav.empty:
            chart = nav.merge(funds[["fund_id", "name"]], on="fund_id", how="left")
            fig = px.line(chart, x="date", y="nav", color="name", labels={"date":"日期", "nav":"单位净值", "name":"基金"}, color_discrete_sequence=["#087f75", "#ec9f45", "#6677aa"])
            fig.update_layout(margin=dict(l=0,r=0,t=10,b=0), legend_title_text="", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="white", height=330)
            st.plotly_chart(fig, width="stretch")
    st.info("当前内置数据为合成演示样本，不代表真实基金或管理人。导入自己的数据后，页面会按实际资料更新。")
    st.download_button("下载当前基金研究速报（Markdown）", "\n\n".join(fund_research_report(row, nav, holdings) for _, row in funds.iterrows()), file_name="fund_research_reports.md", mime="text/markdown")
    st.subheader("建议的研究顺序")
    steps = st.columns(4)
    for col, title, detail in zip(steps, ["01 · 导入", "02 · 体检", "03 · 核验", "04 · 留痕"], ["导入净值、持仓与说明材料", "查看收益、风险和暴露", "逐条比较陈述与可用证据", "导出可复核的分析记录"]):
        with col:
            st.markdown(f"**{title}**  \n{detail}")

elif page == "基金筛选":
    header("FUND SCREENING", "先定义约束，再比较候选基金。", "筛选只总结历史样本特征，不等同于经理能力判断或未来收益预测。")
    a, b = st.columns(2)
    min_obs = a.slider("最低净值观测数", min_value=3, max_value=60, value=24, help="月频数据下，24 个点约覆盖两年；实际频率和缺口请查看数据频率列。")
    max_dd = b.slider("最大回撤上限", min_value=5, max_value=80, value=35, step=5, format="%d%%")
    st.caption("候选分数 = 年化收益横截面百分位 × 50% + 夏普比率百分位 × 30% + 回撤较小百分位 × 20%。权重固定展示；低于观测门槛或超过回撤约束的基金不排名。")
    screened = screen_funds(funds, nav, holdings, min_observations=min_obs, max_drawdown_limit=max_dd / 100)
    screen_view = screened[["名次", "基金", "基金编号", "年化收益", "年化波动", "最大回撤", "夏普比率", "净值月数", "数据频率", "持仓权重合计", "筛选分数", "可排名", "未入选原因"]].rename(columns={"净值月数": "净值点数"})
    st.dataframe(screen_view, hide_index=True, width="stretch")
    eligible = screened.loc[screened["可排名"]]
    if eligible.empty:
        st.warning("当前数据没有满足条件且足以横向排名的基金。请降低历史观测门槛，或补充净值数据；系统不会对不充分样本强行排序。")
    else:
        chosen = eligible.iloc[0]
        st.info(f"按当前历史指标与约束，优先进一步研究：**{chosen['基金']}**。这只是研究优先级，不构成投资建议或经理能力结论。")
    with st.expander("评分方法、数据局限与敏感性"):
        st.write("收益和夏普按当前样本横截面百分位计分，回撤按绝对回撤越小越优计分。权重与门槛变动可能改变排序；目前尚未提供权重敏感性分析。没有基准数据，因此不评价超额收益；持仓权重合计只用于提示快照是否可用，不参与评分。")
    st.download_button("导出筛选结果 CSV", screened.to_csv(index=False).encode("utf-8-sig"), "fund_screening.csv", "text/csv")

elif page == "基金分析":
    header("FUND PROFILE", "基金分析", "查看单只产品的回报路径、风险指标与基础档案。所有指标均由当前导入的净值序列计算。")
    selected = st.selectbox("选择基金", funds["fund_id"].astype(str), format_func=lambda x: funds.loc[funds.fund_id.astype(str) == x, "name"].iloc[0])
    fund = funds.loc[funds.fund_id.astype(str) == selected].iloc[0]
    track = nav.loc[nav.fund_id.astype(str) == selected].sort_values("date")
    metric = all_metrics(funds.loc[funds.fund_id.astype(str) == selected], nav).iloc[0]
    st.caption(f"{fund['manager']} · {fund['strategy']} · 成立 {fund.get('inception', '—')} · 数据来源：{st.session_state.data_origin}")
    cols = st.columns(7)
    for col, label, val in zip(cols, ["区间收益", "年化收益", "年化波动", "最大回撤", "夏普比率", "索提诺比率", "卡玛比率"], [fmt_pct(metric["区间收益"]), fmt_pct(metric["年化收益"]), fmt_pct(metric["年化波动"]), fmt_pct(metric["最大回撤"]), f"{metric['夏普比率']:.2f}" if pd.notna(metric["夏普比率"]) else "—", f"{metric['索提诺比率']:.2f}" if pd.notna(metric["索提诺比率"]) else "—", f"{metric['卡玛比率']:.2f}" if pd.notna(metric["卡玛比率"]) else "—"]):
        col.metric(label, val)
    st.caption(f"收益分布诊断：偏度 {fmt_ratio(metric['偏度'])}（负偏提示左尾风险），超额峰度 {fmt_ratio(metric['峰度'])}（>0 提示厚尾，Sharpe 之外需额外留意）。")
    with st.expander("尾部风险与回撤深潜（empyrical 口径）"):
        t1, t2, t3, t4, t5 = st.columns(5)
        t1.metric("95%VaR", fmt_pct(metric["95%VaR"]), help="历史模拟法：收益的5%分位数（负值=损失）")
        t2.metric("95%CVaR", fmt_pct(metric["95%CVaR"]), help="期望短缺：收益≤VaR 的平均值")
        t3.metric("尾部比率", fmt_ratio(metric["尾部比率"]), help="|95%分位收益|/|5%分位收益|，>1 表示右尾收益更厚")
        t4.metric("Omega比率", fmt_ratio(metric["Omega比率"]), help="正收益合计 / |负收益合计|")
        t5.metric("最长水下期", f"{int(metric['最长水下期'])} 期" if pd.notna(metric["最长水下期"]) else "—", help="净值连续低于历史高点的最长观测期数")
        st.caption("VaR/CVaR 为历史模拟法，仅反映样本内经验分布，不是未来损失保证；简单收益未对数化，需结合数据频率解读。")
    tab1, tab2 = st.tabs(["净值与回撤", "原始记录"])
    with tab1:
        if not track.empty:
            track = track.copy()
            track["回撤"] = track["nav"] / track["nav"].cummax() - 1
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=track.date, y=track.nav, name="单位净值", line=dict(color="#087f75", width=3)))
            fig.update_layout(height=370, margin=dict(l=0,r=0,t=15,b=0), paper_bgcolor="white", plot_bgcolor="white", yaxis_title="单位净值", xaxis_title="")
            st.plotly_chart(fig, width="stretch")
            dd = px.area(track, x="date", y="回撤", labels={"date":"日期", "回撤":"回撤"}, color_discrete_sequence=["#e79862"])
            dd.update_layout(height=220, margin=dict(l=0,r=0,t=8,b=0), paper_bgcolor="white", plot_bgcolor="white")
            st.plotly_chart(dd, width="stretch")
    with tab2:
        st.dataframe(track, hide_index=True, width="stretch")
    st.caption(f"说明：年化收益按净值端点和实际观测跨度复合年化；当前净值频率为 {metric['数据频率']}，波动、夏普与索提诺按频率年化，非规则序列不计算；夏普与索提诺未扣除无风险利率；卡玛=年化收益/|最大回撤|；离散净值可能遗漏观测日之间的回撤。")

elif page == "组合体检":
    header("PORTFOLIO CHECKUP", "组合体检", "拆解持仓集中度、类别占比与快照质量。这里呈现已上传快照，不代替完整穿透或风险模型。")
    available = holdings["fund_id"].astype(str).unique().tolist() if not holdings.empty else []
    if not available:
        st.warning("还没有持仓数据。请到“数据管理”导入持仓表。")
    else:
        selected = st.selectbox("选择基金", available, format_func=lambda x: funds.loc[funds.fund_id.astype(str) == x, "name"].iloc[0] if (funds.fund_id.astype(str) == x).any() else x)
        result = portfolio_metrics(holdings, selected)
        if not result["available"]:
            st.warning(result["reason"])
        else:
            rows = result["rows"].copy()
            a, b, c, d = st.columns(4)
            a.metric("快照日期", result["as_of"])
            b.metric("持仓合计", fmt_pct(result["reported_weight_sum"] / 100))
            c.metric("最大单项权重", fmt_pct(result["top_weight"] / 100))
            d.metric("持仓条目", result["asset_count"])
            if abs(result["reported_weight_sum"] - 100) > 1:
                st.warning(f"持仓权重合计为 {result['reported_weight_sum']:.2f}%，与100%相差较大。请检查是否存在漏项、重复或计量口径不同。")
            left, right = st.columns([1.1, 1])
            with left:
                fig = px.pie(rows, names="asset", values="weight_pct", hole=.58, color_discrete_sequence=["#087f75", "#3da89d", "#77c5b8", "#f1b36b", "#8291b5", "#b8c9c8"])
                fig.update_layout(height=360, margin=dict(l=0,r=0,t=15,b=0), legend_title_text="")
                st.plotly_chart(fig, width="stretch")
            with right:
                st.subheader("快照明细")
                st.dataframe(rows[["asset", "weight_pct", "as_of"]], hide_index=True, width="stretch")
                st.caption(f"HHI（归一化权重平方和）：{result['hhi']:.3f}。该指标仅按当前分类层级计算，类别定义会影响集中度。")
            st.caption("如基金包含FOF/资管计划等底层资产，目前不会自动穿透；不同日期的快照也不应直接当作同步暴露。")

elif page == "观点核验":
    header("CLAIM REVIEW", "把观点拆成可检查的问题。", "逐条记录管理人说法、当前可比数据、检查结论和证据边界；无法验证的内容会明确留空。")
    if funds.empty:
        st.warning("先导入基金档案。")
    else:
        selected = st.selectbox("关联基金", funds["fund_id"].astype(str), format_func=lambda x: funds.loc[funds.fund_id.astype(str) == x, "name"].iloc[0], key="claim_fund")
        c1, c2 = st.columns([1,1])
        with c1:
            source_file = st.file_uploader("管理人材料（TXT / PDF / DOCX）", type=["txt", "pdf", "docx"], key="claim_doc")
        with c2:
            st.caption("或直接粘贴需要核对的说法。上传文档仅在本机提取文本，不调用外部模型。扫描版PDF暂不支持OCR。")
        prefill = ""
        if source_file:
            try:
                chunks = extract_document(source_file.name, source_file.getvalue())
                prefill = "\n".join(c["text"] for c in chunks)
                st.success(f"读取到 {len(chunks)} 段文本。请检查提取结果，再运行核验。")
            except Exception as exc:
                st.error(str(exc))
        text = st.text_area("陈述原文", value=prefill, height=190, placeholder="例如：权益策略约占组合净值的28%；年内最大回撤控制在5%以内。")
        if st.button("生成逐条核对", type="primary", disabled=not text.strip()):
            fund = funds.loc[funds.fund_id.astype(str) == selected].iloc[0]
            st.session_state.claim_results = assess_claims(text, fund, nav, holdings)
            st.session_state.claim_fund_name = fund["name"]
        if st.session_state.get("claim_results"):
            results = st.session_state.claim_results
            st.subheader("核对结果")
            st.dataframe(pd.DataFrame(results), hide_index=True, width="stretch")
            st.download_button("下载核对记录（Markdown）", markdown_report(st.session_state.claim_fund_name, results), file_name="claim_review.md", mime="text/markdown")
            st.info("“相符”仅表示在当前样本、日期与数据频率下未发现明显差异，不表示事实已被独立证实；“不符”也需要先检查口径、费用、复权和观察区间。")

elif page == "研究资料库":
    header("RESEARCH LIBRARY", "让结论带着出处。", "在本机保存研究文件，以关键词相似度检索相关片段；每条结果保留文件名和页码/段落位置。")
    upload = st.file_uploader("添加资料", type=["pdf", "docx", "txt"], key="library_upload")
    if upload and st.button("加入本机资料库"):
        try:
            raw = upload.getvalue()
            chunks = extract_document(upload.name, raw)
            added, message = add_document(upload.name, raw, chunks)
            (st.success if added else st.info)(message)
        except Exception as exc:
            st.error(str(exc))
    documents = load_library()
    query = st.text_input("检索资料", placeholder="例如：组合最大回撤、流动性安排、债券策略")
    if query:
        hits = retrieve(query, documents, limit=10)
        if not hits:
            st.warning("没有找到相似片段。试试原文中的关键词，或先添加研究资料。")
        for hit in hits:
            with st.expander(f"{hit['file']} · {hit['location']} · 匹配度 {hit['score']:.2f}"):
                st.write(hit["text"])
    if documents:
        st.subheader("本机资料清单")
        st.dataframe(pd.DataFrame([{"文件": d["name"], "片段数": len(d["chunks"]), "大小": f"{d['size'] / 1024:.1f} KB", "加入时间": d["added_at"]} for d in documents]), hide_index=True, width="stretch")
        st.caption(f"资料库原文件与索引保存在本机：{UPLOADS.parent}。导入前请确认你有权处理这些文件；删除该目录即可清除。")
    else:
        st.caption("资料库为空。")

elif page == "数据管理":
    header("DATA WORKSPACE", "导入数据，保留口径。", "支持CSV和Excel。导入时显式映射列名；原文件不会被覆盖，当前工作区的数据只在本次应用会话中生效。")
    t1, t2, t3 = st.tabs(["净值序列", "持仓快照", "基金档案"])
    with t1:
        up = st.file_uploader("选择CSV/XLSX", type=["csv", "xlsx", "xlsm"], key="nav_up")
        if up:
            try:
                frame = load_uploaded_table(up.name, up.getvalue())
                st.write("预览", frame.head(8))
                cols = list(frame.columns)
                dc = st.selectbox("日期列", cols, key="nav_date")
                vc = st.selectbox("净值列", cols, key="nav_value")
                existing_ids = funds["fund_id"].astype(str).tolist()
                selected_id = st.selectbox("匹配基金编号", existing_ids, key="nav_fund") if existing_ids else None
                if not existing_ids:
                    st.warning("请先导入基金档案，再关联净值。")
                if st.button("追加净值数据", disabled=selected_id is None):
                    normalized, warnings = normalize_nav(frame, dc, vc, selected_id)
                    if normalized.empty:
                        raise ValueError("文件中没有可导入的有效净值记录。")
                    normalized["source_file"] = up.name
                    st.session_state.nav = pd.concat([st.session_state.nav, normalized], ignore_index=True).drop_duplicates(["fund_id", "date"], keep="last").sort_values(["fund_id", "date"])
                    st.session_state.data_origin = f"用户导入：{up.name}"
                    st.session_state.agent_result = None
                    st.success(f"已导入 {len(normalized)} 条净值记录。")
                    for warning in warnings: st.warning(warning)
                    st.rerun()
            except Exception as exc: st.error(f"读取失败：{exc}")
        st.caption("净值表要求一行一个日期观测。若文件含复权净值，请在研究记录中注明口径。")
    with t2:
        up = st.file_uploader("持仓CSV/XLSX", type=["csv", "xlsx", "xlsm"], key="holding_up")
        if up:
            try:
                frame = load_uploaded_table(up.name, up.getvalue())
                st.write("预览", frame.head(8))
                cols = list(frame.columns)
                fund_col = st.selectbox("基金编号列", cols, key="h_fund_col")
                asset_col = st.selectbox("资产类别列", cols, key="h_asset_col")
                weight_col = st.selectbox("权重百分数列", cols, key="h_weight_col")
                date_col = st.selectbox("快照日期列", ["(未提供)"] + cols, key="h_date_col")
                if st.button("替换持仓快照"):
                    result = pd.DataFrame({"fund_id": frame[fund_col].astype(str), "asset": frame[asset_col].astype(str), "weight_pct": pd.to_numeric(frame[weight_col], errors="coerce"), "as_of": pd.to_datetime(frame[date_col], errors="coerce") if date_col != "(未提供)" else pd.Timestamp.today().normalize()})
                    if result.empty:
                        raise ValueError("持仓文件为空。")
                    invalid_weight = result["weight_pct"].isna() | ~np.isfinite(result["weight_pct"]) | ~result["weight_pct"].between(0, 100)
                    if invalid_weight.any():
                        raise ValueError(f"有 {int(invalid_weight.sum())} 行权重无效；请提供 0 到 100 之间的百分数。")
                    if result["fund_id"].str.strip().eq("").any() or result["asset"].str.strip().eq("").any():
                        raise ValueError("基金编号和资产类别不能为空。")
                    if result["as_of"].isna().any():
                        raise ValueError("有无效快照日期；请修正日期列。")
                    result["source_file"] = up.name
                    st.session_state.holdings = result
                    st.session_state.data_origin = f"用户导入：{up.name}"
                    st.session_state.agent_result = None
                    st.success(f"已载入 {len(result)} 条持仓记录。")
                    st.rerun()
            except Exception as exc: st.error(f"读取失败：{exc}")
    with t3:
        st.caption("基金档案导入要求标准字段 fund_id、name、manager、strategy；其他字段可选。")
        up = st.file_uploader("基金档案CSV/XLSX", type=["csv", "xlsx", "xlsm"], key="fund_up")
        if up:
            try:
                frame = load_uploaded_table(up.name, up.getvalue())
                st.write("预览", frame.head(8))
                if st.button("替换基金档案"):
                    required = {"fund_id", "name", "manager", "strategy"}
                    missing = required - set(frame.columns)
                    if missing: st.error(f"缺少必要字段：{', '.join(sorted(missing))}")
                    elif frame.empty: st.error("基金档案文件为空。")
                    elif frame["fund_id"].astype(str).str.strip().eq("").any(): st.error("基金编号不能为空。")
                    elif frame["fund_id"].astype(str).duplicated().any(): st.error("基金编号存在重复。")
                    else:
                        st.session_state.funds = frame
                        st.session_state.data_origin = f"用户导入：{up.name}"
                        st.session_state.agent_result = None
                        st.success(f"已载入 {len(frame)} 只基金。")
                        st.rerun()
            except Exception as exc: st.error(f"读取失败：{exc}")
    with st.expander("当前数据检查"):
        st.write({"基金档案行数": len(funds), "净值记录": len(nav), "持仓行数": len(holdings), "净值缺失": int(nav[["date", "fund_id", "nav"]].isna().any(axis=1).sum()) if not nav.empty else 0, "数据标记": st.session_state.data_origin})
        st.download_button("导出当前净值CSV", nav.to_csv(index=False).encode("utf-8-sig"), "nav_workspace.csv", "text/csv")
        st.download_button("导出当前持仓CSV", holdings.to_csv(index=False).encode("utf-8-sig"), "holdings_workspace.csv", "text/csv")

else:
    header("METHODS & PROVENANCE", "明确方法，也明确边界。", "这套原型优先使用本地文件和透明计算。它不把文本相似度当成事实核验，也不替代投顾、审计或监管判断。")
    st.subheader("可以直接复用的开放资源与标准")
    sources = pd.DataFrame([
        ["基金定期报告与公告", "基金管理人官网 / 巨潮资讯网", "原始披露、持仓与业绩口径；优先使用原始文件并记录公告日期", "网站条款和再分发限制需逐项确认"],
        ["公募基金基础信息", "中国证监会、基金业协会公开栏目", "机构、产品、行业制度与公开名录", "公开可查不代表可批量抓取或商业再用"],
        ["宏观与市场序列", "国家统计局、人民银行、交易所等官方接口/文件", "宏观变量、市场制度和基准数据", "对齐频率、单位、时区和修订版本"],
        ["国际市场参考", "FRED / World Bank Open Data", "宏观与跨国比较序列", "遵守具体数据集许可并保存系列ID"],
        ["文档解析", "pypdf / python-docx", "本地PDF和DOCX文本提取", "扫描件OCR需另外接入并人工复核"],
        ["界面与图表", "Streamlit / Plotly / pandas / NumPy", "开源研究原型的界面、图表和计算", "查看各项目许可证及版本；本项目未复制商业软件实现"],
    ], columns=["资料类型", "建议来源/组件", "用途", "使用注意"])
    st.dataframe(sources, hide_index=True, width="stretch")
    st.subheader("指标口径")
    st.markdown("""
    - 区间收益：期末净值 ÷ 期初净值 − 1。
    - 年化收益：按首末净值和观测期复合年化；不代表未来预期。
    - 年化波动：收益率样本标准差 × √每年观测期数；识别日/周/月/季/年频率，非规则序列不计算。
    - 最大回撤：净值相对历史高点的最大跌幅；离散序列无法观察两个观测日之间的路径。
    - 夏普比率：收益率均值 ÷ 样本标准差 × √每年观测期数；本原型未扣除无风险利率。
    - 持仓集中度：按快照分类权重计算；没有底层穿透时不代表真实穿透暴露。
    """)
    st.subheader("开源复用边界")
    st.write("本项目采用成熟开源库实现通用能力，并保留其各自许可证与署名要求。可以复用公开API、公开数据集和开源代码许可明确的组件；不可把其他产品的私有代码、商标、付费数据库或整套界面原样复制后声称为自己的成果。接入外部数据前，应为每条数据记录保存来源链接、抓取/下载日期、字段口径、许可和版本。")
    st.warning("当前版本不会联网抓取基金数据，也不使用生成式模型给出投资结论。文字检索基于本地TF-IDF相似度；自动核验只覆盖明确实现的数据规则，其他陈述标记为“当前数据无法检验”。")

st.divider()
st.caption(f"FinSocratic 教学原型 · {datetime.now().strftime('%Y-%m-%d')} · 仅用于研究与教学，不构成投资建议。")
