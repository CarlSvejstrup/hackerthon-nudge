"""Soft flags: ask Jev what the recent messages say. Code owns all time and arithmetic."""

from __future__ import annotations

import json
import os
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from .core import Contact, relative

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
CONTEXT_MESSAGES = 10   # only the tail of each chat leaves the machine
MAX_CHARS = 300

QUESTIONS = {
    "needs_reply": {
        "type": "noul",
        "instructions": "Does the last message in `messages` expect a reply from Carl? "
                        "It does not if it is a goodbye, a thank-you, an emoji-only reaction, "
                        "or if the conversation has naturally come to an end.",
    },
    "promise": {
        "type": "noul",
        "instructions": "In `messages`, did Carl say he would do something for the other person "
                        "(send something, call, meet up, check something) that the later messages "
                        "do not show as done?",
    },
    "follow_up": {
        "type": "noul",
        "instructions": "Did the other person mention something upcoming or ongoing in their own life "
                        "(an exam, a job interview, a trip, a move, an illness, a big event) that a good "
                        "friend would naturally ask about afterwards?",
    },
    "open_plan": {
        "type": "noul",
        "instructions": "Did Carl and the other person start making a plan together (meet up, call, a trip, "
                        "a visit, doing something together) that the messages never settled with a confirmed "
                        "time, and that was never cancelled?",
    },
    "personal": {
        "type": "noul",
        "instructions": "Is this a personal relationship (friend, family, partner, classmate, colleague "
                        "Carl knows personally) rather than a business, shop, hotel, tour operator, "
                        "customer service or automated sender?",
    },
    "heavy": {
        "type": "noul",
        "instructions": "Did the other person share something emotionally difficult, such as loss, "
                        "illness, a breakup, heavy stress or bad news?",
    },

}

GROUP_QUESTION = {
    "directed": {
        "type": "noul",
        "instructions": "Is the last message not written by Carl aimed specifically at Carl, "
                        "rather than at the group in general?",
    },
}


def build_state(c: Contact, now: datetime) -> dict:
    tail = c.messages[-CONTEXT_MESSAGES:]
    return {
        "me": "Carl",
        "chat": c.name,
        "is_group": c.is_group,
        "messages": [
            {
                "from": "Carl" if m.from_me else (m.sender if c.is_group else c.name),
                "when": relative(now - m.at),
                "text": m.text[:MAX_CHARS],
            }
            for m in tail
        ],
    }


def ask(c: Contact, now: datetime, key: str) -> dict[str, float]:
    questions = QUESTIONS | (GROUP_QUESTION if c.is_group else {})
    body = json.dumps({"model": MODEL, "state": build_state(c, now), "questions": questions}).encode()
    req = urllib.request.Request(ENDPOINT, data=body, headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        answers = json.load(r)["answers"]
    out = {}
    for k, v in answers.items():
        if v["type"] == "noul":
            out[k] = v["noul"]
        else:  # score: normalise 0..2 to 0..1 and keep how sure Jev was
            out[k] = v["score"] / (len(v["legend"]) - 1)
            out[f"{k}_confidence"] = v["confidence"]
    return out


def judge_all(contacts: list[Contact], now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    key = os.environ.get("TYPESAFE_API_KEY") or os.environ.get("JEV_API_KEY")
    if not key:
        raise SystemExit("Mangler JEV_API_KEY i miljøet eller .env")

    def one(c: Contact) -> None:
        try:
            c.jev = ask(c, now, key)
        except Exception as e:  # one bad chat must not stop the scan
            c.jev = {}
            c.reasons.append(f"(jev fejlede: {e.__class__.__name__})")

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(one, contacts))
