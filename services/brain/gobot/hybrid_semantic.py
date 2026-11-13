"""Optional constrained proposal interface. No provider implementation or execution."""
import json
from pydantic import BaseModel,ConfigDict,Field,ValidationError
from .hybrid_contract import IntentCandidate

class SemanticProposal(BaseModel):
    model_config=ConfigDict(extra='forbid')
    candidates:list[IntentCandidate]=Field(min_length=1,max_length=4)

def validate_proposal(raw,allowed_skill_ids):
    if not isinstance(raw,str) or len(raw)>12000:return None
    try:proposal=SemanticProposal.model_validate_json(raw)
    except (ValueError,ValidationError):return None
    if any(c.skill_id not in allowed_skill_ids for c in proposal.candidates):return None
    return proposal # Always a proposal; never trusted approval or a budget.
