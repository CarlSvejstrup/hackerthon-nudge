"""Combine hard and soft flags into act / don't act, and word the nudge."""

from __future__ import annotations

from .core import Contact

YES = 0.7        # a noul above this counts as the flag being present
ACT_AT = 0.6     # contacts scoring at or above this get a nudge

WEIGHTS = {
    "unanswered": 1.0,
    "promise": 0.8,
    "follow_up": 0.6,
    "open_plan": 0.8,
    "broken_rhythm": 0.7,
}
HEAVY_BOOST = 0.5
FORGOTTEN_AFTER_DAYS = 7    # an open loop this old counts as forgotten
FORGOTTEN_BOOST = 0.5       # forgotten open loops rank above fresh ones


def score(c: Contact) -> None:
    j = c.jev
    parts: dict[str, float] = {}

    if c.waiting_on_me:
        p = j.get("needs_reply", 0.0)
        if c.is_group:
            p *= j.get("directed", 0.0)
        parts["unanswered"] = p
    parts["promise"] = j.get("promise", 0.0)
    parts["follow_up"] = j.get("follow_up", 0.0)
    parts["open_plan"] = j.get("open_plan", 0.0)
    parts["broken_rhythm"] = min(c.broken_rhythm / 1.5, 1.0)

    # The older an unanswered message, promise or loose plan, the more likely it was forgotten.
    days = c.silence.total_seconds() / 86400
    forgotten = days >= FORGOTTEN_AFTER_DAYS and any(
        parts.get(k, 0.0) >= YES for k in ("unanswered", "promise", "open_plan"))
    age = 1 + FORGOTTEN_BOOST * min(days / 30, 1.0)
    for k in ("unanswered", "promise", "open_plan"):
        if k in parts:
            parts[k] = min(parts[k] * age, 1.0 + FORGOTTEN_BOOST)

    flags = sum(WEIGHTS[k] * v for k, v in parts.items())
    personal = j.get("personal", 1.0)
    s = flags * personal   # hotels and shops fade out instead of being hard-muted
    heavy = s > 0 and j.get("heavy", 0.0) >= YES
    if heavy:
        s *= 1 + HEAVY_BOOST
    c.score = round(s, 2)
    c.breakdown = {
        "flags": {k: {"value": round(v, 2), "weight": WEIGHTS[k], "points": round(WEIGHTS[k] * v, 2)}
                  for k, v in parts.items()},
        "days_quiet": round(days, 1), "age_factor": round(age, 2),
        "flag_points": round(flags, 2), "personal": round(personal, 2),
"heavy_boost": 1 + HEAVY_BOOST if heavy else 1.0,
        "score": c.score, "threshold": ACT_AT,
    }

    c.reasons = [k for k, v in parts.items() if v >= YES or (k == "broken_rhythm" and v > 0)] + \
                [r for r in c.reasons if r.startswith("(")]
    if forgotten:
        c.reasons.append("forgotten")
    if j.get("heavy", 0.0) >= YES:
        c.reasons.append("heavy")
    if j and j.get("personal", 1.0) < 0.5:
        c.reasons.append("not personal")


def priority(c: Contact) -> int:
    """ntfy priority: 4 when someone is waiting on Carl, 3 otherwise."""
    return 4 if "unanswered" in c.reasons else 3


def should_act(c: Contact) -> bool:
    real = [r for r in c.reasons if not r.startswith("(") and r not in ("not personal", "heavy", "forgotten")]
    return c.score >= ACT_AT and bool(real) and "not personal" not in c.reasons


TITLES = {
    "unanswered": "{name} venter på et svar",
    "promise": "Du lovede {name} noget",
    "follow_up": "Spørg {name}, hvordan det gik",
    "open_plan": "Blev det til noget med {name}?",
    "broken_rhythm": "Det er et stykke tid siden, du og {name} har snakket",
}


def word(c: Contact) -> tuple[str, str]:
    """Title and body for the push. No day counts: rhythm must not feel like a stopwatch."""
    main = next((r for r in ("promise", "unanswered", "open_plan", "follow_up", "broken_rhythm") if r in c.reasons),
                "broken_rhythm")
    title = TITLES[main].format(name=c.name)
    if main == "unanswered" and "forgotten" in c.reasons:
        title = f"Du mangler at svare {c.name}"
    snippet = c.last.text.strip().replace("\n", " ")
    if len(snippet) > 120:
        snippet = snippet[:117] + "…"
    who = "Dig" if c.last.from_me else (c.last.sender if c.is_group else c.name)
    body = f"{who}: “{snippet}”"
    if "heavy" in c.reasons:
        body += "\nDet kunne være godt at tjekke ind."
    return title, body
