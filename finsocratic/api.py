"""Local API and application server for the FinSocratic research workbench."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from .agent import augment_with_ai, render_markdown, run_diligence
from .data import SAMPLE_DIR, load_uploaded_table
from .storage import WorkspaceStore, json_safe


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "frontend" / "dist"
store = WorkspaceStore()
app = FastAPI(title="FinSocratic Research API", version="2.0.0", docs_url="/api/docs", redoc_url=None)


@app.on_event('startup')
def recover_research_tasks():
    from .research_chat import recover_interrupted
    recover_interrupted()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173", "http://127.0.0.1:8501", "http://localhost:8501"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type"],
)


def _bad_input(error: Exception) -> HTTPException:
    return HTTPException(status_code=422, detail=str(error))


def _require_fund(fund_id: str) -> dict[str, Any]:
    fund = store.get_fund(fund_id)
    if fund is None:
        raise HTTPException(status_code=404, detail=f"找不到基金 {fund_id}。")
    return fund


def _document_for_agent(document_id: str, fund_id: str) -> dict[str, Any]:
    document = store.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail=f"找不到资料 {document_id}。")
    if document["fund_id"] != fund_id:
        raise HTTPException(status_code=422, detail="资料与当前基金不匹配。")
    return {"name": document["name"], "chunks": document["chunks"]}


def _parse_list(value: str | None, label: str) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=422, detail=f"{label} 必须是 JSON 数组。") from error
    if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
        raise HTTPException(status_code=422, detail=f"{label} 必须是字符串数组。")
    return parsed


def _run(
    fund_id: str,
    current_docs: list[dict[str, Any]],
    prior_docs: list[dict[str, Any]],
    *,
    benchmark: pd.DataFrame | None = None,
    factors: pd.DataFrame | None = None,
    is_demo: bool = False,
    use_ai: bool = False,
    input_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fund = _require_fund(fund_id)
    result = run_diligence(
        fund, store.nav_frame(fund_id), store.holdings_frame(fund_id), current_docs,
        benchmark=benchmark, prior_documents=prior_docs, factors=factors,
    )
    if use_ai:
        result = augment_with_ai(result, include_red_team=True)
    result["is_demo"] = is_demo
    result["source_manifest"] = {
        "current_reports": [doc["name"] for doc in current_docs],
        "prior_reports": [doc["name"] for doc in prior_docs],
        "benchmark": sorted(set(benchmark["source_file"].astype(str))) if benchmark is not None and "source_file" in benchmark else [],
        "factors": "Kenneth R. French 5-factor（月频）" if factors is not None and not factors.empty else [],
    }
    return store.save_run(fund_id, result, input_meta or {})


def _demo_run() -> dict[str, Any]:
    fund_id = "FOF-001"
    docs = store.list_documents(fund_id)
    current = next((doc for doc in docs if doc["name"] == "FOF-001_2025Q4.txt"), None)
    if current is None:
        current = next((doc for doc in docs if doc["period"] == "current"), None)
    prior = next((doc for doc in docs if doc["name"] == "FOF-001_2025Q2.txt"), None)
    current_docs = [_document_for_agent(current["id"], fund_id)] if current else []
    prior_docs = [_document_for_agent(prior["id"], fund_id)] if prior else []
    sample_benchmark = SAMPLE_DIR / "benchmark_monthly.csv"
    benchmark = pd.read_csv(sample_benchmark, parse_dates=["date"]) if sample_benchmark.exists() else None
    if benchmark is not None:
        benchmark["source_file"] = "benchmark_monthly.csv（合成演示）"
    return _run(fund_id, current_docs, prior_docs, benchmark=benchmark, is_demo=True,
                input_meta={"mode": "synthetic_demo", "report_ids": [current["id"]] if current else []})


def _auto_market_context(fund_id: str) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    """Auto-fetch a benchmark index and Fama-French factors for public-market funds.

    Cached by ``market_data``; a failure degrades gracefully to no benchmark/factors
    instead of failing the whole audit.
    """
    if not fund_id.startswith("CN-"):
        return None, None
    from .market_data import fetch_fama_french_5f, fetch_index_daily

    benchmark = factors = None
    try:
        benchmark = fetch_index_daily("沪深300", start="20150101")
    except Exception:
        benchmark = None
    try:
        factors = fetch_fama_french_5f()
    except Exception:
        factors = None
    return benchmark, factors


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/llm/status")
def llm_status() -> dict[str, Any]:
    from .llm import status
    return status()


@app.get("/api/workspace")
def workspace() -> dict[str, Any]:
    if not store.list_runs():
        _demo_run()
    return store.workspace()


@app.get("/api/funds/{fund_id}")
def fund_details(fund_id: str) -> dict[str, Any]:
    _require_fund(fund_id)
    return next(fund for fund in store.workspace()["funds"] if fund["fund_id"] == fund_id)


@app.get("/api/managers")
def managers() -> list[dict[str, Any]]:
    return store.workspace()["managers"]


class TaskUpdate(BaseModel):
    status: Literal["open", "in_progress", "resolved"]
    resolution_note: str | None = Field(default=None, max_length=4000)


class CopilotRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    fund_id: str | None = None


@app.get("/api/tasks")
def list_tasks(fund_id: str | None = None, run_id: str | None = None) -> list[dict[str, Any]]:
    return store.list_tasks(fund_id, run_id)


@app.patch("/api/tasks/{task_id}")
def update_task(task_id: str, update: TaskUpdate) -> dict[str, Any]:
    task = store.update_task(task_id, update.status, update.resolution_note)
    if task is None:
        raise HTTPException(status_code=404, detail="找不到这项跟进任务。")
    return task


@app.get("/api/search")
def search_sources(q: str = Query(..., min_length=1, max_length=500), fund_id: str | None = None,
                   limit: int = Query(12, ge=1, le=50)) -> dict[str, Any]:
    if fund_id:
        _require_fund(fund_id)
    return {"query": q, "results": store.search_documents(q, fund_id, limit),
            "notice": "匹配分数仅表示文字相关性；请打开原文位置核对，不代表真实性或因果关系。"}


@app.post("/api/copilot")
def research_copilot(request: CopilotRequest) -> dict[str, Any]:
    from .copilot import answer_research

    if request.fund_id:
        _require_fund(request.fund_id)
    if not request.question.strip():
        raise HTTPException(status_code=422, detail="请输入研究问题。")
    latest_runs = []
    seen = set()
    for summary in store.list_runs(request.fund_id):
        if summary["fund_id"] in seen:
            continue
        seen.add(summary["fund_id"])
        result = store.get_run(summary["id"])
        if result:
            latest_runs.append(result)
    return json_safe(answer_research(request.question.strip(), request.fund_id, store.workspace(),
                                    store.full_documents(request.fund_id), latest_runs))


@app.get("/api/runs")
def list_runs(fund_id: str | None = None) -> list[dict[str, Any]]:
    return store.list_runs(fund_id)


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    result = store.get_run(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="找不到这次审计记录。")
    return result


@app.post("/api/runs/demo")
def run_demo() -> dict[str, Any]:
    return _demo_run()


@app.post("/api/runs")
async def create_run(
    fund_id: str = Form(...),
    report: UploadFile | None = File(None),
    prior_report: UploadFile | None = File(None),
    benchmark: UploadFile | None = File(None),
    extra_text: str = Form(""),
    document_ids: str = Form("[]"),
    prior_document_ids: str = Form("[]"),
    benchmark_mapping: str = Form("{}"),
    use_ai: bool = Form(False),
    experimental_market_context: bool = Form(False),
) -> dict[str, Any]:
    _require_fund(fund_id)
    selected_ids = _parse_list(document_ids, "document_ids")
    selected_prior_ids = _parse_list(prior_document_ids, "prior_document_ids")
    current_docs = [_document_for_agent(document_id, fund_id) for document_id in selected_ids]
    prior_docs = [_document_for_agent(document_id, fund_id) for document_id in selected_prior_ids]
    try:
        if report is not None:
            saved = store.add_document(fund_id, report.filename or "report.txt", await report.read(), period="current")
            current_docs.append({"name": saved["name"], "chunks": saved["chunks"]})
        if prior_report is not None:
            saved = store.add_document(fund_id, prior_report.filename or "prior.txt", await prior_report.read(), period="prior")
            prior_docs.append({"name": saved["name"], "chunks": saved["chunks"]})
        if extra_text.strip():
            current_docs.append({"name": "手工输入陈述", "chunks": [
                {"location": f"第 {index} 行", "text": text}
                for index, text in enumerate(extra_text.splitlines(), 1) if text.strip()
            ]})
        if not current_docs:
            fallback = next((doc for doc in store.list_documents(fund_id) if doc["period"] == "current"), None)
            if fallback:
                current_docs.append(_document_for_agent(fallback["id"], fund_id))
        if not current_docs:
            raise ValueError("请上传现期报告、选择资料库文件，或输入待核对陈述。")
        benchmark_frame = None
        factors = None
        auto_context = False
        if benchmark is not None:
            benchmark_raw = await benchmark.read()
            benchmark_frame = load_uploaded_table(benchmark.filename or "benchmark.csv", benchmark_raw)
            try:
                mapping = json.loads(benchmark_mapping)
            except json.JSONDecodeError as error:
                raise ValueError("benchmark_mapping 必须为 JSON 对象。") from error
            if not isinstance(mapping, dict):
                raise ValueError("benchmark_mapping 必须为 JSON 对象。")
            date_col = mapping.get("date") or next((col for col in ("date", "日期") if col in benchmark_frame.columns), None)
            nav_col = mapping.get("nav") or next((col for col in ("nav", "净值", "benchmark_nav", "close") if col in benchmark_frame.columns), None)
            if date_col not in benchmark_frame or nav_col not in benchmark_frame:
                raise ValueError("基准文件需要可映射的日期列和净值列。")
            benchmark_frame = benchmark_frame.rename(columns={date_col: "date", nav_col: "nav"})
            benchmark_frame["source_file"] = Path(benchmark.filename or "benchmark.csv").name
        elif fund_id.startswith("CN-") and experimental_market_context:
            benchmark_frame, factors = await asyncio.to_thread(_auto_market_context, fund_id)
            auto_context = benchmark_frame is not None or factors is not None
        return await asyncio.to_thread(
            _run, fund_id, current_docs, prior_docs,
            benchmark=benchmark_frame, factors=factors, use_ai=use_ai,
            input_meta={"mode": "user_run", "selected_document_ids": selected_ids,
                        "selected_prior_document_ids": selected_prior_ids,
                        "uploaded_report": report.filename if report else None,
                        "uploaded_prior_report": prior_report.filename if prior_report else None,
                        "uploaded_benchmark": benchmark.filename if benchmark else None,
                        "auto_market_context": auto_context, "use_ai": use_ai},
        )
    except (ValueError, TypeError, KeyError) as error:
        raise _bad_input(error) from error


@app.post("/api/documents")
async def upload_document(file: UploadFile = File(...), fund_id: str = Form(...), period: str = Form("current")) -> dict[str, Any]:
    try:
        raw=await file.read(50*1024*1024+1)
        document = store.add_document(fund_id, file.filename or "document.txt", raw, period=period)
        from .source_archive import archive
        archive(document,raw)
    except (ValueError, TypeError) as error:
        raise _bad_input(error) from error
    return {key: value for key, value in document.items() if key != "chunks"} | {"chunks_count": len(document["chunks"])}


@app.get("/api/documents/{document_id}")
def get_document(document_id: str) -> dict[str, Any]:
    document = store.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="找不到这份资料。")
    return document


@app.get("/api/reports/{run_id}")
def download_report(run_id: str, format: str = Query("markdown", pattern="^(markdown|json)$")):
    result = store.get_run(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="找不到这次审计记录。")
    prefix = result["fund"]["fund_id"]
    if format == "json":
        return JSONResponse(result, headers={"Content-Disposition": f'attachment; filename="{prefix}_evidence.json"'})
    return PlainTextResponse(render_markdown(result), media_type="text/markdown; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{prefix}_diligence.md"'})


def _mapping(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=422, detail="mapping 必须是 JSON 对象。") from error
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=422, detail="mapping 必须是 JSON 对象。")
    return parsed


def _source_value(frame: pd.DataFrame, mapping: dict[str, Any], key: str, *, aliases: tuple[str, ...] = ()) -> list[Any]:
    selected = mapping.get(key)
    if selected is None:
        selected = next((candidate for candidate in (key, *aliases) if candidate in frame.columns), None)
    if selected is None:
        raise ValueError(f"请映射 {key} 列。")
    if selected in frame.columns:
        return frame[selected].tolist()
    if key == "fund_id":
        return [selected] * len(frame)
    raise ValueError(f"找不到映射列：{selected}。")


@app.post("/api/imports/{kind}")
async def import_table(kind: str, file: UploadFile = File(...), mapping: str = Form("{}")) -> dict[str, Any]:
    if kind not in {"funds", "nav", "holdings"}:
        raise HTTPException(status_code=404, detail="不支持该数据类型。")
    columns = _mapping(mapping)
    try:
        raw = await file.read()
        if len(raw) > 50 * 1024 * 1024:
            raise ValueError("文件不能超过 50 MB。")
        frame = load_uploaded_table(file.filename or "table.csv", raw, sheet_name=columns.get("sheet_name"))
        if frame.empty:
            raise ValueError("表格为空。")
        fields = {
            "funds": {"fund_id": (), "name": ("基金名称",), "manager": ("管理人",), "strategy": ("策略",)},
            "nav": {"fund_id": (), "date": ("日期",), "nav": ("净值", "累计净值")},
            "holdings": {"fund_id": (), "asset": ("资产类别",), "weight_pct": ("权重", "权重百分数"), "as_of": ("快照日期",)},
        }[kind]
        extracted = {field: _source_value(frame, columns, field, aliases=aliases) for field, aliases in fields.items()}
        records = []
        for index in range(len(frame)):
            record = {field: values[index] for field, values in extracted.items()}
            record["source_row"] = index + 2
            records.append(record)
        if kind == "funds":
            count = store.upsert_funds(records, source_file=file.filename or "funds.csv")
        elif kind == "nav":
            count = store.upsert_nav(records, source_file=file.filename or "nav.csv")
        else:
            count = store.upsert_holdings(records, source_file=file.filename or "holdings.csv")
        return {"imported": count, "kind": kind, "workspace": store.workspace()}
    except (ValueError, TypeError, KeyError, pd.errors.ParserError) as error:
        raise _bad_input(error) from error


@app.get("/api/market/search")
def market_search(q: str = Query("", max_length=80), fof_only: bool = True):
    from .market_data import search_funds
    try:
        frame = search_funds(q, kind="FOF" if fof_only else None)
        return {"results": frame.head(40).to_dict("records"), "total": len(frame),
                "provider": "东方财富 / 天天基金", "notice": "公开目录；结果排序不代表推荐。"}
    except Exception as error:
        raise HTTPException(status_code=502, detail="公开目录暂时无法访问，请稍后重试或使用文件导入。") from error


class MarketImport(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


@app.post("/api/market/import")
def market_import(request: MarketImport):
    from .market_data import fetch_fund_list, fetch_fund_nav, fund_source_manifest, fetch_manager_profile, fetch_fof_holdings
    try:
        matches = fetch_fund_list().loc[lambda frame: frame["code"] == request.code]
        if matches.empty:
            raise ValueError("公开目录中没有该基金。")
        item = matches.iloc[0]
        nav = fetch_fund_nav(request.code)
        if len(nav) < 3:
            raise ValueError("有效历史数据不足三个观测。")
        manifest = fund_source_manifest(request.code)
        profile = {"fund_id": f"CN-{request.code}", "name": item["name"],
                   "manager": f"待核对管理人 · {request.code}", "strategy": item["type"],
                   "description": manifest["return_basis"], "source_manifest": manifest,
                   "data_origin": "public_market", "inception": None}
        previous = store.get_fund(profile["fund_id"])
        if previous and previous.get("profile_disclosure"):
            profile.update({key: previous[key] for key in ("manager", "inception", "profile_disclosure")})
        try:
            manager_profile = fetch_manager_profile(request.code)
        except Exception:
            manager_profile = {}  # 经理任职为尽力而为，净值导入不应因它失败
        if manager_profile.get("current_managers"):
            profile.update(
                manager=" ".join(manager_profile["current_managers"]),
                inception=manager_profile.get("inception"),
                manager_start_date=manager_profile.get("manager_start_date"),
                manager_history=manager_profile.get("manager_history"),
                current_managers=manager_profile.get("current_managers"),
                manager_source_manifest={"source_url": manager_profile["source_url"],
                                         "sha256": manager_profile["sha256"],
                                         "retrieved_at": manager_profile["retrieved_at"]})
        try:
            fof = fetch_fof_holdings(request.code)
        except Exception:
            fof = {}  # 底层持仓为尽力而为，净值导入不应因它失败
        if fof.get("holdings"):
            profile.update(
                fof_holdings_count=len(fof["holdings"]),
                fof_holdings_report_date=fof.get("report_date"),
                fof_holdings_weight_sum=round(sum(h["weight_pct"] for h in fof["holdings"]), 2),
                fof_holdings_source_manifest={"source_url": fof["source_url"],
                                              "sha256": fof["sha256"],
                                              "retrieved_at": fof["retrieved_at"]})
        count = store.save_market_fund(profile, nav)
        if fof.get("holdings"):
            store.upsert_fof_holdings(
                [{"fund_id": profile["fund_id"], "target_code": h["target_code"],
                  "target_name": h["target_name"], "weight_pct": h["weight_pct"],
                  "report_date": fof["report_date"]} for h in fof["holdings"]],
                source_file=f"eastmoney_fof_{request.code}.json")
        return {"fund_id": profile["fund_id"], "imported": count, "start": nav.iloc[0]["date"],
                "end": nav.iloc[-1]["date"], "manifest": manifest,
                "fof_holdings": profile.get("fof_holdings_count", 0)}
    except ValueError as error:
        raise _bad_input(error) from error
    except Exception as error:
        raise HTTPException(status_code=502, detail="公开净值暂时无法获取，未保存不完整数据。请稍后重试。") from error


@app.post("/api/market/disclosure")
def import_public_disclosure(request: MarketImport):
    """Curated manager-origin report; fixed host/path prevents arbitrary URL fetching."""
    import hashlib
    from datetime import datetime, timezone
    from .market_data import CACHE_DIR, _get
    if request.code != "005215":
        raise HTTPException(status_code=422, detail="当前精选原始披露案例为 005215；其他基金可在资料库上传报告。")
    fid = f"CN-{request.code}"
    _require_fund(fid)
    url = "https://www.nffund.com/main/files/2025/07/18/448922561903.pdf"
    name = "005215_2025Q2_南方基金原始季报.pdf"
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = CACHE_DIR / name
        raw = path.read_bytes() if path.exists() else _get(url)
        if not raw.startswith(b"%PDF") or len(raw) > 25_000_000:
            raise ValueError("来源没有返回有效、大小合适的 PDF。")
        document = store.add_document(fid, name, raw, period="reference")
        if not path.exists():
            path.write_bytes(raw)
        meta = {"source_url": url, "sha256": hashlib.sha256(raw).hexdigest(),
                "downloaded_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(), "report_period": "2025-04-01 / 2025-06-30",
                "document_id": document["id"], "note": "历史原始披露案例，并非最新报告；表格抽取需人工核对。"}
        path.with_suffix(".source.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        store.add_document(fid, "005215_2025Q2_来源记录.txt", json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8"), period="reference")
        profile = store.get_fund(fid)
        profile.update(manager="南方基金（2025Q2披露）", inception="2017-10-19",
                       profile_disclosure={"source_url": url, "page": 2, "as_of": "2025-06-30"})
        store.upsert_funds([profile], source_file=name)
        return {"document_id": document["id"], "chunks_count": len(document["chunks"]), **meta}
    except (ValueError, TypeError) as error:
        raise _bad_input(error) from error
    except Exception as error:
        raise HTTPException(status_code=502, detail="原始披露下载失败，请稍后重试。") from error


class ComparisonRequest(BaseModel):
    fund_ids: list[str] = Field(min_length=2, max_length=8)
    start: str | None = None
    end: str | None = None


@app.post("/api/comparison")
def compare_workspace(request: ComparisonRequest):
    from .comparison import compare_funds
    try:
        ids = list(dict.fromkeys(request.fund_ids))
        funds = {f['fund_id']:f for f in store.workspace()['funds']}
        if any(fid not in funds for fid in ids):
            raise ValueError('存在未知基金编号。')
        return json_safe(compare_funds([funds[fid] for fid in ids], request.start, request.end))
    except (ValueError, TypeError) as error:
        raise _bad_input(error) from error


@app.get("/api/funds/{fund_id}/brief")
def export_fund_brief(fund_id: str):
    from .comparison import fund_brief
    _require_fund(fund_id)
    workspace = store.workspace()
    fund = next(f for f in workspace['funds'] if f['fund_id'] == fund_id)
    return PlainTextResponse(fund_brief(fund, workspace['tasks'], workspace['runs']),
                             media_type='text/markdown; charset=utf-8',
                             headers={'Content-Disposition':'attachment; filename="research_brief.md"'})


@app.get('/api/data-hub')
def data_hub_status():
    from .data_hub import status
    return status()


@app.post('/api/data-hub/collect')
def collect_data(background: BackgroundTasks):
    from .data_hub import collect, status, LOCK
    if not LOCK.locked():
        background.add_task(collect, store)
    return {'accepted':True,'status':status()}


@app.get('/api/documents/{document_id}/original')
def original_document(document_id: str):
    from .source_archive import original
    saved=original(document_id)
    if saved:
        return FileResponse(saved[0],filename=saved[1]['name'],media_type='application/octet-stream')
    from .data_hub import original_path
    path=original_path(document_id)
    if path is None:
        raise HTTPException(status_code=404,detail='此资料没有已归档的原始PDF。')
    return FileResponse(path,media_type='application/pdf')


@app.get('/api/research/bootstrap')
def research_bootstrap():
    from .research_chat import sessions
    from .llm import status
    funds=[{k:f.get(k) for k in ('fund_id','name','manager','strategy','is_sample')} for f in store.list_funds()]
    return {'funds':funds,'sessions':sessions(),'model':status()}


class ResearchQuestion(BaseModel):
    question: str = Field(min_length=2,max_length=3000)
    fund_id: str
    session_id: str | None = None


@app.post('/api/research/ask')
def start_research(request: ResearchQuestion, background: BackgroundTasks):
    from .research_chat import begin,execute
    from .llm import is_available
    _require_fund(request.fund_id)
    if not is_available():
        raise HTTPException(status_code=422,detail='请先在本机配置 DeepSeek，再开始AI研究。')
    try:
        session_id,turn_id=begin(request.question.strip(),request.fund_id,request.session_id)
        background.add_task(execute,store,session_id,turn_id,request.question.strip(),request.fund_id)
        return {'session_id':session_id,'turn_id':turn_id}
    except ValueError as error:
        raise _bad_input(error) from error


@app.get('/api/research/sessions/{session_id}')
def research_session(session_id: str):
    from .research_chat import get_session
    try:return get_session(session_id)
    except ValueError as error:raise HTTPException(status_code=404,detail=str(error)) from error


@app.get('/api/learning/status')
def learning_status():
    from .learning import status
    return json_safe(status())


@app.get('/api/learning/forward')
def forward_results():
    from .forward_validation import evaluate
    return json_safe(evaluate(store))


@app.post('/api/learning/forward')
def register_forward():
    from .forward_validation import freeze
    try:return json_safe(freeze(store))
    except ValueError as error:raise _bad_input(error)


@app.post('/api/learning/train')
def learning_train(background: BackgroundTasks):
    from .learning import train, LOCK
    if LOCK.locked():
        raise HTTPException(status_code=409, detail='训练正在运行，请等待完成。')
    background.add_task(train, store)
    return {'accepted': True}


@app.get('/api/learning/funds/{fund_id}')
def learning_fund(fund_id: str):
    _require_fund(fund_id)
    from .learning import fund_evidence
    return json_safe(fund_evidence(fund_id))


@app.get('/api/learning/funds/{fund_id}/dossier')
def learning_dossier(fund_id: str):
    """Export the auditable learning card as a portable researcher memo."""
    _require_fund(fund_id)
    from .learning import fund_evidence, status
    evidence = fund_evidence(fund_id)
    if evidence.get('status') != 'ready':
        raise HTTPException(status_code=404, detail=evidence.get('message', '暂无可导出的学习档案。'))
    report = status().get('report', {})
    card = evidence['card']; bayes = card.get('bayesian') or {}; diag = bayes.get('diagnostics') or {}
    robust = bayes.get('robustness') or {}
    readiness = card.get('research_readiness') or {}
    fund = store.get_fund(fund_id)
    def pct(value):
        return '—' if value is None else f'{float(value)*100:.2f}%'
    lines = [f"# {fund['name']} · 研究学习档案", '',
             f"- 生成时间：{datetime.now().astimezone().isoformat(timespec='seconds')}",
             f"- 研究对象：{fund_id}（代表份额：{evidence.get('representative_fund_id')}）",
             f"- 训练版本：{report.get('run_id')}", f"- 数据快照哈希：{report.get('snapshot_sha256')}",
             '', '## 研究判断', '', f"- 研究结论：{readiness.get('verdict')}",
             f"- 证据就绪度：{readiness.get('grade')}（{readiness.get('ready_count')}/{readiness.get('total')}）",
             f"- 贝叶斯 P(同类季度相对收益均值 > 0)：{pct(bayes.get('probability_positive_mean'))}",
             f"- 95% 可信区间：{pct((bayes.get('credible_interval_95') or [None])[0])} 至 {pct((bayes.get('credible_interval_95') or [None,None])[1])}",
             f"- 神经网络状态：{card.get('neural',{}).get('status')}",
             '', '## 归因稳定性', '', f"- 正收益季度占比：{pct(diag.get('positive_quarter_share'))}",
             f"- 正收益四季度窗口占比：{pct(diag.get('positive_4q_block_share'))}",
             f"- 前半段 / 后半段 / 最近8季度：{pct(diag.get('period_means',{}).get('first_half'))} / {pct(diag.get('period_means',{}).get('second_half'))} / {pct(diag.get('period_means',{}).get('recent_8q'))}",
             f"- 留一季度均值范围：{pct((robust.get('leave_one_quarter_out_range') or [None])[0])} 至 {pct((robust.get('leave_one_quarter_out_range') or [None,None])[1])}",
             f"- 三种同类基准方向一致：{robust.get('benchmark_agreement')}", '', '### 三种基准', '']
    for name, item in (robust.get('benchmarks') or {}).items():
        lines.append(f"- {name}：均值超额 {pct(item.get('mean_excess'))}；Bootstrap CI {pct(item.get('bootstrap_ci_95',[None])[0])} 至 {pct(item.get('bootstrap_ci_95',[None,None])[1])}；均值为正概率 {pct(item.get('bootstrap_positive_mean'))}")
    lines += ['', '## 证据就绪度逐项检查', '']
    for check in readiness.get('checks', []):
        lines.append(f"- [{'x' if check.get('ready') else ' '}] {check.get('label')}：{check.get('detail')}")
    lines += ['', '## 下一步最有价值的证据', '']
    lines.extend(f"- {item}" for item in readiness.get('next_best_evidence', []))
    lines += ['', '## 方法与边界', '']
    lines.extend(f"- {item}" for item in evidence.get('limitations', []))
    lines += ['', f"- 数据与模型目录：{report.get('storage')}", '']
    return PlainTextResponse('\n'.join(lines), media_type='text/markdown; charset=utf-8',
                             headers={'Content-Disposition': f'attachment; filename="{fund_id}-research-dossier.md"'})


@app.get('/api/research/sessions/{session_id}/print')
def printable_research(session_id: str):
    from .research_chat import get_session
    from fastapi.responses import HTMLResponse
    from html import escape
    try:
        session=get_session(session_id)
    except ValueError as error:
        raise HTTPException(status_code=404,detail=str(error)) from error
    sections=[]
    for turn in session['turns']:
        p=turn['payload']
        if turn['state']!='complete':continue
        citations=''.join('<li><b>'+escape(c['id']+' · '+c['source']+' · '+c['location'])+'</b><pre>'+escape(c['text'])+'</pre></li>' for c in p.get('citations',[]))
        sections.append('<section><h2>'+escape(turn['question'])+'</h2><p>'+escape(turn['created_at'])+'</p><p>'+escape(p.get('evidence_delta',{}).get('summary','历史版本未记录输入快照'))+'</p><pre>'+escape(p.get('answer',''))+'</pre><h3>原始证据附件</h3><ol>'+citations+'</ol></section>')
    return HTMLResponse('<!doctype html><html lang="zh"><meta charset="utf-8"><title>FinSocratic研究档案</title><style>body{max-width:900px;margin:40px auto;font:15px/1.8 sans-serif;color:#172b35}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}h1,h2{color:#137c70}section{break-before:page}li{margin:18px 0}button{padding:10px 20px}@media print{button{display:none}body{margin:15mm}pre{font-size:11pt}}</style><button onclick="window.print()">打印 / 保存为 PDF</button><h1>'+escape(session['title'])+'</h1><p>研究对象：'+escape(session['fund_id'])+' · 历史版本及原始证据随报告保留</p>'+''.join(sections)+'</html>')


@app.get("/{path:path}", include_in_schema=False)
def serve_frontend(path: str):
    if path.startswith("api/"):
        raise HTTPException(status_code=404, detail="未知 API。")
    if not DIST.exists():
        return JSONResponse({"message": "前端尚未构建。请在 frontend 目录运行 npm install && npm run build。",
                             "api": "/api/workspace"}, status_code=503)
    target = (DIST / path).resolve()
    if path and target.is_file() and DIST.resolve() in target.parents:
        return FileResponse(target)
    return FileResponse(DIST / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("finsocratic.api:app", host="127.0.0.1", port=8501, reload=False)
