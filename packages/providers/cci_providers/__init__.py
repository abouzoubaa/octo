"""cci_providers — thin provider interfaces for every AI call.

Portability principle (plan §2): switching vendors — or dropping to a local
open-source model — is configuration, not a rewrite. Nothing outside this
package imports a vendor SDK or calls a model endpoint directly.
"""
from cci_providers.base import (
    EmbeddingProvider,
    LLMProvider,
    OCRProvider,
    TranscriptionProvider,
)
from cci_providers.registry import (
    get_embedding_provider,
    get_llm,
    get_ocr,
    get_reranker,
    get_transcriber,
    provider_versions,
)

__all__ = [
    "LLMProvider",
    "EmbeddingProvider",
    "TranscriptionProvider",
    "OCRProvider",
    "get_llm",
    "get_embedding_provider",
    "get_transcriber",
    "get_ocr",
    "get_reranker",
    "provider_versions",
]
