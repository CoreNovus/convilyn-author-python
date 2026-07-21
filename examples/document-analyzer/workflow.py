"""Document Analyzer — example workflow definition.

Demonstrates how to compose tools from server.py into a complete
workflow spec that can be tested locally and pushed to the platform.
"""

from server import server

from convilyn_author import WorkflowSpec

workflow = (
    WorkflowSpec(
        "doc_analyzer",
        name="Document Analyzer",
        version="1.0.0",
        description=(
            "Analyze uploaded documents — extract text, identify keywords, and generate summary"
        ),
    )
    .with_input(
        types=["document"],
        formats=["pdf", "docx", "txt"],
        max_size_bytes=10_485_760,
    )
    .with_output(format="json", type="analysis_report")
    .from_server(server)
    .add_phase(
        "Extract",
        "Parse the uploaded document using `doc_analyzer__extract_text` "
        "to extract raw text content.",
    )
    .add_phase(
        "Analyze",
        "Run `doc_analyzer__analyze_text` on the extracted text to identify "
        "keywords, word frequency, and classify the document topic.",
    )
    .add_phase(
        "Summarize",
        "Generate a concise summary using `doc_analyzer__summarize`. "
        "Compile all results into a structured JSON report and store "
        "via `store_artifact` with file_name ending in .json.",
    )
    .add_phase(
        "Complete",
        "Call `complete_workflow` with a summary of findings: "
        "document type, top keywords, and key statistics.",
    )
    .with_agent_config(max_iterations=20, temperature=0.3)
    .add_preflight_rule(
        "check_has_document",
        check_type="file_count",
        params={"type": "document", "min": 1},
        error_message="Please upload a document to analyze",
        description="Must provide at least one document",
    )
    .with_locale_policy(type="locale_independent")
    .with_aliases("Document Analysis", "Text Analysis", "File Analyzer")
    .with_keywords("analyze", "document", "keywords", "summary", "extract")
)


if __name__ == "__main__":
    import json

    compiled = workflow.compile()
    print(json.dumps(compiled, indent=2))
