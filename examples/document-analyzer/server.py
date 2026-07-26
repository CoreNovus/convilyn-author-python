"""Document Analyzer — example Convilyn tool server.

Demonstrates a tool server with tools that parse, analyze, and
summarize documents — the kind of tools a platform workflow calls.
"""

from convilyn_author import ToolServer

server = ToolServer(
    name="doc-analyzer",
    description="Document analysis tools — parse, analyze, and summarize",
    version="1.0.0",
    capabilities=["text_extraction", "analysis", "summarization"],
)


@server.tool(description="Extract text content from a document", idempotent=True)
async def extract_text(content: str, file_type: str = "txt") -> dict:
    """Extract raw text from a document.

    Args:
        content: Base64-encoded document content or plain text.
        file_type: Document type (txt, pdf, docx).

    Returns:
        Dict with ref_id and summary (full text stored server-side).
    """
    # In production, use actual parsing libraries (pypdf, python-docx)
    text = content  # Simplified: treat as plain text
    char_count = len(text)
    word_count = len(text.split())

    result = {
        "text": text,
        "char_count": char_count,
        "word_count": word_count,
        "file_type": file_type,
    }

    ref_id = await server.data_store.store(result)
    return {"ref_id": ref_id, "summary": f"Extracted {word_count} words ({char_count} chars)"}


@server.tool(description="Analyze text to extract keywords and classify topic")
async def analyze_text(text: str, max_keywords: int = 10) -> dict:
    """Analyze text content for keywords and classification.

    Args:
        text: Plain text to analyze.
        max_keywords: Maximum keywords to extract.

    Returns:
        Dict with ref_id and summary (full analysis stored server-side).
    """
    # Simplified keyword extraction (production: use NLP library)
    words = text.lower().split()
    word_freq: dict[str, int] = {}
    stop_words = {"the", "a", "an", "is", "it", "in", "to", "and", "of", "for", "on", "with"}
    for word in words:
        cleaned = word.strip(".,!?;:\"'()[]")
        if cleaned and len(cleaned) > 2 and cleaned not in stop_words:
            word_freq[cleaned] = word_freq.get(cleaned, 0) + 1

    sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
    keywords = [w for w, _ in sorted_words[:max_keywords]]

    result = {
        "keywords": keywords,
        "word_count": len(words),
        "unique_words": len(word_freq),
        "classification": "general",  # Simplified
    }

    ref_id = await server.data_store.store(result)
    return {
        "ref_id": ref_id,
        "summary": f"Found {len(keywords)} keywords, {len(words)} words analyzed",
    }


@server.tool(description="Generate a concise summary of text content")
async def summarize(text: str, max_length: int = 200) -> dict:
    """Summarize text content.

    Args:
        text: Plain text to summarize.
        max_length: Maximum summary length in characters.

    Returns:
        Dict with summary text and metadata.
    """
    # Simplified summarization (production: use LLM or extractive methods)
    sentences = text.replace("\n", " ").split(".")
    sentences = [s.strip() for s in sentences if s.strip()]

    summary_parts: list[str] = []
    current_length = 0
    for sentence in sentences:
        if current_length + len(sentence) > max_length:
            break
        summary_parts.append(sentence)
        current_length += len(sentence) + 2  # +2 for ". "

    summary = ". ".join(summary_parts)
    if summary and not summary.endswith("."):
        summary += "."

    return {
        "summary": summary,
        "original_length": len(text),
        "summary_length": len(summary),
        "compression_ratio": round(len(summary) / max(len(text), 1), 2),
    }


if __name__ == "__main__":
    server.run()
