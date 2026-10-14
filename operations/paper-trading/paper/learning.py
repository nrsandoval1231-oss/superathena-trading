"""Trading-specific outcome feedback using the shared Athena identity contracts.

Broker observations become experiences immediately. Prospective, fixed-sample
nightly validation can promote only temporary abstention rules, never more risk.
This is an application learning policy, not a second general-purpose Athena Core.
"""
from __future__ import annotations

import json
import math
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from statistics import fmean
from zoneinfo import ZoneInfo

from ..athena_adapter.contracts import canonical_hash
from ..athena_adapter.jev import JEV_MODEL, questions
from .journal import PaperJournal

NY = ZoneInfo("America/New_York")
PROTOCOL = {
    "version": "paper-negative-experience-v1", "discovery_n": 20, "validation_n": 20,
    "minimum_mean_loss_r": 0.1, "loss_wilson_z": 1.96, "rule_lifetime_days": 14,
    "adaptive_action": "NO_TRADE", "grouping": "account-symbol-policy-direction",
    "maximum_candidates_per_cohort": 1,
}


def instant(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("learning timestamps must be timezone aware")
    return result.astimezone(UTC)


def decimal(value) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("non-finite broker amount")
    return result


def _outcome_orders(history: Any) -> list[dict]:
    """Top-level orders plus nested bracket legs. A repeated id is a conflict."""
    if not isinstance(history, list) or len(history) >= 500:
        raise ValueError("incomplete broker history")
    ordered: list[dict] = []
    seen: set[str] = set()

    def visit(item: Any) -> None:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError("incomplete broker history")
        identity = item["id"]
        if identity in seen:
            raise ValueError("duplicate broker order in outcome")
        seen.add(identity)
        ordered.append(item)
        legs = item.get("legs")
        if legs is None:
            return
        if not isinstance(legs, list):
            raise ValueError("incomplete broker history")
        for leg in legs:
            visit(leg)

    for item in history:
        visit(item)
    if len(ordered) >= 500:
        raise ValueError("incomplete broker history")
    return ordered


def outcome(journal: PaperJournal, observed_at: datetime) -> dict | None:
    entry, flat = journal.last("entry_intent"), journal.last("flat_confirmed")
    if not entry or not flat:
        return None
    binding = journal.last("binding")["binding"]
    order = entry["order"]
    history = _outcome_orders(flat["order_history"])
    seen, fills = set(), []
    for item in history:
        if item["id"] in seen:
            raise ValueError("duplicate broker order in outcome")
        seen.add(item["id"])
        qty = decimal(item["filled_qty"])
        if qty < 0 or qty > 1:
            raise ValueError("outcome exceeds owned paper quantity")
        if qty == 0:
            continue
        if item["symbol"] != order["symbol"] or item["side"] not in {"buy", "sell"}:
            raise ValueError("unowned outcome fill")
        price = decimal(item["filled_avg_price"])
        if price <= 0:
            raise ValueError("missing fill price")
        fills.append((item, qty, price))
    parent = next((item for item in history if item["id"] == flat["parent"]["id"]), None)
    if parent is None or parent.get("client_order_id") != order["client_order_id"]:
        raise ValueError("outcome is missing the reserved entry")
    entered = decimal(parent["filled_qty"])
    buys = sum((qty for item, qty, _ in fills if item["side"] == "buy"), Decimal(0))
    sells = sum((qty for item, qty, _ in fills if item["side"] == "sell"), Decimal(0))
    if buys != sells or buys != entered:
        raise ValueError("outcome fills do not reconcile to owned flat position")
    gross = sum((qty * price * (1 if item["side"] == "sell" else -1)
                 for item, qty, price in fills), Decimal(0))
    risk = abs(decimal(order["limit_price"]) - decimal(order["stop_loss"]["stop_price"])) * entered
    entry_at = instant(entry["at"])
    closed_at = instant(flat["snapshot"]["clock"]["timestamp"])
    if entry_at > closed_at or closed_at > observed_at:
        raise ValueError("outcome is not available at observation time")
    policy = binding["policy"]
    adjudications = [event for event in journal.events if event["kind"] == "adjudication"]
    wanted = entry.get("verdict_hash")
    if wanted:
        adjudication = next((event for event in adjudications
                             if canonical_hash(event["receipt"]) == wanted), None)
        if adjudication is None:
            raise ValueError("outcome decision receipt does not match reserved entry")
    else:
        adjudication = adjudications[-1] if adjudications else None
    receipt = adjudication["receipt"] if adjudication else {}
    if receipt and wanted != canonical_hash(receipt):
        raise ValueError("outcome decision receipt does not match reserved entry")
    question_hash = receipt.get("question_hash")
    direction = "LONG" if order["side"] == "buy" else "SHORT"
    cohort = canonical_hash({"account": binding["account_id"], "symbol": order["symbol"],
                             "direction": direction, "policy": policy, "questions": question_hash})
    # A fallback reuses an earlier acceptance after the cutoff. It is stored and
    # kept out of this study, including when that earlier receipt was accepted.
    eligible = (entered == 1 and risk > 0 and policy.get("actor_model") == JEV_MODEL
                and receipt.get("accepted") is True and not entry.get("fallback")
                and question_hash == canonical_hash(questions()))
    sampled = [decimal(p["unrealized_pl"]) for event in journal.events
               if event["kind"] == "broker_observation"
               for p in event["snapshot"]["positions"]
               if p["symbol"] == order["symbol"] and "unrealized_pl" in p]
    return {
        "id": canonical_hash({"account": binding["account_id"], "entry": order["client_order_id"]}),
        "account": binding["account_id"], "symbol": order["symbol"], "direction": direction,
        "cohort": cohort, "policy_hash": canonical_hash(policy), "session": entry["session"],
        "question_hash": question_hash,
        "entry_at": entry_at.isoformat(), "closed_at": closed_at.isoformat(),
        "observed_at": observed_at.isoformat(), "source_hash": canonical_hash(flat),
        "entry_hash": canonical_hash(entry), "quantity": str(entered),
        "status": "CLOSED" if entered else "NO_FILL", "gross_pnl": str(gross),
        "gross_r": float(gross / risk) if risk > 0 else None,
        "result": "LOSS" if gross < 0 else "GAIN" if gross > 0 else "FLAT",
        "costs": "UNMEASURED", "net_pnl": None, "eligible": eligible,
        "sampled_mfe_dollars": str(max(sampled)) if sampled else None,
        "sampled_mae_dollars": str(min(sampled)) if sampled else None,
        "excursion_basis": "broker position samples, not complete market path",
        "exit_reason": (journal.last("halt") or {}).get("reason"),
        "decision": adjudication,
    }


def episode_arm(episode: dict) -> str:
    """Missing arm is the original intraday study. Earnings rows are explicit."""
    arm = episode.get("arm")
    if arm is None:
        return "intraday"
    if not isinstance(arm, str) or not arm:
        return "unknown"
    return arm


def _filled_rows(parent: dict | None, close_orders: list) -> list[tuple[str, Decimal, Decimal]] | None:
    """Balanced entry and exit fills. None means the cashflow is not measured."""
    rows: list[tuple[str, Decimal, Decimal]] = []
    seen: set[str] = set()

    def add(item: Any) -> bool:
        if not isinstance(item, dict):
            return True
        identity = item.get("id")
        if isinstance(identity, str):
            if identity in seen:
                return True
            seen.add(identity)
        try:
            qty = decimal(item.get("filled_qty") or 0)
        except (TypeError, ValueError):
            return False
        if qty == 0:
            return True
        side = item.get("side")
        try:
            price = decimal(item.get("filled_avg_price"))
        except (TypeError, ValueError):
            return False
        if side not in {"buy", "sell"} or price <= 0 or qty < 0:
            return False
        rows.append((side, qty, price))
        return True

    if not add(parent):
        return None
    legs = parent.get("legs") if isinstance(parent, dict) else None
    for leg in legs or []:
        if not add(leg):
            return None
    for order in close_orders:
        if not add(order):
            return None
    return rows


def _lifecycle_samples(
    journal: PaperJournal, *, symbol: str, client_order_id: str,
    entry_at: datetime, observed_at: datetime,
) -> list[Decimal]:
    """Unrealized samples for this reservation only, from entry through observation."""
    sampled: list[Decimal] = []
    for event in journal.events:
        if event["kind"] != "broker_observation":
            continue
        owner = event.get("client_order_id")
        if isinstance(owner, str) and owner != client_order_id:
            continue
        try:
            at = instant(event["at"])
        except (KeyError, TypeError, ValueError):
            continue
        if at < entry_at or at > observed_at:
            continue
        for position in event.get("snapshot", {}).get("positions", []):
            if position.get("symbol") != symbol or "unrealized_pl" not in position:
                continue
            sampled.append(decimal(position["unrealized_pl"]))
    return sampled


def earnings_episode(journal: PaperJournal, client_order_id: str, observed_at: datetime) -> dict | None:
    """One closed earnings trade. It is stored and never eligible for the intraday study."""
    binding_event = journal.last("binding")
    if not binding_event:
        raise ValueError("earnings outcome has no account binding")
    binding = binding_event["binding"]
    entry = next((
        event for event in reversed(journal.events)
        if event["kind"] == "entry_intent"
        and event.get("order", {}).get("client_order_id") == client_order_id
    ), None)
    experience = next((
        event for event in reversed(journal.events)
        if event["kind"] == "earnings_experience" and event.get("client_order_id") == client_order_id
    ), None)
    closed = next((
        event for event in reversed(journal.events)
        if event["kind"] == "position_closed" and event.get("client_order_id") == client_order_id
    ), None)
    if entry is None or closed is None:
        raise ValueError("earnings close is missing its reservation")
    if experience is None:
        return None
    order = entry["order"]
    wanted = entry.get("verdict_hash")
    adjudications = [event for event in journal.events if event["kind"] == "adjudication"]
    if wanted:
        adjudication = next((event for event in adjudications
                             if canonical_hash(event["receipt"]) == wanted), None)
        if adjudication is None:
            raise ValueError("earnings outcome decision receipt does not match reserved entry")
    else:
        adjudication = None
    receipt = adjudication["receipt"] if adjudication else {}
    question_hash = receipt.get("question_hash")
    parent = experience.get("parent") if isinstance(experience.get("parent"), dict) else None
    close_orders = experience.get("close_orders") if isinstance(experience.get("close_orders"), list) else []
    try:
        filled = decimal(parent.get("filled_qty") or 0) if parent else Decimal(0)
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("earnings fill quantity is unusable") from exc
    if filled < 0:
        raise ValueError("earnings fill quantity is unusable")
    entry_at = instant(entry["at"])
    if entry_at > observed_at:
        raise ValueError("outcome is not available at observation time")
    direction = "LONG" if order["side"] == "buy" else "SHORT"
    policy = binding["policy"]
    no_fill = filled == 0 or closed.get("reason") == "ENTRY_TERMINATED"
    gross: Decimal | None
    if no_fill:
        gross = Decimal(0)
        status = "NO_FILL"
    else:
        status = "CLOSED"
        measured = _filled_rows(parent, close_orders)
        buys = sells = Decimal(0)
        if measured is not None:
            buys = sum((qty for side, qty, _ in measured if side == "buy"), Decimal(0))
            sells = sum((qty for side, qty, _ in measured if side == "sell"), Decimal(0))
        if measured is None or buys != sells or buys != filled:
            gross = None
        else:
            gross = sum((qty * price * (1 if side == "sell" else -1)
                         for side, qty, price in measured), Decimal(0))
    try:
        risk = abs(decimal(order["limit_price"]) - decimal(order["stop_loss"]["stop_price"])) * filled
    except (KeyError, TypeError, ValueError):
        risk = Decimal(0)
    if gross is None:
        result = "UNMEASURED"
        gross_r = None
        gross_text = None
    else:
        result = "LOSS" if gross < 0 else "GAIN" if gross > 0 else "FLAT"
        gross_r = float(gross / risk) if risk > 0 and status == "CLOSED" else None
        gross_text = str(gross)
    sampled = _lifecycle_samples(
        journal, symbol=order["symbol"], client_order_id=client_order_id,
        entry_at=entry_at, observed_at=observed_at,
    )
    return {
        "id": canonical_hash({
            "arm": "earnings", "account": binding["account_id"], "entry": client_order_id,
        }),
        "arm": "earnings",
        "account": binding["account_id"], "symbol": order["symbol"], "direction": direction,
        "cohort": canonical_hash({
            "arm": "earnings", "account": binding["account_id"], "symbol": order["symbol"],
            "direction": direction, "policy": policy, "questions": question_hash,
        }),
        "policy_hash": canonical_hash(policy), "session": entry["session"],
        "question_hash": question_hash,
        "entry_at": entry_at.isoformat(), "closed_at": observed_at.isoformat(),
        "observed_at": observed_at.isoformat(), "source_hash": canonical_hash(experience),
        "entry_hash": canonical_hash(entry), "quantity": str(filled),
        "status": status, "gross_pnl": gross_text, "gross_r": gross_r, "result": result,
        "costs": "UNMEASURED", "net_pnl": None,
        "eligible": False, "eligible_for_intraday_study": False,
        "sampled_mfe_dollars": str(max(sampled)) if sampled else None,
        "sampled_mae_dollars": str(min(sampled)) if sampled else None,
        "excursion_basis": "broker position samples, not complete market path",
        "exit_reason": experience.get("reason"),
        "decision": adjudication,
    }


def evidence(values: list[dict]) -> dict:
    returns = [item["gross_r"] for item in values]
    n = len(returns)
    if not n:
        return {"n": 0, "supported": False}
    losses = sum(r < 0 for r in returns)
    p, z = losses / n, PROTOCOL["loss_wilson_z"]
    lower = (p + z*z/(2*n) - z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))) / (1+z*z/n)
    mean = fmean(returns)
    # Skipping has zero hypothetical trade P&L. This is a comparison, not an executed outcome.
    return {"n": n, "mean_gross_r": mean, "loss_fraction_lower": lower,
            "counterfactual_skip_effect_r": -mean,
            "supported": mean <= -PROTOCOL["minimum_mean_loss_r"] and lower > 0.5}


class LearningStore:
    def __init__(self, state_dir: Path):
        self.directory = state_dir / "learning"
        self.journal = PaperJournal(self.directory / "events.sqlite")
        registration = self.journal.last("protocol")
        if registration is None:
            self.journal.append("protocol", protocol=PROTOCOL, digest=canonical_hash(PROTOCOL))
        elif registration["digest"] != canonical_hash(PROTOCOL):
            self.close()
            raise ValueError("learning protocol drift requires a new versioned study")

    def close(self):
        self.journal.close()

    def experiences(self):
        return [e["episode"] for e in self.journal.events if e["kind"] == "experience"]

    def ingest(self, source: PaperJournal, now: datetime):
        episode = outcome(source, now)
        if episode is None:
            return
        existing = next((e for e in self.experiences() if e["id"] == episode["id"]), None)
        if existing:
            if any(existing[key] != episode[key] for key in ("source_hash", "entry_hash", "policy_hash", "question_hash")):
                raise ValueError("observed outcome changed; reconcile before learning")
            return
        self.journal.append("experience", episode=episode)

    def ingest_earnings(self, source: PaperJournal, client_order_id: str, now: datetime) -> bool:
        """Store one earnings close beside intraday episodes. It stays out of that study."""
        episode = earnings_episode(source, client_order_id, now)
        if episode is None:
            return False
        # An unmeasured close stays out of the store so a later fill can replace it.
        if episode.get("result") == "UNMEASURED" or (
            episode.get("status") == "CLOSED" and episode.get("gross_pnl") is None
        ):
            return False
        if episode_arm(episode) != "earnings" or episode["eligible"]:
            raise ValueError("earnings outcome must stay ineligible for the intraday study")
        existing = next((e for e in self.experiences() if e["id"] == episode["id"]), None)
        if existing:
            compared = ("source_hash", "entry_hash", "policy_hash", "question_hash", "arm")
            if any(existing[key] != episode[key] for key in compared):
                raise ValueError("observed outcome changed; reconcile before learning")
            return True
        self.journal.append("experience", episode=episode)
        return True

    def context(self, account: str, symbol: str, direction: str, now: datetime, policy=None):
        available = [e for e in self.experiences() if episode_arm(e) == "intraday"
                     and e["account"] == account
                     and e["symbol"] == symbol and e["direction"] == direction
                     and instant(e["observed_at"]) < now and e["status"] == "CLOSED"
                     and e["question_hash"] == canonical_hash(questions())
                     and (policy is None or e["policy_hash"] == canonical_hash(policy))]
        rules = [e for e in self.journal.events if e["kind"] == "promoted"
                 and e["account"] == account and e["symbol"] == symbol and e["direction"] == direction
                 and instant(e["at"]) < now < instant(e["expires_at"])
                 and e["question_hash"] == canonical_hash(questions())
                 and policy is not None and e["policy_hash"] == canonical_hash(policy)]
        recent = [{k: e[k] for k in ("id", "session", "result", "gross_r", "gross_pnl", "quantity", "costs")}
                  for e in sorted(available, key=lambda e: e["observed_at"])[-5:]]
        content = {"recent_experiences": recent, "validated_rules": rules,
                   "learning_mode": "observed experience plus validated temporary abstention"}
        return {**content, "version": canonical_hash(content)}

    def review(self, session: date, now: datetime, *, unresolved: bool = False, session_summary=None):
        cutoff = datetime.combine(session, time(20, 15), NY)
        if now < cutoff or unresolved:
            return None
        day = session.isoformat()
        if any(e["kind"] == "nightly_review" and e["session"] == day for e in self.journal.events):
            return None
        available = [e for e in self.experiences() if instant(e["observed_at"]) <= now]
        groups = {}
        for episode in available:
            if episode.get("eligible") and episode_arm(episode) == "intraday":
                groups.setdefault(episode["cohort"], []).append(episode)
        for cohort, items in groups.items():
            items.sort(key=lambda e: (e["observed_at"], e["id"]))
            candidate = next((e for e in self.journal.events if e["kind"] == "candidate"
                              and e["cohort"] == cohort), None)
            if candidate is None and len(items) >= PROTOCOL["discovery_n"]:
                discovery = items[:PROTOCOL["discovery_n"]]
                result = evidence(discovery)
                # One fixed discovery look per cohort, retaining rejected hypotheses too.
                self.journal.append("candidate", cohort=cohort, at=now, discovery=result,
                                    source_ids=[e["id"] for e in discovery],
                                    eligible=result["supported"], protocol_hash=canonical_hash(PROTOCOL))
                continue
            if candidate is None or not candidate["eligible"]:
                continue
            if any(e["kind"] == "validation" and e["cohort"] == cohort for e in self.journal.events):
                continue
            prospective = [e for e in items if instant(e["entry_at"]) > instant(candidate["at"])
                           and e["id"] not in candidate["source_ids"]]
            if len(prospective) < PROTOCOL["validation_n"]:
                continue
            sample = prospective[:PROTOCOL["validation_n"]]
            result = evidence(sample)
            self.journal.append("validation", cohort=cohort, at=now, result=result,
                                source_ids=[e["id"] for e in sample],
                                disposition="PROMOTED" if result["supported"] else "REJECTED")
            if result["supported"]:
                first = sample[0]
                self.journal.append("promoted", cohort=cohort, at=now,
                                    expires_at=now + timedelta(days=PROTOCOL["rule_lifetime_days"]),
                                    account=first["account"], symbol=first["symbol"],
                                    direction=first["direction"], policy_hash=first["policy_hash"],
                                    question_hash=first["question_hash"],
                                    action="NO_TRADE", reason="prospectively confirmed negative gross returns")
        day_episodes = [e for e in available if e["session"] == day]
        report = {"session": day, "at": now.isoformat(), "protocol": PROTOCOL,
                  "session_summary": session_summary or [],
                  "episodes": [e for e in day_episodes if episode_arm(e) == "intraday"],
                  "earnings_episodes": [e for e in day_episodes if episode_arm(e) == "earnings"],
                  "evaluations": [e for e in self.journal.events
                                  if e["kind"] in {"candidate", "validation", "promoted"}],
                  "limits": "Gross paper outcomes; fees unmeasured; no guarantee of future improvement."}
        self.journal.append("nightly_review", session=day, report=report)
        return report

    def write_reports(self):
        # Reports are derived output; replay repairs a crash between ledger commit and file write.
        for e in self.journal.events:
            if e["kind"] == "nightly_review":
                path = self.directory / (e["session"] + ".json")
                temporary = path.with_suffix(".tmp")
                temporary.write_text(json.dumps(e["report"], indent=2) + "\n")
                temporary.replace(path)


def maintain(state_dir: Path, now: datetime):
    store = LearningStore(state_dir)
    try:
        sessions, unresolved, summaries = set(), False, {}
        for path in sorted(state_dir.glob("*.sqlite")):
            journal = PaperJournal(path)
            try:
                entry = journal.last("entry_intent")
                if entry:
                    sessions.add(date.fromisoformat(entry["session"]))
                    unresolved |= not bool(
                        journal.last("flat_confirmed") or journal.last("entry_not_created")
                    )
                    store.ingest(journal, now)
                else:
                    try:
                        sessions.add(date.fromisoformat(path.stem))
                    except ValueError:
                        pass
                session = entry["session"] if entry else path.stem
                summaries.setdefault(session, []).append({
                    "journal": path.name, "journal_head": journal.head,
                    "candidate_reviews": sum(e["kind"] == "decision_started" for e in journal.events),
                    "jev_acceptances": sum(e["kind"] == "adjudication" and e["receipt"]["accepted"]
                                           for e in journal.events),
                    "fallback_entries": sum(e["kind"] == "fallback_entry" for e in journal.events),
                    "learned_veto_observations": sum(e["kind"] == "learning_veto" for e in journal.events),
                    "entry_reserved": bool(entry), "flat_confirmed": bool(journal.last("flat_confirmed")),
                    "halt": journal.last("halt"),
                })
            finally:
                journal.close()
        for session in sorted(sessions):
            store.review(session, now, unresolved=unresolved,
                         session_summary=summaries.get(session.isoformat(), []))
        store.write_reports()
    finally:
        store.close()
