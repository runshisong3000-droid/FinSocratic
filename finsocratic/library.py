"""Local document ingestion, persistence and evidence retrieval."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from docx import Document
from pypdf import PdfReader
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .data import UPLOADS

INDEX = UPLOADS.parent / "library.json"
ALLOWED = {".pdf", ".docx", ".txt"}


def extract_document(name: str, raw: bytes) -> list[dict]:
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED:
        raise ValueError("资料库目前支持 PDF、DOCX 和 TXT；净值表请在基金数据页上传 CSV/XLSX。")
    chunks = []
    if suffix == ".pdf":
        reader = PdfReader(__import__("io").BytesIO(raw))
        for number, page in enumerate(reader.pages, 1):
            text = (page.extract_text() or "").strip()
            if text:
                chunks.append({"location": f"第 {number} 页", "text": text})
        if not chunks:
            raise ValueError("没有提取到可搜索文本；该 PDF 可能是扫描件，当前演示版还没有 OCR。")
    elif suffix == ".docx":
        doc = Document(__import__("io").BytesIO(raw))
        for number, paragraph in enumerate(doc.paragraphs, 1):
            text = paragraph.text.strip()
            if text:
                chunks.append({"location": f"第 {number} 段", "text": text})
        for tnum, table in enumerate(doc.tables, 1):
            for rnum, row in enumerate(table.rows, 1):
                text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                if text:
                    chunks.append({"location": f"表格 {tnum} 第 {rnum} 行", "text": text})
    else:
        body = raw.decode("utf-8-sig", errors="replace")
        chunks = [{"location": f"第 {number} 行", "text": line.strip()} for number, line in enumerate(body.splitlines(), 1) if line.strip()]
    if not chunks:
        raise ValueError("文件中没有可供检索的文本。")
    return chunks


def load_library() -> list[dict]:
    if not INDEX.exists():
        return []
    try:
        return json.loads(INDEX.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def add_document(name: str, raw: bytes, chunks: list[dict]) -> tuple[bool, str]:
    UPLOADS.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(raw).hexdigest()
    items = load_library()
    if any(item["sha256"] == digest for item in items):
        return False, "这份文件已在资料库中。"
    safe_name = Path(name).name
    target = UPLOADS / f"{digest[:12]}_{safe_name}"
    target.write_bytes(raw)
    items.append({"name": safe_name, "sha256": digest, "stored_as": target.name, "size": len(raw), "added_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="minutes"), "chunks": chunks})
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    return True, f"已保存到本机资料库（{len(chunks)} 个文本片段）。"


def retrieve(query: str, documents: list[dict], limit: int = 8) -> list[dict]:
    corpus = [(doc, chunk) for doc in documents for chunk in doc["chunks"]]
    if not query.strip() or not corpus:
        return []
    texts = [chunk["text"] for _, chunk in corpus]
    try:
        vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(2, 4), max_features=50000, sublinear_tf=True)
        matrix = vectorizer.fit_transform(texts + [query])
        scores = cosine_similarity(matrix[-1], matrix[:-1]).ravel()
    except ValueError:
        return []
    ranked = sorted(range(len(corpus)), key=lambda i: float(scores[i]), reverse=True)
    result = []
    for idx in ranked:
        if scores[idx] <= 0:
            continue
        doc, chunk = corpus[idx]
        result.append({"file": doc["name"], "location": chunk["location"], "text": chunk["text"], "score": float(scores[idx])})
        if len(result) == limit:
            break
    return result
