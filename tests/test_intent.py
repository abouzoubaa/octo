from cci_retrieval.intent import INTENT_OTHER, INTENT_QUESTION, INTENT_TRIGGER, detect_intent


def test_question_mark():
    assert detect_intent("Where's the post about meal prep?").intent == INTENT_QUESTION


def test_question_starter_without_mark():
    assert detect_intent("how do I start with kettlebells").intent == INTENT_QUESTION


def test_trigger_keyword_wins():
    result = detect_intent("PLAN", trigger_keywords=["PLAN"])
    assert result.intent == INTENT_TRIGGER
    assert result.matched_trigger == "PLAN"


def test_trigger_case_insensitive():
    assert detect_intent("plan", trigger_keywords=["PLAN"]).intent == INTENT_TRIGGER


def test_noise_is_other():
    assert detect_intent("🔥🔥🔥").intent == INTENT_OTHER
    assert detect_intent("love this").intent == INTENT_OTHER
    assert detect_intent("").intent == INTENT_OTHER
