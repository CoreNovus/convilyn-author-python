"""Example: Document translation tool server for Convilyn workflows.

Demonstrates wrapping an external API as a platform tool.
Tools receive data via LLM arguments, not via extraction types.
"""

from convilyn_author import ToolServer

server = ToolServer(
    name="document-translator",
    description="AI-powered document translation between languages",
    version="1.0.0",
    capabilities=["translation", "language-detection"],
)


@server.tool(
    description="Translate text to a target language",
    idempotent=True,
)
async def translate_text(
    text: str,
    source_language: str = "auto",
    target_language: str = "en",
) -> dict:
    """Translate text between languages.

    In production, this would call a real translation API (e.g., DeepL).
    """
    translated = f"[Translated from {source_language} to {target_language}]: {text[:100]}"
    result = {
        "translated_text": translated,
        "source_language": source_language,
        "target_language": target_language,
        "confidence": 0.95,
    }
    ref_id = await server.data_store.store(result)
    return {"ref_id": ref_id, "summary": f"Translated to {target_language}"}


@server.tool(
    description="Detect the language of a text passage",
    idempotent=True,
)
async def detect_language(text: str) -> dict:
    """Detect the primary language of text content.

    In production, this would use a language detection model.
    Small result — no DataStore needed.
    """
    return {
        "ref_id": None,
        "summary": "Detected: English (98%)",
    }


if __name__ == "__main__":
    server.run()
