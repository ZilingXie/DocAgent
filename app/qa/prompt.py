SYSTEM_PROMPT = """You are a technical documentation QA assistant.

Rules:
1) Use only the provided context chunks.
2) If evidence is insufficient, set "insufficient_evidence" to true and answer exactly:
   "Not enough evidence in provided docs."
3) Do not fabricate APIs, versions, parameters, or steps.
4) Every factual claim must be supported by citations.
5) Output must be valid JSON only, no markdown fences.
"""


def build_answer_prompt(question: str, context_block: str) -> str:
    return f"""Question:
{question}

Context Chunks:
{context_block}

Return JSON with this exact schema:
{{
  "answer": "string",
  "key_steps": ["string"],
  "citations": ["chunk_id"],
  "insufficient_evidence": false
}}

Requirements:
- "citations" must contain chunk_id values that exist in Context Chunks.
- If insufficient evidence, return:
  {{
    "answer": "Not enough evidence in provided docs.",
    "key_steps": [],
    "citations": [],
    "insufficient_evidence": true
  }}
"""
