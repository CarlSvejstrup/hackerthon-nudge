"""Nudge's own database: what Jev said, what was sent, what we know about people.

The bridge's messages.db is the raw source and is only ever read. Everything Nudge
derives lives here, in nudge.db next to the repo root.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .core import ROOT, Contact, Message

DB = Path(os.environ.get("NUDGE_STORE") or ROOT / "nudge.db")
KEEP_MESSAGES = int(os.environ.get("NUDGE_KEEP", 50))   # rolling window of text per chat

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY, started_at TEXT, finished_at TEXT,
    contacts INTEGER, jev_calls INTEGER, cache_hits INTEGER, acted INTEGER);
CREATE TABLE IF NOT EXISTS judgements (
    jid TEXT, last_message_id TEXT, judged_at TEXT, jev TEXT,
    PRIMARY KEY (jid, last_message_id));
CREATE TABLE IF NOT EXISTS nudges (
    id INTEGER PRIMARY KEY, jid TEXT, name TEXT, message_id TEXT, title TEXT, body TEXT,
    priority INTEGER, reasons TEXT, score REAL, sent_at TEXT, status TEXT DEFAULT 'sent');
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY, jid TEXT, name TEXT, note TEXT, written_at TEXT);
CREATE TABLE IF NOT EXISTS contacts (
    jid TEXT PRIMARY KEY, name TEXT, is_group INTEGER, close INTEGER, typical_gap_s REAL,
    source_ts TEXT, last_id TEXT, last_at TEXT, last_from_me INTEGER, last_sender TEXT, last_text TEXT,
    jev TEXT, score REAL, reasons TEXT, urgency REAL, priority INTEGER, act INTEGER, updated_at TEXT);
CREATE TABLE IF NOT EXISTS thread_status (
    jid TEXT PRIMARY KEY, status TEXT, until TEXT, message_id TEXT,
    flag_reason TEXT, set_at TEXT);
CREATE TABLE IF NOT EXISTS ignored (jid TEXT PRIMARY KEY, source_ts TEXT);
CREATE TABLE IF NOT EXISTS recent_messages (
    jid TEXT, id TEXT, at TEXT, from_me INTEGER, sender TEXT, text TEXT,
    PRIMARY KEY (jid, id));
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    return con


RETIRED_KEYS = ("urgency", "urgency_confidence")   # Jev no longer asked; older rows still carry them


def clean_jev(jev: dict) -> dict:
    return {k: v for k, v in jev.items() if k not in RETIRED_KEYS}


def cached_judgement(con, c: Contact) -> dict | None:
    """Jev is only asked again when the chat has a new last message."""
    row = con.execute("SELECT jev FROM judgements WHERE jid = ? AND last_message_id = ?",
                      (c.jid, c.last.id)).fetchone()
    return clean_jev(json.loads(row[0])) if row else None


def save_judgement(con, c: Contact) -> None:
    con.execute("INSERT OR REPLACE INTO judgements VALUES (?, ?, ?, ?)",
                (c.jid, c.last.id, now(), json.dumps(c.jev)))


def remember_recent(con, c: Contact) -> None:
    """Queue per chat: add the newest messages, drop text beyond the last KEEP_MESSAGES."""
    con.executemany("INSERT OR IGNORE INTO recent_messages VALUES (?, ?, ?, ?, ?, ?)",
                    [(c.jid, m.id, m.at.isoformat(), int(m.from_me), m.sender, m.text)
                     for m in c.messages[-KEEP_MESSAGES:]])
    con.execute("""DELETE FROM recent_messages WHERE jid = ? AND id NOT IN (
                     SELECT id FROM recent_messages WHERE jid = ? ORDER BY at DESC LIMIT ?)""",
                (c.jid, c.jid, KEEP_MESSAGES))


def already_nudged(con, c: Contact) -> bool:
    return con.execute("SELECT 1 FROM nudges WHERE jid = ? AND message_id = ?",
                       (c.jid, c.last.id)).fetchone() is not None


def last_nudge(con, jid: str) -> str | None:
    row = con.execute("SELECT sent_at FROM nudges WHERE jid = ? ORDER BY sent_at DESC LIMIT 1",
                      (jid,)).fetchone()
    return row[0] if row else None


def notes_for(con, jid: str) -> list[str]:
    return [r[0] for r in con.execute(
        "SELECT note FROM notes WHERE jid = ? ORDER BY written_at DESC LIMIT 5", (jid,))]


def log_nudge(con, jid, name, message_id, title, body, priority, reasons, score) -> None:
    con.execute("INSERT INTO nudges (jid, name, message_id, title, body, priority, reasons, score, sent_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (jid, name, message_id, title, body, priority, json.dumps(reasons), score, now()))


def add_note(con, jid: str, name: str, note: str) -> None:
    con.execute("INSERT INTO notes (jid, name, note, written_at) VALUES (?, ?, ?, ?)",
                (jid, name, note, now()))


def save_contact(con, c: Contact, source_ts: str, urgency: float, priority: int, act: bool) -> None:
    """The classified snapshot the MCP reads. Written by the routine only."""
    con.execute("INSERT OR REPLACE INTO contacts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
        c.jid, c.name, int(c.is_group), int(c.close),
        c.typical_gap.total_seconds() if c.typical_gap else None,
        source_ts, c.last.id, c.last.at.isoformat(), int(c.last.from_me), c.last.sender, c.last.text,
        json.dumps(c.jev), c.score, json.dumps(c.reasons), urgency, priority, int(act), now()))


def snapshot(con) -> dict[str, tuple]:
    """jid -> (source_ts, Contact rebuilt from the snapshot with only its last message)."""
    out = {}
    for (jid, name, is_group, close, gap, source_ts, last_id, last_at, from_me, sender, text,
         jev, *_rest) in con.execute("SELECT * FROM contacts"):
        c = Contact(jid=jid, name=name, is_group=bool(is_group),
                    messages=[Message(last_id, sender or "", text or "", datetime.fromisoformat(last_at), bool(from_me))])
        c.close = bool(close)
        c.typical_gap = timedelta(seconds=gap) if gap else None
        c.jev = clean_jev(json.loads(jev)) if jev else {}
        out[jid] = (source_ts, c)
    return out


def ignored(con) -> dict[str, str]:
    return dict(con.execute("SELECT jid, source_ts FROM ignored"))


def mark_ignored(con, jid: str, source_ts: str) -> None:
    con.execute("INSERT OR REPLACE INTO ignored VALUES (?, ?)", (jid, source_ts))


STATUSES = ("open", "done", "snoozed", "muted", "flagged")


def find_contact(con, name: str) -> list[tuple[str, str]]:
    return list(con.execute("SELECT jid, name FROM contacts WHERE name LIKE ? ORDER BY score DESC",
                            (f"%{name}%",)))


def set_status(con, jid: str, status: str, until: str | None = None, reason: str | None = None) -> None:
    """done: quiet until they write again. snoozed: quiet until `until`. muted: never nudge.
    flagged: Carl's own flag, always nudge until done. open: back to automatic."""
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    last = con.execute("SELECT last_id FROM contacts WHERE jid = ?", (jid,)).fetchone()
    con.execute("INSERT OR REPLACE INTO thread_status VALUES (?, ?, ?, ?, ?, ?)",
                (jid, status, until, last[0] if last else None, reason, now()))


def statuses(con) -> dict[str, dict]:
    return {r[0]: dict(zip(("status", "until", "message_id", "flag_reason"), r[1:5]))
            for r in con.execute("SELECT * FROM thread_status")}


def apply_status(st: dict | None, last_message_id: str, at: datetime) -> tuple[bool | None, str | None]:
    """Returns (forced act or None for automatic, reason to show)."""
    if not st or st["status"] == "open":
        return None, None
    if st["status"] == "muted":
        return False, "muted"
    if st["status"] == "flagged":
        return True, f"flagged: {st['flag_reason']}" if st["flag_reason"] else "flagged"
    until = datetime.fromisoformat(st["until"]) if st["until"] else None
    if until and until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    if st["status"] == "snoozed" and until and at < until:
        return False, f"snoozed until {st['until'][:10]}"
    if st["status"] == "done" and st["message_id"] == last_message_id:
        return False, "done"
    return None, None   # snooze ran out, or a new message reopened a done thread
