"""Evaluation harness.

Metrics:
- top3_accuracy        — expected post appears in the top-3 retrieval results
- citation_correctness — answer cards cite only expected posts (held-out set)
- no_answer_accuracy   — questions labelled "no answer" actually return the
                         no_strong_answer state

Usage:
  cci-eval run <creator_handle> [--gate]      # --gate exits non-zero below thresholds
  cci-eval import <creator_handle> questions.yaml
  cci-eval history <creator_handle>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys

import yaml
from sqlalchemy import select

from cci_core.config import get_settings
from cci_core.db import session_scope
from cci_core.models import AnswerState, Creator, EvalQuestion, EvalRun
from cci_retrieval.answer import generate_answer
from cci_retrieval.search import search

# Gates (plan §5–6): retrieval must beat native IG search on the labelled set,
# and citation correctness gates comment-to-DM automation.
GATE_TOP3 = 0.70
GATE_CITATIONS = 0.90
GATE_NO_ANSWER = 0.80


def run_eval(creator_id: str) -> dict:
    results = {
        "top3": {"hit": 0, "total": 0, "misses": []},
        "citations": {"correct": 0, "total": 0, "holdout": 0, "wrong": []},
        "no_answer": {"correct": 0, "total": 0, "wrong": []},
    }
    with session_scope() as session:
        questions = session.scalars(
            select(EvalQuestion).where(EvalQuestion.creator_id == creator_id)
        ).all()
        if not questions:
            raise SystemExit("no eval questions — import a labelled set first")

        for q in questions:
            expected = set(q.expected_post_ids or [])
            if not expected:
                # labelled "no good answer in the corpus"
                card = generate_answer(session, creator_id, q.question)
                results["no_answer"]["total"] += 1
                if card.state == AnswerState.no_strong_answer.value:
                    results["no_answer"]["correct"] += 1
                else:
                    results["no_answer"]["wrong"].append(q.question)
                continue

            hits = search(session, creator_id, q.question, top_k=3)
            results["top3"]["total"] += 1
            if expected & {h.post_id for h in hits}:
                results["top3"]["hit"] += 1
            else:
                results["top3"]["misses"].append(q.question)

            if q.holdout:  # citation gate runs on the held-out subset
                results["citations"]["holdout"] += 1
                card = generate_answer(session, creator_id, q.question)
                if card.state == AnswerState.answered.value:
                    results["citations"]["total"] += 1
                    cited = {c["post_id"] for c in card.citations}
                    if cited and cited <= expected:
                        results["citations"]["correct"] += 1
                    else:
                        results["citations"]["wrong"].append(q.question)

    def rate(d: dict, num: str, den: str = "total") -> float | None:
        return round(d[num] / d[den], 3) if d[den] else None

    summary = {
        "n_questions": sum(results[k]["total"] for k in results),
        "holdout_questions": results["citations"]["holdout"],
        "top3_accuracy": rate(results["top3"], "hit"),
        "citation_correctness": rate(results["citations"], "correct"),
        "no_answer_accuracy": rate(results["no_answer"], "correct"),
        "details": results,
    }
    _persist(creator_id, summary)
    return summary


def _persist(creator_id: str, summary: dict) -> None:
    s = get_settings()
    config_blob = json.dumps({
        "embedding": [s.embedding_provider, s.embedding_model, s.embedding_version],
        "llm": [s.llm_provider, s.llm_model],
        "thresholds": [s.answer_min_confidence, s.dm_min_confidence],
        "k": [s.search_top_k, s.rerank_candidates],
    }, sort_keys=True)
    with session_scope() as session:
        session.add(EvalRun(
            creator_id=creator_id,
            git_sha=_git_sha(),
            config_hash=hashlib.sha256(config_blob.encode()).hexdigest()[:16],
            top3_accuracy=summary["top3_accuracy"],
            citation_correctness=summary["citation_correctness"],
            no_answer_accuracy=summary["no_answer_accuracy"],
            n_questions=summary["n_questions"],
            details=summary["details"],
        ))


def _git_sha() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return None


def check_gates(summary: dict) -> list[str]:
    failures = []
    if summary["top3_accuracy"] is not None and summary["top3_accuracy"] < GATE_TOP3:
        failures.append(f"top3_accuracy {summary['top3_accuracy']} < {GATE_TOP3}")
    if summary["citation_correctness"] is not None and summary["citation_correctness"] < GATE_CITATIONS:
        failures.append(f"citation_correctness {summary['citation_correctness']} < {GATE_CITATIONS}")
    elif summary["citation_correctness"] is None and summary.get("holdout_questions", 0) > 0:
        # vacuous pass: held-out questions exist but NONE were answerable → the gate
        # that certifies citation quality has nothing to certify. Fail closed.
        failures.append(
            f"citation gate vacuous: {summary['holdout_questions']} held-out questions, "
            "0 answered (corpus cites nothing)")
    if summary["no_answer_accuracy"] is not None and summary["no_answer_accuracy"] < GATE_NO_ANSWER:
        failures.append(f"no_answer_accuracy {summary['no_answer_accuracy']} < {GATE_NO_ANSWER}")
    return failures


def import_questions(creator_id: str, path: str) -> int:
    """YAML format: [{question, expected_post_ids: [...], holdout: bool}] —
    expected_post_ids may reference posts by external_id (resolved here)."""
    with open(path) as fh:
        items = yaml.safe_load(fh)
    count = 0
    with session_scope() as session:
        from cci_core.models import Post

        for item in items:
            expected = []
            for ref in item.get("expected_post_ids", []):
                post = session.get(Post, ref) or session.scalar(
                    select(Post).where(Post.creator_id == creator_id,
                                       Post.external_id == str(ref)))
                if post:
                    expected.append(post.id)
            session.add(EvalQuestion(
                creator_id=creator_id,
                question=item["question"],
                expected_post_ids=expected,
                holdout=bool(item.get("holdout", False)),
                labelled_by=item.get("labelled_by"),
            ))
            count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(prog="cci-eval")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("handle")
    p.add_argument("--gate", action="store_true")
    p = sub.add_parser("import")
    p.add_argument("handle")
    p.add_argument("path")
    p = sub.add_parser("history")
    p.add_argument("handle")
    args = parser.parse_args()

    with session_scope() as session:
        creator = session.scalar(select(Creator).where(Creator.handle == args.handle))
        if creator is None:
            raise SystemExit(f"creator '{args.handle}' not found")
        creator_id = creator.id

    if args.cmd == "run":
        summary = run_eval(creator_id)
        print(json.dumps({k: v for k, v in summary.items() if k != "details"}, indent=2))
        if args.gate:
            failures = check_gates(summary)
            if failures:
                print("GATE FAILED:\n  " + "\n  ".join(failures), file=sys.stderr)
                raise SystemExit(1)
            print("all gates passed ✔")
    elif args.cmd == "import":
        print(f"imported {import_questions(creator_id, args.path)} questions")
    elif args.cmd == "history":
        with session_scope() as session:
            runs = session.scalars(
                select(EvalRun).where(EvalRun.creator_id == creator_id)
                .order_by(EvalRun.created_at.desc()).limit(20)
            ).all()
            for r in runs:
                print(f"{r.created_at:%Y-%m-%d %H:%M} sha={str(r.git_sha)[:8]} "
                      f"top3={r.top3_accuracy} citations={r.citation_correctness} "
                      f"no_answer={r.no_answer_accuracy} n={r.n_questions}")


if __name__ == "__main__":
    main()
