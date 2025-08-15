from __future__ import annotations
import os, json, logging
from typing import Optional, Dict, Any

from pydantic_ai import Agent
from leg5_src.parser.models import CompanyModel

logger = logging.getLogger("leg_llm_agent")


def run_llm(raw_text: str, model_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Return a dict matching leg_models.Company, or None on failure/missing lib."""

    model = model_name or os.getenv("PYA_MODEL", "gpt-4o-mini")
    try:
        agent = Agent(model=model, response_format=CompanyModel)
        prompt = (
            "Extract structured company data from the Romanian legal notice below.\n"
            "Rules:\n"
            "- Do NOT invent data. Leave fields null/empty if not present.\n"
            "- Preserve Romanian diacritics and original capitalization for names.\n"
            "- Prefer cui like RO######## if available; registrationNumber like Jxx/xxxxx/yyyy.\n"
            "- Keep addresses as they appear; infer county/city only if clearly stated.\n\n"
            f"{raw_text}"
        )
        result = agent.run(prompt)
        comp: CompanyModel = result.data
        return json.loads(comp.model_dump_json())
    except Exception as e:
        logger.exception(f"LLM extraction failed: {e}")
        return None
