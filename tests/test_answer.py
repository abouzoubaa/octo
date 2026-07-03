"""Grounded answer card: citations required, no-answer state honoured."""
from cci_retrieval.answer import generate_answer, persist_answer


def test_answer_card_cites_sources(seeded_creator, session):
    card = generate_answer(session, seeded_creator.id, "how do I handle price objections?")
    assert card.state == "answered"
    assert card.text
    assert card.citations, "an uncited answer must be refused"
    assert all(c["post_id"] for c in card.citations)


def test_no_strong_answer_for_out_of_corpus_question(seeded_creator, session):
    card = generate_answer(session, seeded_creator.id, "what is your favourite quantum chromodynamics paper?")
    assert card.state == "no_strong_answer"
    assert card.text is None


def test_empty_corpus_returns_no_answer(creator, session):
    card = generate_answer(session, creator.id, "anything at all?")
    assert card.state == "no_strong_answer"
    assert card.confidence == 0.0


def test_persist_answer_roundtrip(seeded_creator, session):
    card = generate_answer(session, seeded_creator.id, "push day workout")
    answer = persist_answer(session, seeded_creator.id, card)
    session.commit()
    assert answer.id
    assert answer.creator_id == seeded_creator.id
    assert answer.state.value == card.state
