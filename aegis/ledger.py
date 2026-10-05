from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from .models import StrategyEvidence


@dataclass(frozen=True)
class EvidenceReceipt:
    strategy_id: str
    created_at: str
    evidence_hash: str
    payload: dict


def seal_evidence(evidence: StrategyEvidence) -> EvidenceReceipt:
    payload = evidence.to_dict()
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(canonical).hexdigest()
    return EvidenceReceipt(
        strategy_id=evidence.strategy_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        evidence_hash=digest,
        payload=payload,
    )
