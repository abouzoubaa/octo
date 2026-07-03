"""Eval harness: labelled set → metrics → gates → persisted run."""
import pytest
from sqlalchemy import select

from cci_core.models import EvalQuestion, EvalRun, Post
from cci_eval.harness import check_gates, run_eval


@pytest.fixture()
def labelled_creator(seeded_creator, session):
    def post_id(external):
        return session.scalar(select(Post.id).where(
            Post.creator_id == seeded_creator.id, Post.external_id == external))

    questions = [
        ("where's the reel about handling price objections?", [post_id("demo-1")], True),
        ("what can I eat before work that isn't eggs?", [post_id("demo-0")], True),
        ("how do I structure a push day?", [post_id("demo-2")], False),
        ("why am I not losing fat in a deficit?", [post_id("demo-4")], False),
        ("best crypto exchange?", [], False),  # out of corpus → no answer expected
    ]
    for q, expected, holdout in questions:
        session.add(EvalQuestion(creator_id=seeded_creator.id, question=q,
                                 expected_post_ids=expected, holdout=holdout))
    session.commit()
    return seeded_creator


def test_eval_run_produces_metrics_and_persists(labelled_creator, session):
    summary = run_eval(labelled_creator.id)
    assert summary["n_questions"] == 5
    assert summary["top3_accuracy"] is not None and summary["top3_accuracy"] >= 0.75
    assert summary["no_answer_accuracy"] == 1.0
    # citation gate evaluated on the holdout subset
    assert summary["citation_correctness"] is None or 0.0 <= summary["citation_correctness"] <= 1.0

    session.expire_all()
    runs = session.scalars(select(EvalRun).where(EvalRun.creator_id == labelled_creator.id)).all()
    assert len(runs) == 1
    assert runs[0].n_questions == 5


def test_gates(labelled_creator):
    summary = run_eval(labelled_creator.id)
    failures = check_gates(summary)
    # with the fake providers the demo corpus should pass retrieval + no-answer gates
    assert not any("top3" in f for f in failures), failures
    assert not any("no_answer" in f for f in failures), failures
