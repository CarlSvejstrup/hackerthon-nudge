"""Read WhatsApp history from the bridge database and compute flags per contact."""

from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("NUDGE_DB") or ROOT / "vendor/whatsapp-mcp/whatsapp-bridge/store/messages.db")

CONTACTS_DB = DB_PATH.parent / "whatsapp.db"

SESSION_BREAK = timedelta(hours=6)   # a pause longer than this starts a new session
LOOKBACK = timedelta(days=365)
MIN_SESSIONS = 5                     # fewer sessions than this: not a close contact
RHYTHM_FACTOR = 2.5                  # silence beyond this many normal gaps breaks rhythm
RHYTHM_FLOOR = timedelta(days=10)    # never flag daily chatters after a couple of quiet days
DEAD_AFTER = timedelta(days=365)     # silence this long is history, not a nudge
UNANSWERED_MIN_AGE = timedelta(minutes=float(os.environ.get("NUDGE_MIN_AGE_MIN", 120)))  # 0 for a live demo
UNANSWERED_MAX_AGE = timedelta(days=180)   # forgotten replies are the point, not just fresh ones
OPEN_LOOP_WINDOW = timedelta(days=float(os.environ.get("NUDGE_WINDOW_DAYS", 180)))  # quiet chats this recent are checked for open loops


@dataclass
class Message:
    id: str
    sender: str
    text: str
    at: datetime
    from_me: bool


@dataclass
class Contact:
    jid: str
    name: str
    messages: list[Message]
    is_group: bool = False
    close: bool = False
    typical_gap: timedelta | None = None
    silence: timedelta = timedelta(0)
    broken_rhythm: float = 0.0       # 0 = within rhythm, 1 = just broken, up to 3
    waiting_on_me: bool = False      # they wrote last, recently enough to matter
    jev: dict[str, float] = field(default_factory=dict)
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    breakdown: dict = field(default_factory=dict)   # how the score was built, for the demo trace

    @property
    def last(self) -> Message:
        return self.messages[-1]


def parse_ts(raw: str) -> datetime:
    # Go writes e.g. "2026-09-29 10:15:03.123456789+02:00"; Python wants at most 6 fraction digits.
    s = str(raw).replace(" ", "T", 1)
    s = re.sub(r"(\.\d{6})\d+", r"\1", s)
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def contact_names(path: Path = CONTACTS_DB) -> dict[str, str]:
    """User part of a phone number or LID -> the name Carl has saved, else their own push name."""
    if not path.exists():
        return {}
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    names = {}
    for jid, first, full, push, biz in con.execute(
            "SELECT their_jid, first_name, full_name, push_name, business_name FROM whatsmeow_contacts"):
        name = full or first or push or biz
        if name:
            names[jid.split("@")[0]] = name
    for lid, pn in con.execute("SELECT lid, pn FROM whatsmeow_lid_map"):
        if pn in names:
            names[lid] = names[pn]
    con.close()
    return names


def latest_per_chat(db_path: Path = DB_PATH) -> dict[str, str]:
    """Cheap change detector: newest message timestamp per chat, as the bridge stored it."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    rows = dict(con.execute("SELECT chat_jid, MAX(timestamp) FROM messages "
                            "WHERE content IS NOT NULL AND content != '' GROUP BY chat_jid"))
    con.close()
    return rows


def load_contacts(db_path: Path = DB_PATH, now: datetime | None = None,
                  only: set[str] | None = None) -> list[Contact]:
    """Full history, but only for the chats in `only` when given."""
    now = now or datetime.now(timezone.utc)
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    names = dict(con.execute("SELECT jid, name FROM chats"))
    people = contact_names()
    where, params = "", []
    if only is not None:
        if not only:
            return []
        where = f" AND chat_jid IN ({','.join('?' * len(only))})"
        params = list(only)
    rows = con.execute(
        "SELECT id, chat_jid, sender, content, timestamp, is_from_me FROM messages "
        "WHERE content IS NOT NULL AND content != ''" + where + " ORDER BY timestamp", params
    ).fetchall()
    con.close()

    by_chat: dict[str, list[Message]] = {}
    for mid, jid, sender, text, ts, from_me in rows:
        at = parse_ts(ts)
        if now - at > LOOKBACK:
            continue
        who = people.get((sender or "").split("@")[0], sender or "")
        by_chat.setdefault(jid, []).append(Message(mid, who, text, at, bool(from_me)))

    contacts = []
    for jid, msgs in by_chat.items():
        if jid.endswith("@broadcast") or jid.endswith("@newsletter"):
            continue
        user = jid.split("@")[0]
        name = names.get(jid)
        if not name or name == user:
            name = people.get(user, user)
        c = Contact(jid=jid, name=name, messages=msgs,
                    is_group=jid.endswith("@g.us"))
        compute_hard_flags(c, now)
        contacts.append(c)
    return contacts


def compute_hard_flags(c: Contact, now: datetime) -> None:
    learn_rhythm(c)
    time_flags(c, now)


def learn_rhythm(c: Contact) -> None:
    """Needs the full history. Only rerun when the chat has new messages."""
    msgs = c.messages
    starts = [msgs[0].at]
    for prev, cur in zip(msgs, msgs[1:]):
        if cur.at - prev.at > SESSION_BREAK:
            starts.append(cur.at)
    both_sides = any(m.from_me for m in msgs) and any(not m.from_me for m in msgs)
    c.close = len(starts) >= MIN_SESSIONS and both_sides

    if c.close and not c.is_group:  # a trip group going quiet is not a drifting friendship
        gaps = [b - a for a, b in zip(starts, starts[1:])][-20:]
        c.typical_gap = median(gaps)


def time_flags(c: Contact, now: datetime) -> None:
    """Only needs the last message and the learned rhythm, so it is cheap on every run."""
    c.silence = now - c.last.at
    c.broken_rhythm = 0.0
    if c.typical_gap:
        limit = max(c.typical_gap * RHYTHM_FACTOR, RHYTHM_FLOOR)
        if limit < c.silence < DEAD_AFTER:
            c.broken_rhythm = min(c.silence / limit, 3.0)

    c.waiting_on_me = (not c.last.from_me) and UNANSWERED_MIN_AGE <= c.silence <= UNANSWERED_MAX_AGE


def is_candidate(c: Contact) -> bool:
    """Worth a Jev look. Quiet chats are included on purpose: a forgotten promise is the best nudge.
    Each chat costs one Jev call per new last message, so old quiet chats are judged once."""
    return c.waiting_on_me or c.broken_rhythm > 0 or c.silence <= OPEN_LOOP_WINDOW


def relative(delta: timedelta) -> str:
    h = delta.total_seconds() / 3600
    if h < 1:
        return "just now"
    if h < 24:
        return f"{int(h)} hours ago"
    d = int(h // 24)
    return "yesterday" if d == 1 else f"{d} days ago"
