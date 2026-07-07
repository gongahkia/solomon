from __future__ import annotations

from dataclasses import asdict, dataclass

from stonks_cli.config import AppConfig


@dataclass(frozen=True)
class LegalPolicyCheck:
    ok: bool
    blockers: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def evaluate_legal_policy(
    cfg: AppConfig,
    *,
    venue_id: str | None = None,
    strategy_class: str | None = None,
) -> LegalPolicyCheck:
    policy = cfg.legal_policy
    if not policy.sg_resident:
        return LegalPolicyCheck(ok=True, blockers=[])
    blockers: list[str] = []
    venue = _norm(venue_id)
    strategy = _norm(strategy_class)
    if venue and venue in {_norm(item) for item in policy.blocked_venue_ids}:
        blockers.append(f"legal_policy_blocked_venue:{venue}")
    if strategy and strategy in {_norm(item) for item in policy.blocked_strategy_classes}:
        blockers.append(f"legal_policy_blocked_strategy:{strategy}")
    return LegalPolicyCheck(ok=not blockers, blockers=blockers)


def enforce_legal_policy(
    cfg: AppConfig,
    *,
    venue_id: str | None = None,
    strategy_class: str | None = None,
) -> None:
    check = evaluate_legal_policy(cfg, venue_id=venue_id, strategy_class=strategy_class)
    if not check.ok:
        raise ValueError("; ".join(check.blockers))


def _norm(value: str | None) -> str:
    return (value or "").strip().lower().replace("-", "_")
