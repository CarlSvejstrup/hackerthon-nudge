"""Nudge as an MCP server: ask Claude who to reach out to, and why.

Read-mostly. It never sends a WhatsApp message and never pushes to the phone;
pushing stays with the routine and the `nudge push` command.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys

from mcp.server.fastmcp import FastMCP

from . import store
from .core import DB_PATH, ROOT, parse_ts

mcp = FastMCP("nudge")


FIELDS = ("jid", "name", "is_group", "score", "reasons", "act",
          "last_at", "last_from_me", "last_text", "jev", "updated_at")


def _snapshot(where: str = "", params: tuple = ()) -> list[dict]:
    """The routine's last classification. Reading it costs no Jev call and no model call."""
    con = store.connect()
    rows = con.execute(f"SELECT {', '.join(FIELDS)} FROM contacts {where} ORDER BY score DESC", params)
    out = []
    for r in rows:
        d = dict(zip(FIELDS, r))
        d["reasons"], d["jev"] = json.loads(d["reasons"] or "[]"), store.clean_jev(json.loads(d["jev"] or "{}"))
        d["last_nudged_at"] = store.last_nudge(con, d["jid"])
        d["notes"] = store.notes_for(con, d["jid"])
        out.append(d)
    return out


def _last_run() -> str | None:
    row = store.connect().execute("SELECT finished_at FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    return row[0] if row else None


def _classify() -> str:
    """On demand: the same incremental scan as the routine. Unchanged chats cost nothing,
    and Jev is only asked about chats whose last message is new."""
    out = subprocess.run([sys.executable, "-m", "nudge", "scan"], cwd=ROOT,
                         capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip().splitlines()[-1] if out.stderr else "scan failed")
    return out.stdout.splitlines()[0]


@mcp.tool()
def who_to_reach_out_to(include_all: bool = False) -> dict:
    """Contacts Carl should reach out to right now, highest score first: flags (unanswered,
    promise, follow_up, open_plan, broken_rhythm, forgotten, heavy), notes and when he was last nudged.
    Classifies new messages first, so the answer is always current."""
    summary = _classify()
    rows = _snapshot("" if include_all else "WHERE act = 1")
    return {"classified": summary, "as_of": _last_run(), "contacts": rows}


@mcp.tool()
def explain_contact(name: str) -> dict:
    """Why a contact is or is not flagged: every Jev answer, the score, notes and last nudge."""
    _classify()
    rows = _snapshot("WHERE name LIKE ?", (f"%{name}%",))
    if not rows:
        return {"found": False, "hint": "No chat with that name in the last classification."}
    return {"found": True, "as_of": _last_run(), **rows[0]}


LABELS = {"unanswered": "Ubesvaret", "promise": "Løfte", "follow_up": "Opfølgning",
          "open_plan": "Åben aftale", "broken_rhythm": "Brudt rytme"}


def _bar(v: float, width: int = 10) -> str:
    n = max(0, min(width, round(v / 1.5 * width)))
    return "█" * n + "░" * (width - n)


REASON_LABELS = LABELS | {"forgotten": "glemt", "heavy": "tungt emne", "not personal": "forretning"}


def _trace(live_jev: bool) -> dict:
    cmd = [sys.executable, "-m", "nudge", "scan", "--trace"] + (["--no-cache"] if live_jev else [])
    out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=180)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip().splitlines()[-1] if out.stderr else "scan failed")
    return json.loads(out.stdout)


def _stages(d: dict) -> list[str]:
    t = d["timings_ms"]
    acted = sum(1 for c in d["contacts"] if c["act"])
    filtered = sum(1 for c in d["contacts"] if "not personal" in c["reasons"])
    return [
        "| Trin | Hvad skete der | Tid |", "|---|---|---|",
        f"| 1. Kode læser | {d['chats']} chats · {d['read']} med nye beskeder læst helt · "
        f"{d['from_snapshot']} genberegnet fra snapshot | {t.get('read', 0)} ms |",
        f"| 2. Udvælgelse | {d['candidates']} kandidater med mulig åben løkke | {t.get('select', 0)} ms |",
        f"| 3. Jev flagger | {d['jev_calls']} kald × {d['questions_per_call']} spørgsmål · "
        f"{d['cache_hits']} fra cache | {t.get('jev', 0)} ms |",
        f"| 4. Kode scorer | vægte, glemt-boost, personlig-filter | {t.get('score', 0)} ms |",
        f"| 5. Beslutning | **{acted} nudges** · {filtered} forretninger sorteret fra af Jev | |", ""]


def _ranking(d: dict, rows: int) -> list[str]:
    top = max((c["breakdown"]["score"] for c in d["contacts"]), default=1) or 1
    out = ["| # | Kontakt | Score | Flag | Beslutning |", "|---|---|---|---|---|"]
    for i, c in enumerate(d["contacts"][:rows], 1):
        sc = c["breakdown"]["score"]
        flags = ", ".join(REASON_LABELS.get(r.split(":")[0], r) for r in c["reasons"]) or "–"
        out.append(f"| {i} | {c['name'][:22]} | `{_bar(sc / top * 1.5)}` {sc:.2f} | {flags} "
                   f"| {'**NUDGE**' if c['act'] else 'vent'} |")
    return out + [""]


def _explain(c: dict) -> list[str]:
    b = c["breakdown"]
    out = [f"### {c['name']} → {'NUDGE' if c['act'] else 'vent'} ({b['score']} "
           f"{'≥' if b['score'] >= b['threshold'] else '<'} {b['threshold']})",
           "", "| Jev-flag | Jev siger | Vægt | Point |", "|---|---|---|---|"]
    for k, f in b["flags"].items():
        if f["value"] > 0.05:
            out.append(f"| {LABELS.get(k, k)} | `{_bar(f['value'])}` {f['value']:.2f} | × {f['weight']} | {f['points']:.2f} |")
    extra = f"  ·  stille i {b['days_quiet']:.0f} dage, åbne løkker × {b['age_factor']}" if b["age_factor"] > 1 else ""
    out += ["", f"**{b['flag_points']}** flagpoint × personlig **{b['personal']}**"
            + (f" × tungt emne **{b['heavy_boost']}**" if b["heavy_boost"] > 1 else "")
            + f" = **{b['score']}**{extra}", ""]
    return out


@mcp.tool()
def demo(live_jev: bool = False, rows: int = 10, explain: int = 3) -> str:
    """The whole Nudge demo in one view: the pipeline stages with timings, a ranking of every
    candidate with score bars, Jev's flags and the decision, and then how
    the top scores were built. Set live_jev to run Jev live instead of from cache.
    Show the returned markdown to Carl exactly as it is, without summarising it."""
    d = _trace(live_jev)
    lines = ["## Nudge: live demo", "", "#### Pipeline", *_stages(d),
             "#### Rangering", *_ranking(d, rows), "#### Sådan blev scoren bygget", ""]
    for c in [c for c in d["contacts"] if c["act"]][:explain]:
        lines += _explain(c)
    return "\n".join(lines)


@mcp.tool()
def show_pipeline(top: int = 3, live_jev: bool = False) -> str:
    """Only the pipeline stages and how the top scores were built. For the full demo view use `demo`.
    Show the returned markdown to Carl exactly as it is, without summarising it."""
    d = _trace(live_jev)
    lines = ["## Nudge: sådan blev beslutningen truffet", "", *_stages(d)]
    for c in d["contacts"][:top]:
        lines += _explain(c)
    return "\n".join(lines)


@mcp.tool()
def set_thread_status(name: str, status: str, until: str | None = None, reason: str | None = None) -> dict:
    """Change how Nudge treats one chat. status is one of:
    - done: Carl handled it; quiet until the other person writes again.
    - snoozed: quiet until `until` (ISO date, e.g. 2026-10-03), then automatic again.
    - muted: never nudge about this chat (shops, tour operators, bots).
    - flagged: Carl's own flag; always nudge until set to done. Put why in `reason`.
    - open: back to fully automatic.
    Only changes Nudge's own database; nothing is sent anywhere."""
    con = store.connect()
    hits = store.find_contact(con, name)
    if len(hits) != 1:
        return {"changed": False, "matches": [n for _, n in hits] or "none",
                "hint": "Ask Carl which one he means, then call again with a more exact name."}
    store.set_status(con, hits[0][0], status, until, reason)
    con.commit()
    return {"changed": True, "name": hits[0][1], "status": status, "until": until, "reason": reason}


@mcp.tool()
def list_thread_statuses() -> list[dict]:
    """Every chat Carl has marked done, snoozed, muted or flagged."""
    con = store.connect()
    return [dict(zip(("name", "status", "until", "reason", "set_at"), r)) for r in con.execute(
        "SELECT c.name, t.status, t.until, t.flag_reason, t.set_at FROM thread_status t "
        "LEFT JOIN contacts c ON c.jid = t.jid WHERE t.status != 'open' ORDER BY t.set_at DESC")]


@mcp.tool()
def nudge_history(limit: int = 10) -> dict:
    """Recent routine runs (Jev calls, cache hits) and the nudges that were sent."""
    con = store.connect()
    runs = [dict(zip(("started_at", "contacts", "jev_calls", "cache_hits", "acted"), r)) for r in con.execute(
        "SELECT started_at, contacts, jev_calls, cache_hits, acted FROM runs ORDER BY id DESC LIMIT ?", (limit,))]
    nudges = [dict(zip(("sent_at", "name", "title", "body", "reasons", "status"), r)) for r in con.execute(
        "SELECT sent_at, name, title, body, reasons, status FROM nudges ORDER BY id DESC LIMIT ?", (limit,))]
    return {"runs": runs, "nudges": nudges}


@mcp.tool()
def notes_about(name: str) -> list[dict]:
    """What Nudge has learned about a person's life from earlier runs."""
    con = store.connect()
    return [dict(zip(("name", "note", "written_at"), r)) for r in con.execute(
        "SELECT name, note, written_at FROM notes WHERE name LIKE ? ORDER BY written_at DESC",
        (f"%{name}%",))]


@mcp.tool()
def search_chats(query: str, limit: int = 20) -> list[dict]:
    """Full-text search across all WhatsApp messages, newest first."""
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT c.name, m.chat_jid, m.timestamp, m.is_from_me, m.sender, m.content "
        "FROM messages m LEFT JOIN chats c ON c.jid = m.chat_jid "
        "WHERE m.content LIKE ? ORDER BY m.timestamp DESC LIMIT ?", (f"%{query}%", limit)).fetchall()
    return [{"chat": name or jid, "at": parse_ts(ts).isoformat(), "from": "Carl" if me else sender, "text": text}
            for name, jid, ts, me, sender, text in rows]


def main() -> None:
    from .__main__ import load_env
    load_env()
    mcp.run()


if __name__ == "__main__":
    main()
