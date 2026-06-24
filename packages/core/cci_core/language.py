"""Lightweight, dependency-free language detection (stopword scoring).

Good enough to tag content and route search/embeddings; not a linguistics engine.
Defaults to English on uncertainty. For true multilingual retrieval, set
CCI_FTS_CONFIG (Postgres text-search config) and use a multilingual embedding model.
"""
from __future__ import annotations

_STOPWORDS = {
    "en": {"the", "and", "you", "for", "with", "what", "how", "this", "that", "your"},
    "es": {"el", "la", "los", "que", "de", "para", "con", "como", "una", "tu"},
    "fr": {"le", "la", "les", "que", "des", "pour", "avec", "comment", "une", "vous"},
    "de": {"der", "die", "und", "das", "ist", "für", "mit", "wie", "ein", "nicht"},
    "pt": {"o", "a", "que", "de", "para", "com", "como", "uma", "você", "não"},
    "it": {"il", "la", "che", "di", "per", "con", "come", "una", "non", "sono"},
}


def detect_language(text: str | None) -> str:
    """Best-guess ISO-639-1 code; 'en' on uncertainty."""
    tokens = {t.strip(".,!?;:¿¡").lower() for t in (text or "").split()}
    if not tokens:
        return "en"
    best, best_score = "en", 0
    for lang, words in _STOPWORDS.items():
        score = len(tokens & words)
        if score > best_score:
            best, best_score = lang, score
    return best
