"""评测：把「答得对」和「说得清」拆成两个数，一起报。

指标：
  dept_acc      科室准确率（结论里的 dept 是否命中 gold）
  exam_recall   检查项召回（gold 里任一检查是否进了结论）
  completeness  溯源完整率均值（每条结论的证据能不能核对到）
  avg_steps     决策链平均步数
  avg_ms        端到端耗时

用法：
    python -m app.seed            # 先灌数据
    python eval/run_eval.py --json eval/report.json

    # A2 消融：检索 × 模型 两维四组（未配置的云端项诚实回落，不抛异常）
    python eval/run_eval.py --retriever bm25      --llm offline
    python eval/run_eval.py --retriever bm25      --llm modelarts
    python eval/run_eval.py --retriever koosearch --llm offline
    python eval/run_eval.py --retriever koosearch --llm modelarts
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages" / "core"))
sys.path.insert(0, str(REPO / "apps" / "api"))

from app.pipeline import answer  # noqa: E402
from medpal_core.config import settings  # noqa: E402
from medpal_core.llm.base import build_llm  # noqa: E402
from medpal_core.ontology import version as onto_version  # noqa: E402
from medpal_core.retrieval import build_retriever  # noqa: E402
from medpal_core.storage import connect  # noqa: E402

RETRIEVER_CHOICES = ("bm25", "koosearch")
LLM_CHOICES = ("offline", "modelarts")
CLOUD_LLM_PROVIDERS = {"modelarts", "openai", "pangu", "huawei"}


def load(path: Path) -> list:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _score_completeness(out: dict) -> float:
    """评测口径：没有证据的答案不算「可追溯」，直接记 0。

    trace.writer 里「无引用 = 1.0」是为了不冤枉纯推理步；
    但评测问的是「这条结论有没有证据撑着」，两者不能混。
    """
    if not out.get("evidence_count"):
        return 0.0
    return float(out.get("trace_completeness") or 0.0)


def dataset_path(name: str = "") -> Path:
    """--dataset 指定 v1/v2；不指定优先 v2（扩到 30/60 条后自动切），没有再退回 v1。"""
    folder = REPO / "eval" / "dataset"
    if name:
        p = folder / (name if name.endswith(".jsonl") else name + ".jsonl")
        if not p.exists():
            raise SystemExit(f"数据集不存在：{p}")
        return p
    for cand in ("v2.jsonl", "v1.jsonl"):
        if (folder / cand).exists():
            return folder / cand
    raise SystemExit(f"{folder} 下没有 jsonl 数据集")


def make_retriever(conn, kind: str = ""):
    """返回 (retriever, 实际后端, 提示)。None 表示用 pipeline 默认的 BM25。

    消融要求：koosearch 没配也要能跑完 —— 此时保留 koosearch 实例（召回为空），
    并把「未配置」明确打印出来，不偷偷换成 bm25 冒充云端结果。
    """
    if kind in ("", "bm25"):
        return None, "bm25", ""
    try:
        rt = build_retriever(conn, kind)
    except Exception as exc:  # 依赖缺失等
        return None, "bm25", f"{kind} 初始化失败（{exc}），回落 bm25"
    if not getattr(rt, "available", lambda: True)():
        return rt, kind, f"{kind} 未配置（缺 HUAWEI_KOOSEARCH_ENDPOINT），召回为空"
    return rt, kind, ""


def make_llm(kind: str = ""):
    """返回 (llm, 实际模型, 提示)。None 表示离线（pipeline 不挂模型）。"""
    if kind in ("", "offline"):
        return None, "offline", ""
    cfg = settings()
    provider = (cfg.llm_provider or "offline").strip().lower()
    if kind != "modelarts":
        return None, "offline", f"未知模型 {kind}，回落 offline"
    if provider in CLOUD_LLM_PROVIDERS and cfg.llm_base_url:
        try:
            return build_llm(cfg), provider, ""
        except Exception as exc:
            return None, "offline", f"modelarts 初始化失败（{exc}），回落 offline"
    return None, "offline", "modelarts 未配置（MEDPAL_LLM_BASE_URL 为空），回落 offline"


def run(db_path: str = "", dataset: str = "", retriever_kind: str = "",
        llm_kind: str = "") -> dict:
    conn = connect(db_path or None)
    try:
        path = dataset_path(dataset)
        rows = load(path)
        retriever, retriever_actual, retriever_note = make_retriever(conn, retriever_kind)
        llm, llm_actual, llm_note = make_llm(llm_kind)
        for note in (retriever_note, llm_note):
            if note:
                print(f"[warn] {note}")
        cases = []
        for row in rows:
            out = answer(conn, row["q"], retriever=retriever, llm=llm)
            conc = out.get("conclusion") or {}
            dept_ok = bool(row.get("dept")) and row["dept"] == conc.get("dept")
            exam_ok = (not row.get("exams")) or any(
                e in (conc.get("exams") or []) for e in row["exams"])
            cases.append({
                "q": row["q"],
                "dept_ok": dept_ok,
                "exam_ok": exam_ok,
                "trace_id": out.get("trace_id"),
                "completeness": _score_completeness(out),
                "steps": len(out.get("paths") or []),
                "elapsed_ms": out.get("elapsed_ms"),
                "llm_error": (out.get("conclusion") or {}).get("llm_error"),
            })
        n = max(1, len(cases))
        cur = onto_version.current_version(conn)
        return {
            "ontology_version": (cur or {}).get("version"),
            "dataset": path.name,
            "n": len(cases),
            "retriever": {"requested": retriever_kind or "bm25", "actual": retriever_actual},
            "llm": {"requested": llm_kind or "offline", "actual": llm_actual},
            "dept_acc": round(sum(c["dept_ok"] for c in cases) / n, 3),
            "exam_recall": round(sum(c["exam_ok"] for c in cases) / n, 3),
            "completeness": round(sum(c["completeness"] or 0 for c in cases) / n, 3),
            "zero_evidence": sum(1 for c in cases if not c["completeness"]),
            "llm_errors": sum(1 for c in cases if c["llm_error"]),
            "avg_steps": round(sum(c["steps"] for c in cases) / n, 2),
            "avg_ms": round(sum(c["elapsed_ms"] or 0 for c in cases) / n, 1),
            "cases": cases,
        }
    finally:
        conn.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="")
    ap.add_argument("--json", default="")
    ap.add_argument("--dataset", default="", help="v1 / v2 / 文件名，缺省自动挑最新的")
    ap.add_argument("--retriever", choices=RETRIEVER_CHOICES, default="",
                    help="bm25（缺省）/ koosearch")
    ap.add_argument("--llm", choices=LLM_CHOICES, default="",
                    help="offline（缺省）/ modelarts")
    args = ap.parse_args(argv)
    report = run(args.db, args.dataset, args.retriever, args.llm)
    for c in report["cases"]:
        flag = "OK " if (c["dept_ok"] and c["exam_ok"]) else "MISS"
        print(f"{flag} {c['q'][:30]:<32} completeness={c['completeness']}  {c['elapsed_ms']}ms")
    print("-" * 60)
    print(
        f"dept_acc={report['dept_acc']}  exam_recall={report['exam_recall']}  "
        f"completeness={report['completeness']}  avg_steps={report['avg_steps']}  "
        f"avg_ms={report['avg_ms']}  (n={report['n']}, dataset={report['dataset']}, "
        f"zero_evidence={report['zero_evidence']})"
    )
    print(
        f"retriever={report['retriever']['requested']}->{report['retriever']['actual']}  "
        f"llm={report['llm']['requested']}->{report['llm']['actual']}  "
        f"llm_errors={report['llm_errors']}"
    )
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                   encoding="utf-8")
        print("写入", args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
