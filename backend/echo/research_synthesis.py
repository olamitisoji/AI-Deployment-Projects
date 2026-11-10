"""Evidence-linked extractive material for researcher review, without invented themes."""


def synthesize_transcripts(transcripts: list[dict]) -> dict:
    excerpts = []
    seen = set()
    for transcript in transcripts:
        identifier, text = transcript.get("id"), transcript.get("text")
        if not isinstance(identifier, str) or not identifier.strip() or not isinstance(text, str) or not text.strip() or identifier in seen:
            continue
        seen.add(identifier)
        excerpts.append({"transcript_id": identifier, "text": text.strip()[:2000]})
    return {"mode": "extractive", "transcript_count": len(excerpts), "excerpts": excerpts,
        "limitations": ["Extracts only; themes and interpretations require researcher review.", "Each extract is capped at 2,000 characters; consult the cited transcript for full context.", "This material describes the provided interviews and does not establish population prevalence."]}
