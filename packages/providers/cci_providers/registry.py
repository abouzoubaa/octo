"""Provider selection — pure configuration (CCI_* env vars), never code changes."""
from functools import lru_cache

from cci_core.config import get_settings
from cci_providers.base import EmbeddingProvider, LLMProvider, OCRProvider, TranscriptionProvider
from cci_providers.reranking import RerankProvider


@lru_cache
def get_llm() -> LLMProvider:
    s = get_settings()
    if s.llm_provider == "anthropic":
        from cci_providers.llm import AnthropicLLM

        return AnthropicLLM(api_key=s.llm_api_key, model=s.llm_model)
    if s.llm_provider == "openai-compatible":
        from cci_providers.llm import OpenAICompatibleLLM

        return OpenAICompatibleLLM(
            api_key=s.llm_api_key, model=s.llm_model,
            base_url=s.llm_base_url or "https://api.openai.com/v1",
        )
    from cci_providers.llm import FakeLLM

    return FakeLLM()


@lru_cache
def get_embedding_provider() -> EmbeddingProvider:
    s = get_settings()
    if s.embedding_provider == "openai-compatible":
        from cci_providers.embeddings import OpenAICompatibleEmbeddings

        return OpenAICompatibleEmbeddings(
            api_key=s.embedding_api_key, model=s.embedding_model,
            dims=s.embedding_dims, version=s.embedding_version,
            base_url=s.embedding_base_url or "https://api.openai.com/v1",
        )
    from cci_providers.embeddings import FakeEmbeddings

    return FakeEmbeddings()


@lru_cache
def get_transcriber() -> TranscriptionProvider:
    s = get_settings()
    if s.transcription_provider == "faster-whisper":
        from cci_providers.transcription import FasterWhisperTranscriber

        return FasterWhisperTranscriber(model_size=s.whisper_model)
    from cci_providers.transcription import FakeTranscriber

    return FakeTranscriber()


def provider_versions() -> dict:
    """Central AI version registry — model + version of every AI component in use,
    for reproducibility and safe migrations (which model produced which artifact)."""
    s = get_settings()
    return {
        "llm": {"provider": s.llm_provider, "model": s.llm_model},
        "embeddings": {"provider": s.embedding_provider, "model": s.embedding_model,
                       "version": s.embedding_version, "dims": s.embedding_dims},
        "transcription": {"provider": s.transcription_provider, "model": s.whisper_model},
        "ocr": {"provider": s.ocr_provider},
        "rerank": {"provider": s.rerank_provider,
                   "model": s.rerank_model if s.rerank_provider == "cross-encoder" else None},
    }


@lru_cache
def get_reranker() -> RerankProvider | None:
    """The second-pass reranker, or None when disabled (rerank_provider='none')."""
    provider = get_settings().rerank_provider
    if provider == "fake":
        from cci_providers.reranking import FakeReranker

        return FakeReranker()
    if provider == "llm":
        from cci_providers.reranking import LLMReranker

        return LLMReranker(get_llm())
    if provider == "cross-encoder":
        from cci_providers.reranking import CrossEncoderReranker

        return CrossEncoderReranker(get_settings().rerank_model)
    return None  # 'none' → skip reranking


@lru_cache
def get_ocr() -> OCRProvider:
    s = get_settings()
    if s.ocr_provider == "paddleocr":
        from cci_providers.ocr import PaddleOCRProvider

        return PaddleOCRProvider()
    from cci_providers.ocr import FakeOCR

    return FakeOCR()
