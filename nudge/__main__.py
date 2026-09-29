"""nudge scan | push | note | log | context | search"""

from __future__ import annotations

import argparse
import time
import json
import os
import sqlite3
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .core import DB_PATH, ROOT, is_candidate, latest_per_chat, load_contacts, parse_ts, time_flags
from .decide import priority, should_act, score, word
from . import store
from .judge import QUESTIONS, judge_all



def load_env() -> None:
    for env in (ROOT / ".env", Path.home() / "code/.env"):
        if not env.exists():
            continue
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def push(title: str, body: str, priority: int = 3) -> None:
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        raise SystemExit("Mangler NTFY_TOPIC i .env")
    data = json.dumps({"topic": topic, "title": title, "message": body,
                       "priority": priority, "tags": ["speech_balloon"]}).encode()
    req = urllib.request.Request("https://ntfy.sh/", data=data,
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10).close()


def scan(args) -> None:
    """Incremental: full history is only read for chats with a new message since the last run."""
    now = datetime.now(timezone.utc)
    con = store.connect()
    started = store.now()
    clock, timings = time.perf_counter(), {}

    def lap(name: str) -> None:
        nonlocal clock
        timings[name] = round((time.perf_counter() - clock) * 1000)
        clock = time.perf_counter()

    latest = latest_per_chat()
    snap = store.snapshot(con)
    ignored = store.ignored(con)
    changed = {jid for jid, ts in latest.items()
               if args.full or (snap[jid][0] if jid in snap else ignored.get(jid)) != ts}
    fresh_contacts = {c.jid: c for c in load_contacts(now=now, only=changed)}
    everyone = dict(fresh_contacts)
    for jid, (_, c) in snap.items():
        if jid not in everyone and jid in latest:
            time_flags(c, now)
            everyone[jid] = c

    lap("read")
    candidates = sorted((c for c in everyone.values() if is_candidate(c)), key=lambda c: c.silence)[: args.limit]
    need_jev, need_history = [], set()
    for c in candidates:
        cached = None if args.no_cache else store.cached_judgement(con, c)
        if cached is not None and not set(QUESTIONS) <= cached.keys():
            cached = None   # judged before a question was added: ask again once
        if cached is not None:
            c.jev = cached
        elif c.jid in fresh_contacts:
            need_jev.append(c)
        else:
            need_history.add(c.jid)   # became a candidate without new messages, e.g. rhythm just broke
    for c in load_contacts(now=now, only=need_history):
        candidates = [c if x.jid == c.jid else x for x in candidates]
        need_jev.append(c)
    lap("select")
    if not args.no_jev and need_jev:
        judge_all(need_jev, now)
        for c in need_jev:
            if c.jev:
                store.save_judgement(con, c)
    for c in fresh_contacts.values():
        store.remember_recent(con, c)

    lap("jev")
    # Carl's own flags always make it to the candidate list, even when the chat is quiet.
    st = store.statuses(con)
    for jid, s_ in st.items():
        if s_["status"] == "flagged" and jid in everyone and all(x.jid != jid for x in candidates):
            candidates.append(everyone[jid])
    by_jid = {c.jid: c for c in candidates}
    forced = {}
    for c in candidates:
        score(c)
        act, why = store.apply_status(st.get(c.jid), c.last.id, now)
        if why:
            c.reasons.append(why)
        if act is True:
            c.score = max(c.score, 1.0) + 0.5
        forced[c.jid] = act
    for jid, c in everyone.items():
        c = by_jid.get(jid, c)
        if jid not in by_jid:
            c.score, c.reasons = 0.0, []
        act = forced.get(jid)
        act = (jid in by_jid and should_act(c)) if act is None else act
        store.save_contact(con, c, latest.get(jid, ""), 0.0, priority(c), act)
    for jid in changed - everyone.keys():   # too old or a broadcast list: remember we looked
        store.mark_ignored(con, jid, latest[jid])
    contacts = sorted(candidates, key=lambda c: -c.score)
    fresh = need_jev

    acted = [c for c in contacts if (forced.get(c.jid) if forced.get(c.jid) is not None else should_act(c))
             and not store.already_nudged(con, c)]
    con.execute("INSERT INTO runs (started_at, finished_at, contacts, jev_calls, cache_hits, acted) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (started, store.now(), len(contacts), 0 if args.no_jev else len(fresh),
                 len(contacts) - len(fresh), len(acted)))
    con.commit()

    lap("score")
    if args.trace:
        print(json.dumps({
            "chats": len(latest), "read": len(changed), "from_snapshot": len(everyone) - len(fresh_contacts),
            "candidates": len(contacts), "jev_calls": len(fresh), "cache_hits": len(contacts) - len(fresh),
            "questions_per_call": len(QUESTIONS), "timings_ms": timings,
            "contacts": [{"name": c.name, "is_group": c.is_group, "act": c in acted or bool(forced.get(c.jid)),
                          "reasons": c.reasons, "jev": {k: round(v, 2) for k, v in c.jev.items()},
                          "fresh_jev": c in fresh, "breakdown": c.breakdown,
                          "priority": priority(c),
                          "days_quiet": round(c.silence.total_seconds() / 86400, 1)} for c in contacts],
        }, ensure_ascii=False))
        return
    if args.json:
        print(json.dumps([{
            "jid": c.jid, "name": c.name, "is_group": c.is_group, "score": c.score,
            "act": should_act(c), "reasons": c.reasons, "jev": {k: round(v, 2) for k, v in c.jev.items()},
            "priority": priority(c),
            "already_nudged": store.already_nudged(con, c), "last_message_id": c.last.id,
            "last_nudged_at": store.last_nudge(con, c.jid), "notes": store.notes_for(con, c.jid),
            "template": dict(zip(("title", "body"), word(c))),
        } for c in contacts], ensure_ascii=False, indent=1))
        return
    print(f"{len(latest)} chats, {len(changed)} med nye beskeder læst, {len(contacts)} kandidater, "
          f"{len(fresh)} nye Jev-vurderinger, {len(contacts) - len(fresh)} fra cache")
    for c in contacts:
        mark = "→" if c in acted else " "
        print(f"{mark} {c.score:4.2f}  {c.name[:24]:24}  {', '.join(c.reasons) or '-'}")
        if args.verbose and c.jev:
            print("        jev:", {k: round(v, 2) for k, v in c.jev.items()})
        if not (c in acted and args.push):
            continue
        title, body = word(c)
        push(title, body, priority=priority(c))
        store.log_nudge(con, c.jid, c.name, c.last.id, title, body, priority(c), c.reasons, c.score)
        con.commit()
        print(f"        push sendt: {title}")


def push_cmd(args) -> None:
    """Used by the Claude routine: send one nudge Claude has worded, and log it."""
    con = store.connect()
    if con.execute("SELECT 1 FROM nudges WHERE jid = ? AND message_id = ?",
                   (args.jid, args.message_id)).fetchone():
        print("allerede sendt")
        return
    push(args.title, args.body, args.priority)
    store.log_nudge(con, args.jid, args.name, args.message_id, args.title, args.body,
                    args.priority, args.reasons.split(",") if args.reasons else [], args.score)
    con.commit()
    print("push sendt")


def note_cmd(args) -> None:
    """Used by the Claude routine: remember what is going on in someone's life."""
    con = store.connect()
    store.add_note(con, args.jid, args.name, args.text)
    con.commit()
    print("note gemt")


def status_cmd(args) -> None:
    con = store.connect()
    hits = store.find_contact(con, args.name)
    if len(hits) != 1:
        print("Fandt ingen" if not hits else "Flere matcher: " + ", ".join(n for _, n in hits))
        return
    store.set_status(con, hits[0][0], args.status, args.until, args.reason)
    con.commit()
    print(f"{hits[0][1]}: {args.status}")


def log_cmd(args) -> None:
    con = store.connect()
    print("Seneste kørsler:")
    for r in con.execute("SELECT started_at, contacts, jev_calls, cache_hits, acted FROM runs "
                         "ORDER BY id DESC LIMIT ?", (args.limit,)):
        print(f"  {r[0]}  {r[1]} kontakter · {r[2]} Jev-kald · {r[3]} fra cache · {r[4]} skal handles")
    print("Seneste nudges:")
    for r in con.execute("SELECT sent_at, name, title, status FROM nudges ORDER BY id DESC LIMIT ?",
                         (args.limit,)):
        print(f"  {r[0]}  {r[1][:20]:20}  {r[2]}  [{r[3]}]")


def context_cmd(args) -> None:
    """Fallback for the routine when the WhatsApp MCP is not loaded: last N messages of one chat."""
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT timestamp, is_from_me, sender, content FROM messages WHERE chat_jid = ? "
        "AND content != '' ORDER BY timestamp DESC LIMIT ?", (args.jid, args.limit)).fetchall()
    for ts, from_me, sender, text in reversed(rows):
        print(f"{parse_ts(ts):%d.%m %H:%M}  {'Carl' if from_me else sender}: {text}")


def search(args) -> None:
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT c.name, m.chat_jid, m.timestamp, m.is_from_me, m.sender, m.content "
        "FROM messages m LEFT JOIN chats c ON c.jid = m.chat_jid "
        "WHERE m.content LIKE ? ORDER BY m.timestamp DESC LIMIT ?",
        (f"%{' '.join(args.terms)}%", args.limit)).fetchall()
    for name, jid, ts, from_me, sender, text in rows:
        who = "Dig" if from_me else sender
        print(f"{parse_ts(ts):%d.%m.%Y %H:%M}  {(name or jid)[:24]:24}  {who[:12]:12}  {text[:100]}")


def main() -> None:
    load_env()
    p = argparse.ArgumentParser(prog="nudge")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="find hvem du bør række ud til")
    s.add_argument("--push", action="store_true", help="send nudges til telefonen via ntfy")
    s.add_argument("--no-jev", action="store_true", help="kun hårde flag, ingen data forlader maskinen")
    s.add_argument("--limit", type=int, default=40)
    s.add_argument("-v", "--verbose", action="store_true")
    s.add_argument("--json", action="store_true", help="maskinlæsbart output til Claude-routinen")
    s.add_argument("--no-cache", action="store_true", help="spørg Jev igen, selv om chatten er vurderet")
    s.add_argument("--trace", action="store_true", help="hele pipelinen som JSON, til demo-værktøjet")
    s.add_argument("--full", action="store_true", help="læs hele historikken for alle chats igen")
    s.set_defaults(fn=scan)
    pu = sub.add_parser("push", help="send én nudge formuleret af Claude")
    pu.add_argument("--jid", required=True)
    pu.add_argument("--message-id", required=True)
    pu.add_argument("--title", required=True)
    pu.add_argument("--body", required=True)
    pu.add_argument("--priority", type=int, default=3)
    pu.add_argument("--name", default="")
    pu.add_argument("--reasons", default="")
    pu.add_argument("--score", type=float, default=0.0)
    pu.set_defaults(fn=push_cmd)
    cx = sub.add_parser("context", help="seneste beskeder i én chat")
    cx.add_argument("--jid", required=True)
    cx.add_argument("--limit", type=int, default=20)
    cx.set_defaults(fn=context_cmd)
    no = sub.add_parser("note", help="gem kontekst om en person")
    no.add_argument("--jid", required=True)
    no.add_argument("--name", default="")
    no.add_argument("--text", required=True)
    no.set_defaults(fn=note_cmd)
    stt = sub.add_parser("status", help="sæt status på en tråd: open, done, snoozed, muted, flagged")
    stt.add_argument("name")
    stt.add_argument("status", choices=store.STATUSES)
    stt.add_argument("--until", help="ISO-dato for snoozed, fx 2026-10-03")
    stt.add_argument("--reason", help="din egen grund ved flagged")
    stt.set_defaults(fn=status_cmd)
    lg = sub.add_parser("log", help="seneste kørsler og nudges")
    lg.add_argument("--limit", type=int, default=10)
    lg.set_defaults(fn=log_cmd)
    q = sub.add_parser("search", help="søg i dine chats")
    q.add_argument("terms", nargs="+")
    q.add_argument("--limit", type=int, default=20)
    q.set_defaults(fn=search)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
