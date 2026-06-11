from cci_retrieval.chunking import (
    MAX_WORDS, chunk_caption, chunk_ocr, chunk_transcript,
)


def test_short_caption_single_chunk():
    chunks = chunk_caption("Quick tip: eat more protein.")
    assert len(chunks) == 1
    assert chunks[0].source == "caption"


def test_empty_caption():
    assert chunk_caption("") == []
    assert chunk_caption("   \n\n ") == []


def test_long_caption_splits():
    text = " ".join(f"word{i}" for i in range(MAX_WORDS * 3))
    chunks = chunk_caption(text)
    assert len(chunks) >= 3
    assert all(len(c.text.split()) <= MAX_WORDS for c in chunks)


def test_transcript_chunks_overlap_and_carry_timestamps():
    segments = [
        {"start": float(i * 5), "end": float(i * 5 + 5), "text": " ".join(["spoken"] * 30)}
        for i in range(30)
    ]
    chunks = chunk_transcript(segments)
    assert len(chunks) > 1
    assert chunks[0].start_ts == 0.0
    assert all(c.start_ts is not None for c in chunks)
    # overlap: consecutive chunks share trailing/leading words
    assert chunks[1].start_ts < 30 * 5  # second chunk starts before the end


def test_transcript_empty():
    assert chunk_transcript([]) == []


def test_ocr_joins_fragments():
    frags = [(f"line {i}", float(i)) for i in range(10)]
    chunks = chunk_ocr(frags)
    assert len(chunks) == 1
    assert chunks[0].start_ts == 0.0
    assert "line 9" in chunks[0].text


def test_ocr_splits_when_large():
    frags = [(" ".join(["text"] * 30), float(i)) for i in range(40)]
    chunks = chunk_ocr(frags)
    assert len(chunks) > 1
    assert all(len(c.text.split()) >= 1 for c in chunks)
