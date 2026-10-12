"""eventos — tool of the eventos-sociales howware: a wedding, XV años or baptism planned from a countdown template.

Commands (JSON on stdout, diagnostics on stderr, documented exit codes):
  setup      load seed.json into the memory: predicates and the templates that come with the howware
  now        today's date and weekday, from the clock (never guess them)
  brief      start of session: the events, days left, what is late, payments due, RSVPs pending
  templates  the templates;  template: save an event's tasks and budget shares as a new template, or retire one
  event      create an event (applies a template: tasks and budget areas) or change it (date, state, capacity...)
  events     the events
  agenda     what is late (from the start, or slipped), this week, the next weeks, and what comes after
  tasks      an event's tasks by state, area or text;  task: add, change, do, drop or reopen one
  budget     the total, the suggested split, the planned amount per area; and per area: hired, covered by
             sponsors, the hosts' share, paid, owed, left
  vendor     add or change a vendor: area, contract total, state, pay-off date, contact;  vendors: with balances
  pay        record a payment (to a vendor or an area), idempotently;  unpay: void one;  payments: by payer, area
  sponsor    add or change a sponsor (padrinos): role, state, what they cover;  sponsors: all of them
  guest      add or change an invitation: group, seats, RSVP, coming, diet; or remove it
  guests     the invitations with counts; --file imports a JSON or CSV list; --export writes a CSV
  table      add or change a table;  seat: seat an invitation at a table (capacity checked);  tables: the plan
  program    the day's program, minute by minute: add, remove, list

Contract (howware spec §6): no network, no interactive prompts, idempotent writes, money in integer cents, dates at
noon local time, refuse unsafe input with a clear error. Standard library only. Judgment (what to do first when
late, who sits with whom, how to word the program) is the agent's and the owner's, never this file's.
"""

from __future__ import annotations

import argparse
import calendar
import csv
import hashlib
import io
import json
import os
import re
import secrets
import subprocess
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

__version__ = "0.1.0"
HERE = Path(__file__).resolve().parent
SEED = HERE / "seed.json"
MIN_MEMORY = (0, 4, 0)

# Exit codes (documented in SKILL.md)
OK, BAD_INPUT, MEMORY_ERROR = 0, 2, 3

EVENT_STATES = ("planning", "done", "cancelled")
TASK_STATES = ("pending", "done", "dropped")
VENDOR_STATES = ("quoting", "hired", "discarded")
SPONSOR_STATES = ("to_ask", "accepted", "declined", "removed")
RSVP = {"pending": "pending", "pendiente": "pending", "yes": "yes", "si": "yes", "sí": "yes", "confirmado": "yes",
        "confirmed": "yes", "no": "no", "declined": "no", "no viene": "no", "no vienen": "no"}
GENERAL = "general"
MAX_TEXT = 2000
MAX_MONEY = 10_000_000_000          # cents: 100 million pesos
MAX_SEATS = 5000
WEEKDAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
OFFSET_RE = re.compile(r"([+-]?)(\d{1,3})([dwm])")
CSV_COLUMNS = {"name": ("name", "nombre", "invitado", "invitacion", "invitación"), "group": ("group", "grupo"),
               "seats": ("seats", "pases", "lugares"), "rsvp": ("rsvp", "confirmacion", "confirmación"),
               "coming": ("coming", "asistentes", "vienen"), "diet": ("diet", "dieta"), "note": ("note", "nota")}


class ToolError(Exception):
    def __init__(self, message: str, code: int = BAD_INPUT):
        super().__init__(message)
        self.code = code


# -- memory (project-memory helper) -------------------------------------------------
def find_helper(explicit: str | None) -> Path:
    for c in (explicit, os.environ.get("HOWWARE_MEMORY_HELPER"),
              Path.home() / ".claude/skills/project-memory/scripts/memory.py",
              Path.home() / ".codex/skills/project-memory/scripts/memory.py"):
        if c and Path(c).is_file():
            return Path(c)
    raise ToolError("project-memory is not installed (or pass --mem / HOWWARE_MEMORY_HELPER).", MEMORY_ERROR)


class Memory:
    PAGE = 5000

    def __init__(self, helper: Path, db: str | None):
        self.helper, self.db = helper, db

    def command(self, args: tuple[str, ...]) -> list[str]:
        return [sys.executable, str(self.helper)] + (["--db", self.db] if self.db else []) + list(args)

    def run(self, *args: str, stdin: dict | None = None) -> Any:
        for attempt in (1, 2):
            proc = subprocess.run(self.command(args),
                                  input=json.dumps(stdin, ensure_ascii=False) if stdin is not None else None,
                                  capture_output=True, text=True, encoding="utf-8")
            if proc.returncode == 0:
                return json.loads(proc.stdout) if proc.stdout.strip() else None
            message = (proc.stderr or proc.stdout).strip()
            # The memory compares validity per second: a change to a fact in the second it began waits one.
            if attempt == 1 and ("at least one second" in message or "is not after" in message):
                time.sleep(1.1)
                continue
            raise ToolError(f"memory {args[0]} failed: {message[-600:]}", MEMORY_ERROR)

    def check_version(self) -> None:
        out = subprocess.run([sys.executable, str(self.helper), "--version"], capture_output=True, text=True).stdout
        found = re.search(r"(\d+)\.(\d+)\.(\d+)", out or "")
        if not found or tuple(int(x) for x in found.groups()) < MIN_MEMORY:
            raise ToolError(f"project-memory >= {'.'.join(map(str, MIN_MEMORY))} is required (found: {out.strip()}).",
                            MEMORY_ERROR)

    def rows_many(self, queries: list[tuple[str, ...]]) -> list[list[dict]]:
        """Several `list` queries at once, in parallel processes; later pages, rarely needed, one by one."""
        procs = [subprocess.Popen(self.command(("list", *q, "--limit", str(self.PAGE))), stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, encoding="utf-8") for q in queries]
        out = []
        for q, proc in zip(queries, procs):
            stdout, stderr = proc.communicate()
            if proc.returncode != 0:
                raise ToolError(f"memory list failed: {(stderr or stdout).strip()[-600:]}", MEMORY_ERROR)
            page = json.loads(stdout)
            rows, offset = page["rows"], self.PAGE
            while page.get("truncated"):
                page = self.run("list", *q, "--limit", str(self.PAGE), "--offset", str(offset))
                rows += page["rows"]
                offset += self.PAGE
            out.append(rows)
        return out

    def write(self, by: str, content: str, kind: str = "user_statement", **sections) -> dict:
        return self.run("write", stdin={"source": {"type": kind, "content": content, "provided_by": by,
                                                   "captured_at": "now"},
                                        "performed_by": by, **sections})

    def write_new(self, by: str, content: str, events: list[dict], now: datetime) -> dict[str, str]:
        """Writes events that must be new. A key the memory already has belongs to an event voided earlier, so it is
        written again under a fresh key. Returns the key each event was stored under."""
        stored = {e["key"]: e["key"] for e in events}
        pending = events
        for _ in range(3):
            result = self.write(by, content, events=pending)
            existing = set((result.get("events") or {}).get("existing") or [])
            if not existing:
                return stored
            stamp = f"{now.strftime('%Y%m%d%H%M%S')}{secrets.token_hex(3)}"
            pending = []
            for e in events:
                if stored[e["key"]] in existing:
                    stored[e["key"]] = f"{e['key']}_n{stamp}"
                    pending.append({**e, "key": stored[e["key"]]})
        raise ToolError("The memory kept refusing new keys for these events.", MEMORY_ERROR)


# -- exact helpers ------------------------------------------------------------------------
def parse_tz(text: str) -> timezone:
    m = re.fullmatch(r"([+-])(\d{2}):?(\d{2})", text.strip())
    if not m:
        raise ToolError(f"Time zone offset must look like -06:00, not {text!r}")
    minutes = int(m.group(2)) * 60 + int(m.group(3))
    return timezone(timedelta(minutes=minutes if m.group(1) == "+" else -minutes))


def local_offset() -> str:
    z = datetime.now().astimezone().strftime("%z")
    return f"{z[:3]}:{z[3:]}"


def parse_day(text: str, what: str = "date") -> date:
    try:
        return date.fromisoformat(str(text).strip())
    except (TypeError, ValueError):
        raise ToolError(f"{what} must be YYYY-MM-DD, not {text!r}") from None


def noon(day: date, tz: timezone) -> str:
    return datetime(day.year, day.month, day.day, 12, tzinfo=tz).isoformat(timespec="seconds")


def day_of(value: Any) -> date | None:
    return date.fromisoformat(str(value)[:10]) if value else None


def slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48] or "x"


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return " ".join(text.casefold().split())


def cols(*names: str) -> list[str]:
    return [x for c in names for x in ("--column", c)]


def cents(value: Any, what: str = "amount") -> int:
    """Pesos as the owner says them ($25,000.50, 25000, 25 000) to integer cents. Never floats."""
    raw = re.sub(r"(?i)\s|\$|mxn|pesos?", "", str(value or ""))
    if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d{1,2})?", raw):
        raw = raw.replace(",", "")
    if not re.fullmatch(r"\d+(\.\d{1,2})?", raw):
        raise ToolError(f"{what} must be an amount in pesos like 25000 or 25,000.50, not {value!r}")
    c = int((Decimal(raw) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    if c > MAX_MONEY:
        raise ToolError(f"{what} {money(c)} is too large; check it.")
    return c


def money(c: int | None) -> str | None:
    if c is None:
        return None
    return f"{'-' if c < 0 else ''}${abs(c) // 100:,}.{abs(c) % 100:02d}"


def text_field(value: str | None, what: str) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if len(value) > MAX_TEXT:
        raise ToolError(f"{what} is {len(value)} characters; keep it under {MAX_TEXT}.")
    return value or None


def seats_value(value: Any, what: str, allow_zero: bool = False) -> int:
    if not re.fullmatch(r"\d{1,5}", str(value).strip()):
        raise ToolError(f"{what} must be a whole number, not {value!r}")
    n = int(str(value).strip())
    if n > MAX_SEATS or (n == 0 and not allow_zero):
        raise ToolError(f"{what} must be between {0 if allow_zero else 1} and {MAX_SEATS}, not {n}.")
    return n


def parse_offset(text: str) -> str:
    """-12m, -2w, -3d, 0d, +1w: months, weeks or days before (-) or after (+) the event day."""
    raw = str(text or "").strip().lower().replace(" ", "")
    m = OFFSET_RE.fullmatch(raw)
    if not m:
        raise ToolError(f"An offset is like -12m, -2w, -3d, 0d or +1w (months, weeks, days), not {text!r}")
    sign = "-" if m.group(1) == "-" else ("+" if m.group(2) != "0" else "")
    return f"{sign}{int(m.group(2))}{m.group(3)}"


def shift_months(day: date, months: int) -> date:
    y, m = divmod(day.month - 1 + months, 12)
    year, month = day.year + y, m + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def apply_offset(event_day: date, offset: str) -> date:
    m = OFFSET_RE.fullmatch(offset)
    n = int(m.group(2)) * (-1 if m.group(1) == "-" else 1)
    if m.group(3) == "m":
        return shift_months(event_day, n)
    return event_day + timedelta(days=n * (7 if m.group(3) == "w" else 1))


def offset_of(event_day: date, due: date) -> str:
    """A fixed day as an offset in whole months when it falls on one, else in days."""
    for months in range(-36, 37):
        if months and shift_months(event_day, months) == due:
            return f"{'+' if months > 0 else '-'}{abs(months)}m"
    days = (due - event_day).days
    return f"{'+' if days > 0 else ('-' if days < 0 else '')}{abs(days)}d"


def split_by_percent(total: int, areas: list[dict]) -> dict[str, int]:
    """Whole pesos by largest remainder, so the parts add up to the total exactly; leftover cents go to the last."""
    weighted = [a for a in areas if a.get("percent")]
    if not weighted:
        return {}
    pesos, extra = divmod(total, 100)
    whole = sum(a["percent"] for a in weighted)
    raw = [(a["key"], pesos * a["percent"] / whole) for a in weighted]
    base = {k: int(v) for k, v in raw}
    left = pesos - sum(base.values())
    for k, _ in sorted(raw, key=lambda kv: -(kv[1] - int(kv[1])))[:left]:
        base[k] += 1
    out = {k: v * 100 for k, v in base.items()}
    out[weighted[-1]["key"]] += extra
    return out


def program_sort(hhmm: str) -> tuple[int, str]:
    h = int(hhmm[:2])
    return (1 if h < 6 else 0, hhmm)


def read_text(path: str) -> str:
    try:
        return (sys.stdin.buffer.read() if path == "-" else Path(path).read_bytes()).decode("utf-8-sig")
    except (OSError, UnicodeDecodeError) as error:
        raise ToolError(f"Cannot read {path} as UTF-8 text: {getattr(error, 'strerror', None) or error}") from error


# -- the plan: everything of every event, read once per command ------------------------------
EVENT_FACTS = ("ev_kind", "ev_date", "ev_created", "ev_template", "ev_hosts", "ev_capacity", "ev_budget", "ev_state")
TASK_FACTS = ("of_event/key", "task_offset", "task_date", "task_area", "task_state", "task_done_on", "task_note",
              "task_seq", "task_origin")
LINE_FACTS = ("of_event/key", "bl_area", "bl_amount", "bl_percent", "bl_seq")
VENDOR_FACTS = ("of_event/key", "v_area", "v_total", "v_state", "v_due", "v_contact", "v_note")
SPONSOR_FACTS = ("of_event/key", "sp_role", "sp_state", "sp_covers", "sp_amount", "sp_area")
GUEST_FACTS = ("of_event/key", "g_group", "g_seats", "g_rsvp", "g_coming", "g_diet", "g_note", "g_table/key",
               "g_state")
TABLE_FACTS = ("of_event/key", "tb_seats", "tb_order", "tb_state")
PROGRAM_FACTS = ("of_event/key", "pg_time", "pg_vendor/key", "pg_state")
TEMPLATE_FACTS = ("tpl_kind", "tpl_json", "tpl_origin", "tpl_state")


def strip(row: dict, names: tuple[str, ...]) -> dict:
    out = {"key": row["key"], "name": row["name"]}
    for n in names:
        out[n.split("/")[0]] = row.get(f"fact:{n}")
    return out


class Plan:
    def __init__(self, mem: Memory, tz: timezone, today: date):
        self.mem, self.tz, self.today = mem, tz, today
        facts = lambda names: cols("key", "name", *(f"fact:{f}" for f in names))
        (settings, events, tasks, lines, vendors, payments, sponsors, guests, tables, program,
         templates) = mem.rows_many([
            ("--entity-type", "settings", "--where", "key = settings:eventos-sociales", "--column", "key"),
            ("--entity-type", "social_event", *facts(EVENT_FACTS)),
            ("--entity-type", "event_task", *facts(TASK_FACTS)),
            ("--entity-type", "budget_line", *facts(LINE_FACTS)),
            ("--entity-type", "vendor", *facts(VENDOR_FACTS)),
            ("--event-type", "payment_made", *cols("key", "occurred_at", "attr:pay_amount", "attr:pay_area",
                                                   "attr:pay_payer", "attr:pay_note", "link:paid_to/key",
                                                   "link:for_event/key")),
            ("--entity-type", "sponsor", *facts(SPONSOR_FACTS)),
            ("--entity-type", "guest", *facts(GUEST_FACTS)),
            ("--entity-type", "seating_table", *facts(TABLE_FACTS)),
            ("--entity-type", "program_item", *facts(PROGRAM_FACTS)),
            ("--entity-type", "event_template", *facts(TEMPLATE_FACTS))])
        if not settings:
            raise ToolError("This memory has no eventos-sociales settings yet: run TOOL setup first.", MEMORY_ERROR)
        self.events = {r["key"]: strip(r, EVENT_FACTS) for r in events}
        for e in self.events.values():
            e["date"], e["created"] = day_of(e["ev_date"]), day_of(e["ev_created"])
            e["state"] = e["ev_state"] or "planning"
        self.tasks = {r["key"]: strip(r, TASK_FACTS) for r in tasks}
        self.lines = {r["key"]: strip(r, LINE_FACTS) for r in lines}
        self.vendors = {r["key"]: strip(r, VENDOR_FACTS) for r in vendors}
        self.payments = [{"key": r["key"], "day": day_of(r["occurred_at"]), "amount": r["attr:pay_amount"],
                          "area": r["attr:pay_area"], "payer": r["attr:pay_payer"], "note": r["attr:pay_note"],
                          "vendor": r["link:paid_to/key"], "event": r["link:for_event/key"]} for r in payments]
        self.sponsors = {r["key"]: strip(r, SPONSOR_FACTS) for r in sponsors}
        self.guests = {r["key"]: strip(r, GUEST_FACTS) for r in guests}
        self.tables = {r["key"]: strip(r, TABLE_FACTS) for r in tables}
        self.program = {r["key"]: strip(r, PROGRAM_FACTS) for r in program}
        self.templates = {r["key"]: strip(r, TEMPLATE_FACTS) for r in templates}

    # -- lookups ------------------------------------------------------------------------------
    def event(self, ref: str | None, planning_only: bool = False) -> dict:
        if not ref:
            live = [e for e in self.events.values() if e["state"] == "planning"]
            if len(live) == 1:
                return live[0]
            if not live:
                raise ToolError("There is no event in planning yet: create one with TOOL event.")
            raise ToolError(f"There are {len(live)} events in planning; say which with --event: "
                            + ", ".join(f"{e['name']} ({e['key']})" for e in self.ordered_events()) + ".")
        key = ref if ref.startswith("event:") else f"event:{slug(ref)}"
        found = self.events.get(key) or next((e for e in self.events.values() if norm(e["name"]) == norm(ref)), None)
        if not found:
            names = ", ".join(f"{e['name']} ({e['key']})" for e in self.ordered_events()) or "none yet"
            raise ToolError(f"There is no event {ref!r}. Events: {names}.")
        if planning_only and found["state"] != "planning":
            raise ToolError(f"{found['name']} is {found['state']}; reopen it (TOOL event --state planning) to change it.")
        return found

    def ordered_events(self, include_closed: bool = True) -> list[dict]:
        return sorted((e for e in self.events.values() if include_closed or e["state"] == "planning"),
                      key=lambda e: (e["state"] != "planning", e["date"] or date.max, e["key"]))

    def of(self, items: dict[str, dict], ev: dict) -> list[dict]:
        return [x for x in items.values() if x["of_event"] == ev["key"]]

    def areas(self, ev: dict) -> list[dict]:
        return sorted(self.of(self.lines, ev), key=lambda l: (l["bl_seq"] or 999, l["key"]))

    def area(self, ev: dict, ref: str | None, allow_general: bool = True) -> str:
        if ref is None:
            return GENERAL
        s = slug(ref)
        if s == GENERAL and allow_general:
            return GENERAL
        for line in self.areas(ev):
            if line["bl_area"] == s or norm(line["name"]) == norm(ref):
                return line["bl_area"]
        names = ", ".join(f"{l['name']} ({l['bl_area']})" for l in self.areas(ev))
        raise ToolError(f"{ev['name']} has no budget area {ref!r}. Areas: {names or 'none'}"
                        f"{', or general' if allow_general else ''}. A new area: TOOL budget --set <area>=<amount>.")

    def area_label(self, ev: dict, area: str | None) -> str:
        if not area or area == GENERAL:
            return GENERAL
        return next((l["name"] for l in self.areas(ev) if l["bl_area"] == area), area)

    def find(self, items: dict[str, dict], ev: dict, ref: str, what: str, prefix: str) -> dict:
        ref = ref.strip()
        key = ref if ref.startswith(f"{prefix}:") else f"{prefix}:{ev['key'].split(':', 1)[1]}--{slug(ref)}"
        found = items.get(key) if items.get(key, {}).get("of_event") == ev["key"] else None
        found = found or next((x for x in self.of(items, ev) if norm(x["name"]) == norm(ref)), None)
        if not found:
            hits = [x for x in self.of(items, ev) if norm(ref) in norm(x["name"])]
            if len(hits) == 1:
                return hits[0]
            hint = ("; it could be " + ", ".join(f"{x['name']} ({x['key']})" for x in hits[:8])) if hits else ""
            raise ToolError(f"{ev['name']} has no {what} {ref!r}{hint}.")
        return found

    def child_key(self, prefix: str, ev: dict, name: str) -> str:
        return f"{prefix}:{ev['key'].split(':', 1)[1]}--{slug(name)}"

    # -- tasks --------------------------------------------------------------------------------
    def due(self, t: dict, ev: dict) -> date | None:
        if t["task_date"]:
            return day_of(t["task_date"])
        if t["task_offset"] and ev["date"]:
            return apply_offset(ev["date"], t["task_offset"])
        return None

    def task_view(self, t: dict, ev: dict) -> dict:
        due = self.due(t, ev)
        out = {"task": t["key"], "title": t["name"], "area": self.area_label(ev, t["task_area"]),
               "state": t["task_state"] or "pending", "due": due.isoformat() if due else None,
               "when": t["task_offset"] or (offset_of(ev["date"], due) if due and ev["date"] else None)}
        if due and out["state"] == "pending":
            out["days_left"] = (due - self.today).days
            if due < self.today and ev["created"] and due < ev["created"]:
                out["late_from_start"] = True
        if t["task_done_on"]:
            out["done_on"] = day_of(t["task_done_on"]).isoformat()
        if t["task_note"]:
            out["note"] = t["task_note"]
        if t["task_origin"] == "owner":
            out["added_by_owner"] = True
        return out

    def ordered_tasks(self, ev: dict) -> list[dict]:
        return sorted(self.of(self.tasks, ev), key=lambda t: (self.due(t, ev) or date.max, t["task_seq"] or 0))

    # -- money --------------------------------------------------------------------------------
    def event_payments(self, ev: dict) -> list[dict]:
        return sorted((p for p in self.payments if p["event"] == ev["key"]), key=lambda p: (p["day"], p["key"]))

    def vendor_view(self, v: dict, ev: dict) -> dict:
        paid = sum(p["amount"] for p in self.event_payments(ev) if p["vendor"] == v["key"])
        total = v["v_total"]
        out = {"vendor": v["key"], "name": v["name"], "area": self.area_label(ev, v["v_area"]),
               "state": v["v_state"] or "quoting", "total": money(total), "paid": money(paid)}
        if total is not None:
            out["balance"] = money(total - paid)
            if paid > total:
                out["overpaid"] = money(paid - total)
        due = day_of(v["v_due"])
        if due:
            out["pay_off_by"] = due.isoformat()
            if total is not None and total - paid > 0:
                out["days_to_pay_off"] = (due - self.today).days
        for k, name in (("v_contact", "contact"), ("v_note", "note")):
            if v[k]:
                out[name] = v[k]
        return out

    def budget(self, ev: dict) -> dict:
        lines = self.areas(ev)
        vendors = [v for v in self.of(self.vendors, ev) if v["v_state"] == "hired"]
        pays = self.event_payments(ev)
        sponsors = [s for s in self.of(self.sponsors, ev) if s["sp_state"] == "accepted"]
        keys = [l["bl_area"] for l in lines]
        for x in [v["v_area"] for v in vendors] + [p["area"] for p in pays] + [s["sp_area"] for s in sponsors]:
            if x and x not in keys:
                keys.append(x)
        rows, totals = [], {"planned": 0, "hired": 0, "sponsors": 0, "hosts_share": 0, "paid": 0, "owed": 0}
        for area in keys:
            line = next((l for l in lines if l["bl_area"] == area), None)
            planned = line["bl_amount"] if line else None
            hired = sum(v["v_total"] or 0 for v in vendors if v["v_area"] == area)
            loose = sum(p["amount"] for p in pays if p["area"] == area and not p["vendor"])
            committed = hired + loose
            covered = sum(s["sp_amount"] or 0 for s in sponsors if s["sp_area"] == area)
            share = max(committed - covered, 0)
            paid = sum(p["amount"] for p in pays if p["area"] == area)
            row = {"area": area, "label": self.area_label(ev, area), "planned": money(planned),
                   "suggested_percent": line["bl_percent"] if line else None,
                   "hired": money(hired), "paid_without_vendor": money(loose) if loose else None,
                   "covered_by_sponsors": money(covered) if covered else None, "hosts_share": money(share),
                   "paid": money(paid), "owed": money(max(committed - paid, 0))}
            if planned is not None:
                row["left"] = money(planned - share)
                if share > planned:
                    row["over_by"] = money(share - planned)
            rows.append(row)
            totals["planned"] += planned or 0
            totals["hired"] += committed
            totals["sponsors"] += covered
            totals["hosts_share"] += share
            totals["paid"] += paid
            totals["owed"] += max(committed - paid, 0)
        total = ev["ev_budget"]
        out = {"total_budget": money(total), "areas": rows, **{k: money(v) for k, v in totals.items()},
               "note": "hosts_share = hired (and paid without a vendor) minus what accepted sponsors cover; "
                       "left and over_by compare it with the planned amount; payments count whoever made them"}
        if total is not None:
            out["unplanned"] = money(total - totals["planned"])
            out["left_of_total"] = money(total - totals["hosts_share"])
            if totals["hosts_share"] > total:
                out["over_total_by"] = money(totals["hosts_share"] - total)
        return out

    # -- guests and tables ----------------------------------------------------------------------
    def live_guests(self, ev: dict) -> list[dict]:
        return sorted((g for g in self.of(self.guests, ev) if (g["g_state"] or "active") == "active"),
                      key=lambda g: (norm(g["g_group"] or ""), norm(g["name"])))

    @staticmethod
    def expected(g: dict) -> int:
        """Places an invitation takes: what was confirmed, all its seats while pending, none if declined."""
        rsvp = g["g_rsvp"] or "pending"
        if rsvp == "yes":
            return g["g_coming"] or 0
        return 0 if rsvp == "no" else (g["g_seats"] or 0)

    def live_tables(self, ev: dict) -> list[dict]:
        return sorted((t for t in self.of(self.tables, ev) if (t["tb_state"] or "active") == "active"),
                      key=lambda t: (t["tb_order"] or 0, t["key"]))

    def guest_view(self, g: dict) -> dict:
        out = {"guest": g["key"], "name": g["name"], "group": g["g_group"], "seats": g["g_seats"],
               "rsvp": g["g_rsvp"] or "pending"}
        if out["rsvp"] == "yes":
            out["coming"] = g["g_coming"]
        if g["g_table"]:
            out["table"] = self.tables.get(g["g_table"], {}).get("name")
        for k, name in (("g_diet", "diet"), ("g_note", "note")):
            if g[k]:
                out[name] = g[k]
        if g["g_state"] == "removed":
            out["removed"] = True
        return out

    def guest_counts(self, ev: dict) -> dict:
        gs = self.live_guests(ev)
        invited = sum(g["g_seats"] or 0 for g in gs)
        yes = [g for g in gs if g["g_rsvp"] == "yes"]
        no = [g for g in gs if g["g_rsvp"] == "no"]
        pending = [g for g in gs if (g["g_rsvp"] or "pending") == "pending"]
        confirmed = sum(g["g_coming"] or 0 for g in yes)
        by_group: dict[str, dict] = {}
        for g in gs:
            b = by_group.setdefault(g["g_group"] or "(no group)",
                                    {"invitations": 0, "seats": 0, "confirmed": 0, "pending": 0})
            b["invitations"] += 1
            b["seats"] += g["g_seats"] or 0
            b["confirmed"] += (g["g_coming"] or 0) if g["g_rsvp"] == "yes" else 0
            b["pending"] += (g["g_seats"] or 0) if (g["g_rsvp"] or "pending") == "pending" else 0
        out = {"invitations": len(gs), "seats_invited": invited, "confirmed": confirmed,
               "declined": sum(g["g_seats"] or 0 for g in no) + sum((g["g_seats"] or 0) - (g["g_coming"] or 0)
                                                                    for g in yes),
               "pending_seats": sum(g["g_seats"] or 0 for g in pending), "pending_invitations": len(pending),
               "expected_at_most": confirmed + sum(g["g_seats"] or 0 for g in pending), "by_group": by_group,
               "diets": [{"name": g["name"], "diet": g["g_diet"]} for g in gs
                         if g["g_diet"] and g["g_rsvp"] != "no"]}
        if ev["ev_capacity"]:
            out["capacity"] = ev["ev_capacity"]
            out["over_capacity_if_all_pending_come"] = max(out["expected_at_most"] - ev["ev_capacity"], 0)
        return out

    def table_use(self, ev: dict) -> list[dict]:
        gs = self.live_guests(ev)
        out = []
        for t in self.live_tables(ev):
            here = [g for g in gs if g["g_table"] == t["key"]]
            used = sum(self.expected(g) for g in here)
            out.append({"table": t["key"], "name": t["name"], "seats": t["tb_seats"], "used": used,
                        "free": (t["tb_seats"] or 0) - used,
                        "guests": [{"name": g["name"], "places": self.expected(g), "rsvp": g["g_rsvp"] or "pending"}
                                   for g in here]})
        return out


# -- commands -------------------------------------------------------------------------------
def by_source(args, fallback: str) -> str:
    return getattr(args, "source", None) or fallback


def entity_write(mem: Memory, args, content: str, entity: dict, facts: list[tuple[str, Any]],
                 clear: list[str] = ()) -> dict:
    key = entity["key"]
    sets = [{"subject": key, "predicate": p, "value": v, "valid_from": "now"} for p, v in facts if v is not None]
    closes = [{"subject": key, "predicate": p, "at": "now", "if_present": True}
              for p in list(clear) + [p for p, v in facts if v is None]]
    return mem.write(args.by, by_source(args, content), entities=[entity], facts=sets,
                     **({"close": closes} if closes else {}))


def load_seed() -> dict:
    return json.loads(SEED.read_text(encoding="utf-8"))


def template_content(t: dict) -> dict:
    return json.loads(t["tpl_json"] or "{}")


def cmd_setup(mem: Memory, args, now: datetime) -> dict:
    seed = load_seed()
    result = mem.write(args.by, f"eventos-sociales seed v{seed['seed_version']}", "helper_command",
                       predicates=[{**p, "distinct_from_similar": True} for p in seed["predicates"]],
                       entities=seed["entities"])
    p = Plan(mem, now.tzinfo, now.date())
    installed, updated = [], []
    for t in seed["templates"]:
        content = json.dumps({"areas": t["areas"], "tasks": t["tasks"]}, ensure_ascii=False, sort_keys=True)
        have = p.templates.get(t["key"])
        if have and have["tpl_origin"] == "owner":
            continue
        if have and have["tpl_json"] == content and have["name"] == t["name"]:
            continue
        mem.write(args.by, f"eventos-sociales template {t['name']} (seed v{seed['seed_version']})", "helper_command",
                  entities=[{"key": t["key"], "type": "event_template", "name": t["name"],
                             **({"rename": True} if have and have["name"] != t["name"] else {})}],
                  facts=[{"subject": t["key"], "predicate": pr, "value": v, "valid_from": "now"}
                         for pr, v in (("tpl_kind", t["kind"]), ("tpl_json", content), ("tpl_origin", "seed"),
                                       ("tpl_state", (have or {}).get("tpl_state") or "active"))])
        (updated if have else installed).append(t["name"])
    return {"ok": True, "seed_version": seed["seed_version"], "templates_installed": installed,
            "templates_updated": updated, "warnings": result.get("warnings", [])}


def cmd_now(mem, args, now: datetime) -> dict:
    return {"ok": True, "today": now.date().isoformat(), "weekday": WEEKDAY_NAMES[now.weekday()],
            "time": now.strftime("%H:%M")}


def event_view(p: Plan, ev: dict) -> dict:
    tasks = p.of(p.tasks, ev)
    pending = [t for t in tasks if (t["task_state"] or "pending") == "pending"]
    out = {"event": ev["key"], "name": ev["name"], "kind": ev["ev_kind"], "hosts": ev["ev_hosts"],
           "date": ev["date"].isoformat() if ev["date"] else None,
           "weekday": WEEKDAY_NAMES[ev["date"].weekday()] if ev["date"] else None, "state": ev["state"],
           "template": ev["ev_template"], "capacity": ev["ev_capacity"], "total_budget": money(ev["ev_budget"]),
           "tasks": {"pending": len(pending), "done": sum(1 for t in tasks if t["task_state"] == "done"),
                     "dropped": sum(1 for t in tasks if t["task_state"] == "dropped")}}
    if ev["date"]:
        out["days_left"] = (ev["date"] - p.today).days
        out["weeks_left"] = round(out["days_left"] / 7, 1)
    return out


def cmd_event(mem: Memory, args, now: datetime) -> dict:
    p = Plan(mem, now.tzinfo, now.date())
    key = args.key if args.key.startswith("event:") else f"event:{slug(args.key)}"
    current = p.events.get(key)
    facts: list[tuple[str, Any]] = []
    clear: list[str] = []
    entity = {"key": key, "type": "social_event", "name": (args.name or (current or {}).get("name") or "").strip()}
    if not current:
        if not (args.name and args.date):
            raise ToolError(f"New event {key}: give it a --name and a --date (YYYY-MM-DD; an estimate is fine and can "
                            "change later).")
        day = parse_day(args.date, "--date")
        if day < now.date():
            raise ToolError(f"{day.isoformat()} already passed; an event to plan is in the future.")
        tpl = None
        if (args.template or "").lower() != "none":
            ref = args.template or args.kind
            if not ref:
                raise ToolError("Say which template (--template boda, see TOOL templates) or --template none.")
            tkey = ref if ref.startswith("template:") else f"template:{slug(ref)}"
            tpl = p.templates.get(tkey) or next((t for t in p.templates.values() if norm(t["name"]) == norm(ref)),
                                                None)
            if not tpl or tpl["tpl_state"] == "retired":
                names = ", ".join(f"{t['name']} ({t['key']})" for t in p.templates.values()
                                  if t["tpl_state"] != "retired")
                raise ToolError(f"There is no template {ref!r}. Templates: {names or 'none: run setup'}; "
                                "or --template none.")
        kind = args.kind or (tpl["tpl_kind"] if tpl else None)
        if not kind:
            raise ToolError("Say what kind of event it is (--kind boda, xv, bautizo, aniversario...).")
        facts += [("ev_kind", slug(kind)), ("ev_date", noon(day, now.tzinfo)), ("ev_created", noon(now.date(), now.tzinfo)),
                  ("ev_template", tpl["key"] if tpl else "none"), ("ev_state", "planning")]
    else:
        if args.name and args.name.strip() != current["name"]:
            entity["rename"] = True
        if args.template:
            raise ToolError("The template is applied when the event is created; add or drop tasks with TOOL task.")
        if args.kind:
            facts.append(("ev_kind", slug(args.kind)))
        if args.date:
            day = parse_day(args.date, "--date")
            facts.append(("ev_date", noon(day, now.tzinfo)))
    if args.hosts is not None:
        facts.append(("ev_hosts", text_field(args.hosts, "--hosts")))
    if args.capacity is not None:
        facts.append(("ev_capacity", seats_value(args.capacity, "--capacity") if args.capacity != "none" else None))
    if args.budget is not None:
        facts.append(("ev_budget", cents(args.budget, "--budget") if args.budget != "none" else None))
    if args.state:
        if args.state not in EVENT_STATES:
            raise ToolError(f"--state is {', '.join(EVENT_STATES)}.")
        if not current:
            raise ToolError("A new event starts in planning.")
        facts.append(("ev_state", args.state))
    if current and not facts and not entity.get("rename"):
        return {"ok": True, "unchanged": True, **event_view(p, current)}
    result = entity_write(mem, args, f"Event {entity['name']}", entity, facts, clear)
    created_tasks = created_areas = 0
    if not current and tpl:
        content = template_content(tpl)
        stem = key.split(":", 1)[1]
        ents, fs = [], []
        for seq, a in enumerate(content.get("areas", []), 1):
            k = f"budget_line:{stem}--{a['key']}"
            ents.append({"key": k, "type": "budget_line", "name": a["label"]})
            fs += [(k, "of_event", key), (k, "bl_area", a["key"]), (k, "bl_seq", seq)]
            if a.get("percent"):
                fs.append((k, "bl_percent", a["percent"]))
            created_areas += 1
        for seq, t in enumerate(content.get("tasks", []), 1):
            k = f"event_task:{stem}--{t['id']}"
            ents.append({"key": k, "type": "event_task", "name": t["title"]})
            fs += [(k, "of_event", key), (k, "task_offset", t["offset"]), (k, "task_area", t.get("area") or GENERAL),
                   (k, "task_state", "pending"), (k, "task_seq", seq), (k, "task_origin", "template")]
            created_tasks += 1
        mem.write(args.by, f"Template {tpl['name']} applied to {entity['name']}", "helper_command", entities=ents,
                  facts=[{"subject": s, "predicate": pr, "value": v, "valid_from": "now"} for s, pr, v in fs])
    p = Plan(mem, now.tzinfo, now.date())
    ev = p.events[key]
    out = {"ok": True, "created": not current, **event_view(p, ev), "warnings": result.get("warnings", [])}
    if not current:
        out |= {"tasks_created": created_tasks, "budget_areas_created": created_areas}
        late = [p.task_view(t, ev) for t in p.ordered_tasks(ev) if (p.due(t, ev) or date.max) < now.date()]
        if late:
            out["late_from_start"] = {"count": len(late), "tasks": late,
                                      "note": "these were due before planning began; the agent proposes what to do "
                                              "first, the owner decides"}
    if current and args.date:
        fixed_after = [p.task_view(t, ev) for t in p.of(p.tasks, ev) if t["task_date"]
                       and (t["task_state"] or "pending") == "pending" and day_of(t["task_date"]) > ev["date"]]
        out["date_changed"] = {"from": current["date"].isoformat(), "to": ev["date"].isoformat(),
                               "note": "tasks with an offset moved with the date; tasks with a fixed date did not"}
        if fixed_after:
            out["date_changed"]["fixed_tasks_after_the_event"] = fixed_after
    return out


def cmd_events(mem: Memory, args, now: datetime) -> dict:
    p = Plan(mem, now.tzinfo, now.date())
    return {"ok": True, "events": [event_view(p, e) for e in p.ordered_events(include_closed=args.all)]}


def cmd_templates(mem: Memory, args, now: datetime) -> dict:
    p = Plan(mem, now.tzinfo, now.date())
    out = []
    for t in sorted(p.templates.values(), key=lambda t: t["key"]):
        if t["tpl_state"] == "retired" and not args.all:
            continue
        c = template_content(t)
        view = {"template": t["key"], "name": t["name"], "kind": t["tpl_kind"], "origin": t["tpl_origin"],
                "state": t["tpl_state"] or "active", "tasks": len(c.get("tasks", [])),
                "areas": [{"area": a["key"], "label": a["label"], "suggested_percent": a.get("percent")}
                          for a in c.get("areas", [])]}
        if args.detail:
            view["task_list"] = c.get("tasks", [])
        out.append(view)
    return {"ok": True, "templates": out}


def cmd_template(mem: Memory, args, now: datetime) -> dict:
    p = Plan(mem, now.tzinfo, now.date())
    key = args.key if args.key.startswith("template:") else f"template:{slug(args.key)}"
    current = p.templates.get(key)
    if args.state:
        if args.state not in ("active", "retired") or not current:
            raise ToolError("--state is active or retired, for an existing template.")
        entity_write(mem, args, f"Template {current['name']} {args.state}",
                     {"key": key, "type": "event_template", "name": current["name"]}, [("tpl_state", args.state)])
        return {"ok": True, "template": key, "state": args.state}
    if not args.from_event:
        raise ToolError("Save a template from an event: --from-event <event> --name <name>.")
    if current and current["tpl_origin"] == "seed":
        raise ToolError(f"{key} comes with the howware and is updated with it; save yours under another key.")
    ev = p.event(args.from_event)
    if not ev["date"]:
        raise ToolError(f"{ev['name']} has no date.")
    tasks = []
    for t in p.ordered_tasks(ev):
        if t["task_state"] == "dropped":
            continue
        due = p.due(t, ev)
        tasks.append({"id": t["key"].split("--", 1)[-1], "title": t["name"], "area": t["task_area"] or GENERAL,
                      "offset": t["task_offset"] or offset_of(ev["date"], due)})
    total = ev["ev_budget"] or sum(l["bl_amount"] or 0 for l in p.areas(ev))
    areas = []
    for l in p.areas(ev):
        pct = round(100 * l["bl_amount"] / total) if total and l["bl_amount"] is not None else l["bl_percent"]
        areas.append({"key": l["bl_area"], "label": l["name"], **({"percent": pct} if pct else {})})
    name = (args.name or (current or {}).get("name") or ev["name"]).strip()
    content = json.dumps({"areas": areas, "tasks": tasks}, ensure_ascii=False, sort_keys=True)
    entity_write(mem, args, f"Template {name} saved from {ev['name']}",
                 {"key": key, "type": "event_template", "name": name,
                  **({"rename": True} if current and current["name"] != name else {})},
                 [("tpl_kind", ev["ev_kind"]), ("tpl_json", content), ("tpl_origin", "owner"), ("tpl_state", "active")])
    return {"ok": True, "template": key, "name": name, "replaced": bool(current), "tasks": len(tasks),
            "areas": areas, "note": "suggested shares come from this event's planned amounts when it has them"}


def cmd_agenda(mem: Memory, args, now: datetime) -> dict:
    p = Plan(mem, now.tzinfo, now.date())
    today = now.date()
    events = ([e for e in p.ordered_events(include_closed=False)] if args.event == "all"
              else [p.event(args.event)])
    weeks = args.weeks
    out = []
    for ev in events:
        late_start, slipped, this_week, coming, later = [], [], [], [], {}
        for t in p.ordered_tasks(ev):
            if (t["task_state"] or "pending") != "pending":
                continue
            due = p.due(t, ev)
            view = p.task_view(t, ev)
            if due is None:
                later.setdefault("no date", 0)
                later["no date"] += 1
            elif due < today:
                (late_start if view.get("late_from_start") else slipped).append(view)
            elif due <= today + timedelta(days=6):
                this_week.append(view)
            elif due <= today + timedelta(weeks=weeks):
                coming.append(view)
            else:
                m = due.strftime("%Y-%m")
                later[m] = later.get(m, 0) + 1
        due_pay = []
        for v in p.of(p.vendors, ev):
            if v["v_state"] != "hired":
                continue
            view = p.vendor_view(v, ev)
            if view.get("days_to_pay_off") is not None and view["days_to_pay_off"] <= weeks * 7:
                due_pay.append({k: view[k] for k in ("name", "balance", "pay_off_by", "days_to_pay_off")})
        out.append({**event_view(p, ev), "late": {"from_the_start": late_start, "slipped": slipped},
                    "this_week": this_week, f"next_{weeks}_weeks": coming, "later_by_month": later,
                    "payments_due": sorted(due_pay, key=lambda x: x["pay_off_by"]),
                    "rsvp_pending_invitations": p.guest_counts(ev)["pending_invitations"]})
    return {"ok": True, "today": today.isoformat(), "weekday": WEEKDAY_NAMES[today.weekday()], "events": out}


def cmd_tasks(mem: Memory, args, now: datetime) -> dict:
    p = Plan(mem, now.tzinfo, now.date())
    ev = p.event(args.event)
    tasks = p.ordered_tasks(ev)
    if args.state != "all":
        tasks = [t for t in tasks if (t["task_state"] or "pending") == args.state]
    if args.area:
        area = p.area(ev, args.area)
        tasks = [t for t in tasks if (t["task_area"] or GENERAL) == area]
    if args.search:
        words = norm(args.search).split()
        tasks = [t for t in tasks if all(w in norm(f"{t['name']} {t['task_note'] or ''}") for w in words)]
    return {"ok": True, "event": ev["name"], "shown": len(tasks), "tasks": [p.task_view(t, ev) for t in tasks]}


def cmd_task(mem: Memory, args, now: datetime) -> dict:
    p = Plan(mem, now.tzinfo, now.date())
    ev = p.event(args.event, planning_only=True)
    facts: list[tuple[str, Any]] = []
    clear: list[str] = []
    if args.key:
        t = p.find(p.tasks, ev, args.key, "task", "event_task")
        entity = {"key": t["key"], "type": "event_task", "name": t["name"]}
        if args.title and args.title.strip() != t["name"]:
            entity |= {"name": args.title.strip(), "rename": True}
    else:
        if not args.title:
            raise ToolError("A new task needs a --title (or --key to change one).")
        key = p.child_key("event_task", ev, args.title)
        if key in p.tasks:
            key += f"-{now.strftime('%Y%m%d%H%M%S')}"
        t = None
        entity = {"key": key, "type": "event_task", "name": args.title.strip()}
        if not (args.offset or args.due):
            raise ToolError("When is it due? --offset (like -3m, -2w, 0d: relative to the event day, moves with it) "
                            "or --due YYYY-MM-DD (fixed).")
        facts += [("of_event", ev["key"]), ("task_state", "pending"), ("task_origin", "owner"),
                  ("task_seq", len(p.of(p.tasks, ev)) + 1), ("task_area", p.area(ev, args.area))]
    if args.offset and args.due:
        raise ToolError("Give --offset or --due, not both.")
    if args.offset:
        facts.append(("task_offset", parse_offset(args.offset)))
        clear.append("task_date")
    if args.due:
        facts.append(("task_date", noon(parse_day(args.due, "--due"), now.tzinfo)))
        clear.append("task_offset")
    if t and args.area:
        facts.append(("task_area", p.area(ev, args.area)))
    if args.note is not None:
        facts.append(("task_note", text_field(args.note, "--note")))
    state = None
    if args.done or args.drop or args.reopen:
        if sum(map(bool, (args.done, args.drop, args.reopen))) > 1:
            raise ToolError("Give one of --done, --drop, --reopen.")
        if not t:
            raise ToolError("A new task starts pending.")
        state = "done" if args.done else ("dropped" if args.drop else "pending")
        if state == "done":
            day = parse_day(args.date, "--date") if args.date else now.date()
            if day > now.date():
                raise ToolError("A task can't be done on a future day.")
            facts += [("task_state", "done"), ("task_done_on", noon(day, now.tzinfo))]
        else:
            if args.drop and not args.reason:
                raise ToolError("Dropping a task needs --reason (the owner's words).")
            facts.append(("task_state", state))
            clear.append("task_done_on")
    if t and not facts and not clear and not entity.get("rename"):
        return {"ok": True, "unchanged": True, **p.task_view(t, ev)}
    result = entity_write(mem, args, args.reason or f"Task {entity['name']}", entity, facts, clear)
    p = Plan(mem, now.tzinfo, now.date())
    ev = p.events[ev["key"]]
    view = p.task_view(p.tasks[entity["key"]], ev)
    return {"ok": True, "created": t is None, **view, "warnings": result.get("warnings", [])}


def cmd_budget(mem: Memory, args, now: datetime) -> dict:
    p = Plan(mem, now.tzinfo, now.date())
    ev = p.event(args.event)
    changed = []
    if args.total is not None or args.set or args.apply_suggested:
        if ev["state"] != "planning":
            raise ToolError(f"{ev['name']} is {ev['state']}.")
    if args.total is not None:
        total = cents(args.total, "--total")
        entity_write(mem, args, f"Budget of {ev['name']}", {"key": ev["key"], "type": "social_event",
                                                           "name": ev["name"]}, [("ev_budget", total)])
        ev["ev_budget"] = total
        changed.append("total")
    suggestion = None
    lines = p.areas(ev)
    if ev["ev_budget"] is not None:
        split = split_by_percent(ev["ev_budget"], [{"key": l["bl_area"], "percent": l["bl_percent"]} for l in lines])
        suggestion = [{"area": l["bl_area"], "label": l["name"], "percent": l["bl_percent"],
                       "suggested": money(split.get(l["bl_area"]))} for l in lines if l["bl_area"] in split]
    wanted: dict[str, tuple[str, int]] = {}
    if args.apply_suggested:
        if not suggestion:
            raise ToolError("There is no suggestion: set a --total first, and the event needs areas with shares.")
        wanted |= {s["area"]: (s["label"], split[s["area"]]) for s in suggestion}
    for item in args.set or []:
        if "=" not in item:
            raise ToolError(f"--set is area=amount, not {item!r}")
        ref, raw = item.split("=", 1)
        line = next((l for l in lines if l["bl_area"] == slug(ref) or norm(l["name"]) == norm(ref)), None)
        if slug(ref) == GENERAL:
            raise ToolError("general is for tasks; a budget area needs its own name.")
        wanted[line["bl_area"] if line else slug(ref)] = (line["name"] if line else ref.strip(), cents(raw, ref))
    if wanted:
        ents, fs = [], []
        stem = ev["key"].split(":", 1)[1]
        for area, (label, amount) in wanted.items():
            line = next((l for l in lines if l["bl_area"] == area), None)
            k = line["key"] if line else f"budget_line:{stem}--{area}"
            ents.append({"key": k, "type": "budget_line", "name": label})
            fs.append((k, "bl_amount", amount))
            if not line:
                fs += [(k, "of_event", ev["key"]), (k, "bl_area", area), (k, "bl_seq", len(lines) + len(ents))]
        mem.write(args.by, by_source(args, f"Budget of {ev['name']}"), entities=ents,
                  facts=[{"subject": s, "predicate": pr, "value": v, "valid_from": "now"} for s, pr, v in fs])
        changed += sorted(wanted)
        p = Plan(mem, now.tzinfo, now.date())
        ev = p.events[ev["key"]]
    out = {"ok": True, "event": ev["name"], **p.budget(ev)}
    if changed:
        out["changed"] = changed
    if suggestion and (args.suggest or args.total is not None):
        out["suggested_split"] = suggestion
        out["suggested_note"] = "the template's suggested shares of the total; the hosts decide each amount"
    return out


def cmd_vendor(mem: Memory, args, now: datetime) -> dict:
    p = Plan(mem, now.tzinfo, now.date())
    ev = p.event(args.event, planning_only=True)
    key = p.child_key("vendor", ev, args.name)
    current = p.vendors.get(key) if args.key is None else p.find(p.vendors, ev, args.key, "vendor", "vendor")
    if args.key is None and current is None:
        current = next((v for v in p.of(p.vendors, ev) if norm(v["name"]) == norm(args.name)), None)
    entity = {"key": current["key"] if current else key, "type": "vendor", "name": args.name.strip()}
    if current and current["name"] != entity["name"]:
        entity["rename"] = True
    facts: list[tuple[str, Any]] = []
    if not current:
        if not args.area:
            raise ToolError("Which budget area is this vendor for? --area (see TOOL budget).")
        facts += [("of_event", ev["key"]), ("v_state", args.state or "quoting")]
    if args.area:
        facts.append(("v_area", p.area(ev, args.area, allow_general=False)))
    if args.total is not None:
        facts.append(("v_total", cents(args.total, "--total") if args.total != "none" else None))
    if args.state:
        if args.state not in VENDOR_STATES:
            raise ToolError(f"--state is {', '.join(VENDOR_STATES)}.")
        facts.append(("v_state", args.state))
    if args.pay_off_by is not None:
        facts.append(("v_due", noon(parse_day(args.pay_off_by, "--pay-off-by"), now.tzinfo)
                      if args.pay_off_by != "none" else None))
    if args.contact is not None:
        facts.append(("v_contact", text_field(args.contact, "--contact")))
    if args.note is not None:
        facts.append(("v_note", text_field(args.note, "--note")))
    if current and not facts and not entity.get("rename"):
        return {"ok": True, "unchanged": True, **p.vendor_view(current, ev)}
    state = dict(facts).get("v_state") or (current or {}).get("v_state")
    total = dict(facts).get("v_total", (current or {}).get("v_total"))
    if state == "hired" and total is None:
        raise ToolError("A hired vendor needs its contract --total (what was agreed), so balances are exact.")
    result = entity_write(mem, args, f"Vendor {entity['name']}", entity, facts)
    p = Plan(mem, now.tzinfo, now.date())
    return {"ok": True, "created": not current, **p.vendor_view(p.vendors[entity["key"]], p.events[ev["key"]]),
            "warnings": result.get("warnings", [])}


def cmd_vendors(mem: Memory, args, now: datetime) -> dict:
    p = Plan(mem, now.tzinfo, now.date())
    ev = p.event(args.event)
    vs = [v for v in p.of(p.vendors, ev) if args.all or v["v_state"] != "discarded"]
    if args.area:
        area = p.area(ev, args.area, allow_general=False)
        vs = [v for v in vs if v["v_area"] == area]
    views = sorted((p.vendor_view(v, ev) for v in vs), key=lambda v: (v["state"] != "hired", v["area"], v["name"]))
    hired = [v for v in views if v["state"] == "hired"]
    return {"ok": True, "event": ev["name"], "vendors": views,
            "hired_total": money(sum(v["v_total"] or 0 for v in vs if v["v_state"] == "hired")),
            "balance_total": money(sum(max((v["v_total"] or 0) - sum(x["amount"] for x in p.event_payments(ev)
                                                                      if x["vendor"] == v["key"]), 0)
                                       for v in vs if v["v_state"] == "hired")),
            "hired": len(hired)}


def cmd_pay(mem: Memory, args, now: datetime) -> dict:
    p = Plan(mem, now.tzinfo, now.date())
    ev = p.event(args.event)
    amount = cents(args.amount, "--amount")
    if amount == 0:
        raise ToolError("A payment of $0.00 is not a payment.")
    day = parse_day(args.date, "--date") if args.date else now.date()
    if day > now.date():
        raise ToolError(f"{day.isoformat()} hasn't happened yet: record a payment once it is made.")
    vendor = None
    if args.vendor:
        vendor = p.find(p.vendors, ev, args.vendor, "vendor", "vendor")
        if vendor["v_state"] == "discarded":
            raise ToolError(f"{vendor['name']} is discarded; change its state first if they were paid.")
        area = vendor["v_area"]
    elif args.area:
        area = p.area(ev, args.area, allow_general=False)
    else:
        raise ToolError("Who was paid? --vendor, or --area for a payment without a vendor.")
    payer = text_field(args.payer, "--payer")
    if not payer:
        raise ToolError("Who paid? --payer (the couple, the bride's parents, a sponsor...).")
    key = "PAY_" + hashlib.sha256("\x1f".join([ev["key"], vendor["key"] if vendor else area, day.isoformat(),
                                               str(amount), norm(payer), args.nonce or ""]).encode()).hexdigest()[:16]
    if any(x["key"] == key for x in p.payments):
        return {"ok": True, "unchanged": True, "payment": key,
                "message": "This same payment (vendor, day, amount, payer) is already recorded; if it is a second "
                           "one, repeat with --nonce 2."}
    attrs = {"pay_amount": amount, "pay_area": area, "pay_payer": payer}
    if args.note:
        attrs["pay_note"] = text_field(args.note, "--note")
    links = [{"predicate": "for_event", "entity": ev["key"]}]
    if vendor:
        links.append({"predicate": "paid_to", "entity": vendor["key"]})
    stored = mem.write_new(args.by, by_source(args, f"Payment of {money(amount)}"), [{
        "key": key, "type": "payment_made", "occurred_at": noon(day, now.tzinfo),
        "summary": f"{money(amount)} to {vendor['name'] if vendor else p.area_label(ev, area)} by {payer}"[:160],
        "attributes": attrs, "links": links}], now)
    p = Plan(mem, now.tzinfo, now.date())
    out = {"ok": True, "created": True, "payment": stored[key], "date": day.isoformat(), "amount": money(amount),
           "payer": payer, "area": p.area_label(ev, area)}
    if vendor:
        out["vendor"] = p.vendor_view(p.vendors[vendor["key"]], p.events[ev["key"]])
    return out


def cmd_unpay(mem: Memory, args, now: datetime) -> dict:
    p = Plan(mem, now.tzinfo, now.date())
    pay = next((x for x in p.payments if x["key"] == args.key.strip()), None)
    if not pay:
        raise ToolError(f"There is no payment {args.key!r} (see TOOL payments).")
    mem.run("void", "--event", pay["key"], "--reason", args.reason, "--by", args.by)
    return {"ok": True, "voided": pay["key"], "amount": money(pay["amount"]), "date": pay["day"].isoformat()}


def cmd_payments(mem: Memory, args, now: datetime) -> dict:
    p = Plan(mem, now.tzinfo, now.date())
    ev = p.event(args.event)
    pays = p.event_payments(ev)
    if args.payer:
        pays = [x for x in pays if norm(args.payer) in norm(x["payer"])]
    by_payer: dict[str, int] = {}
    by_area: dict[str, int] = {}
    for x in pays:
        by_payer[x["payer"]] = by_payer.get(x["payer"], 0) + x["amount"]
        label = p.area_label(ev, x["area"])
        by_area[label] = by_area.get(label, 0) + x["amount"]
    return {"ok": True, "event": ev["name"], "count": len(pays), "total": money(sum(x["amount"] for x in pays)),
            "by_payer": {k: money(v) for k, v in sorted(by_payer.items(), key=lambda kv: -kv[1])},
            "by_area": {k: money(v) for k, v in sorted(by_area.items(), key=lambda kv: -kv[1])},
            "payments": [{"payment": x["key"], "date": x["day"].isoformat(), "amount": money(x["amount"]),
                          "to": p.vendors.get(x["vendor"], {}).get("name") if x["vendor"] else None,
                          "area": p.area_label(ev, x["area"]), "payer": x["payer"], "note": x["note"]} for x in pays]}


def sponsor_view(p: Plan, s: dict, ev: dict) -> dict:
    return {"sponsor": s["key"], "role": s["sp_role"], "names": s["name"], "state": s["sp_state"] or "to_ask",
            "covers": s["sp_covers"], "amount": money(s["sp_amount"]),
            "area": p.area_label(ev, s["sp_area"]) if s["sp_area"] else None}


def cmd_sponsor(mem: Memory, args, now: datetime) -> dict:
    p = Plan(mem, now.tzinfo, now.date())
    ev = p.event(args.event, planning_only=True)
    key = p.child_key("sponsor", ev, args.role)
    current = p.sponsors.get(key)
    names = (args.names or (current or {}).get("name") or "").strip()
    if not names:
        raise ToolError("Who are they? --names, as the owner says it (\"Tíos Ana y Luis\"), or \"por definir\".")
    entity = {"key": key, "type": "sponsor", "name": names}
    if current and current["name"] != names:
        entity["rename"] = True
    facts: list[tuple[str, Any]] = []
    if not current:
        facts += [("of_event", ev["key"]), ("sp_role", args.role.strip()), ("sp_state", args.state or "to_ask")]
    elif args.state:
        facts.append(("sp_state", args.state))
    if args.state and args.state not in SPONSOR_STATES:
        raise ToolError(f"--state is {', '.join(SPONSOR_STATES)}.")
    if args.state == "removed" and not args.reason:
        raise ToolError("Removing a sponsor needs --reason (the owner's words).")
    if args.covers is not None:
        facts.append(("sp_covers", text_field(args.covers, "--covers")))
    if args.amount is not None:
        facts.append(("sp_amount", cents(args.amount, "--amount") if args.amount != "none" else None))
    if args.area is not None:
        facts.append(("sp_area", p.area(ev, args.area, allow_general=False) if args.area != "none" else None))
    amount = dict(facts).get("sp_amount", (current or {}).get("sp_amount"))
    area = dict(facts).get("sp_area", (current or {}).get("sp_area"))
    if amount and not area:
        raise ToolError("An amount covered needs the budget --area it covers, so the hosts' share is exact.")
    if current and not facts and not entity.get("rename"):
        return {"ok": True, "unchanged": True, **sponsor_view(p, current, ev)}
    result = entity_write(mem, args, args.reason or f"Sponsor {args.role}", entity, facts)
    p = Plan(mem, now.tzinfo, now.date())
    return {"ok": True, "created": not current, **sponsor_view(p, p.sponsors[key], p.events[ev["key"]]),
            "warnings": result.get("warnings", [])}


def cmd_sponsors(mem: Memory, args, now: datetime) -> dict:
    p = Plan(mem, now.tzinfo, now.date())
    ev = p.event(args.event)
    ss = [s for s in p.of(p.sponsors, ev) if args.all or s["sp_state"] != "removed"]
    views = sorted((sponsor_view(p, s, ev) for s in ss), key=lambda s: (s["state"], norm(s["role"])))
    counts: dict[str, int] = {}
    for s in views:
        counts[s["state"]] = counts.get(s["state"], 0) + 1
    covered = sum(s["sp_amount"] or 0 for s in ss if s["sp_state"] == "accepted")
    return {"ok": True, "event": ev["name"], "sponsors": views, "by_state": counts, "covered_total": money(covered)}


def parse_rsvp(value: Any) -> str:
    r = RSVP.get(norm(value)) or RSVP.get(str(value or "").strip().lower())
    if not r:
        raise ToolError(f"RSVP is pending, yes or no (pendiente, sí, no), not {value!r}")
    return r


def guest_facts(p: Plan, ev: dict, current: dict | None, data: dict) -> list[tuple[str, Any]]:
    facts: list[tuple[str, Any]] = []
    seats = seats_value(data["seats"], "seats") if data.get("seats") not in (None, "") else None
    if not current:
        facts += [("of_event", ev["key"]), ("g_state", "active"), ("g_seats", seats or 1)]
    elif seats is not None:
        facts.append(("g_seats", seats))
    seats = seats or (current or {}).get("g_seats") or 1
    if data.get("group") not in (None, ""):
        facts.append(("g_group", text_field(data["group"], "group")))
    rsvp = parse_rsvp(data["rsvp"]) if data.get("rsvp") not in (None, "") else None
    coming = data.get("coming")
    if rsvp:
        facts.append(("g_rsvp", rsvp))
    effective = rsvp or (current or {}).get("g_rsvp") or "pending"
    if coming not in (None, ""):
        coming = seats_value(coming, "coming", allow_zero=True)
        if effective != "yes" and coming:
            raise ToolError("Places coming are for a confirmed invitation (rsvp yes).")
        if coming == 0 and effective == "yes":
            raise ToolError("Confirmed with 0 places is a 'no': use rsvp no.")
    elif rsvp == "yes":
        coming = (current or {}).get("g_coming") or seats
    if effective == "yes" and coming is not None:
        if coming > seats:
            raise ToolError(f"{coming} coming is more than the {seats} seats invited; raise the seats first if "
                            "the owner agrees.")
        facts.append(("g_coming", coming))
    elif rsvp in ("pending", "no"):
        facts.append(("g_coming", None))
    elif seats is not None and current and current.get("g_coming") and current["g_coming"] > seats:
        raise ToolError(f"{current['g_coming']} are confirmed; seats can't go below that.")
    for k, name in (("g_diet", "diet"), ("g_note", "note")):
        if data.get(name) is not None:
            facts.append((k, text_field(str(data[name]), name)))
    return facts


def cmd_guest(mem: Memory, args, now: datetime) -> dict:
    p = Plan(mem, now.tzinfo, now.date())
    ev = p.event(args.event, planning_only=True)
    if args.key:
        current = p.find(p.guests, ev, args.key, "invitation", "guest")
    else:
        if not args.name:
            raise ToolError("Give the invitation's --name (or --key to change one).")
        key = p.child_key("guest", ev, args.name)
        current = p.guests.get(key) or next((g for g in p.of(p.guests, ev) if norm(g["name"]) == norm(args.name)),
                                             None)
    key = current["key"] if current else p.child_key("guest", ev, args.name)
    name = (args.rename or (current["name"] if current else args.name)).strip()
    entity = {"key": key, "type": "guest", "name": name}
    if current and current["name"] != name:
        entity["rename"] = True
    if args.remove:
        if not current:
            raise ToolError(f"There is no invitation {args.name or args.key!r}.")
        if not args.reason:
            raise ToolError("Removing an invitation needs --reason (the owner's words).")
        entity_write(mem, args, args.reason, entity, [("g_state", "removed")], ["g_table"])
        return {"ok": True, "removed": True, "guest": key, "name": name,
                "note": "it stops counting and stays in the memory file"}
    facts = guest_facts(p, ev, current, {"seats": args.seats, "group": args.group, "rsvp": args.rsvp,
                                         "coming": args.coming, "diet": args.diet, "note": args.note})
    if current and current["g_state"] == "removed":
        facts.append(("g_state", "active"))
    if current and not facts and not entity.get("rename"):
        return {"ok": True, "unchanged": True, **p.guest_view(current)}
    result = entity_write(mem, args, f"Invitation {name}", entity, facts)
    p = Plan(mem, now.tzinfo, now.date())
    ev = p.events[ev["key"]]
    g = p.guests[key]
    out = {"ok": True, "created": not current, **p.guest_view(g), "warnings": result.get("warnings", [])}
    if g["g_table"]:
        use = next(t for t in p.table_use(ev) if t["table"] == g["g_table"])
        if use["free"] < 0:
            out["table_over_capacity"] = {"table": use["name"], "seats": use["seats"], "used": use["used"]}
    c = p.guest_counts(ev)
    out["totals"] = {k: c[k] for k in ("invitations", "seats_invited", "confirmed", "pending_seats", "declined")}
    return out


def rows_from_file(path: str) -> list[dict]:
    text = read_text(path)
    stripped = text.lstrip()
    if stripped.startswith("[") or stripped.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as error:
            raise ToolError(f"{path} is not JSON (line {error.lineno}: {error.msg}).") from error
        if not isinstance(data, list) or not all(isinstance(x, dict) for x in data):
            raise ToolError('A JSON guest list is a list: [{"name": ..., "group": ..., "seats": 2}, ...]')
        return data
    try:
        dialect = csv.Sniffer().sniff(text[:2048], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    headers = {norm(h): h for h in reader.fieldnames or []}
    mapping = {field: next((headers[norm(a)] for a in aliases if norm(a) in headers), None)
               for field, aliases in CSV_COLUMNS.items()}
    if not mapping["name"]:
        raise ToolError(f"The CSV needs a name column (nombre or name); it has: {', '.join(reader.fieldnames or [])}.")
    return [{f: (row.get(col) or "").strip() for f, col in mapping.items() if col} for row in reader]


def cmd_guests(mem: Memory, args, now: datetime) -> dict:
    p = Plan(mem, now.tzinfo, now.date())
    ev = p.event(args.event)
    if args.file:
        if ev["state"] != "planning":
            raise ToolError(f"{ev['name']} is {ev['state']}.")
        rows = rows_from_file(args.file)
        ents, fs, created, already, seen = [], [], [], [], set()
        for n, row in enumerate(rows, 1):
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            key = p.child_key("guest", ev, name)
            if key in seen:
                raise ToolError(f"Row {n}: {name!r} appears twice in the list; tell them apart (\"Familia Pérez "
                                "(novia)\").")
            seen.add(key)
            current = p.guests.get(key)
            if current and (current["g_state"] or "active") == "active":
                already.append(name)
                continue
            try:
                facts = guest_facts(p, ev, None, row)
            except ToolError as error:
                raise ToolError(f"Row {n} ({name}): {error}") from None
            ents.append({"key": key, "type": "guest", "name": name})
            fs += [(key, pr, v) for pr, v in facts if v is not None]
            created.append(name)
        if ents:
            mem.write(args.by, by_source(args, f"Guest list imported ({len(ents)})"), entities=ents,
                      facts=[{"subject": s, "predicate": pr, "value": v, "valid_from": "now"} for s, pr, v in fs])
            p = Plan(mem, now.tzinfo, now.date())
            ev = p.events[ev["key"]]
        return {"ok": True, "event": ev["name"], "imported": len(created), "already_here": already,
                **{"totals": p.guest_counts(ev)}}
    gs = p.live_guests(ev) if not args.all else sorted(p.of(p.guests, ev), key=lambda g: norm(g["name"]))
    if args.group:
        gs = [g for g in gs if norm(args.group) in norm(g["g_group"] or "")]
    if args.rsvp:
        r = parse_rsvp(args.rsvp)
        gs = [g for g in gs if (g["g_rsvp"] or "pending") == r]
    if args.search:
        words = norm(args.search).split()
        gs = [g for g in gs if all(w in norm(f"{g['name']} {g['g_note'] or ''} {g['g_diet'] or ''}") for w in words)]
    if args.unseated:
        gs = [g for g in gs if not g["g_table"] and p.expected(g)]
    out = {"ok": True, "event": ev["name"], "totals": p.guest_counts(ev), "shown": len(gs)}
    if args.export:
        target = Path(args.export)
        if target.exists() and not args.overwrite:
            raise ToolError(f"{target} exists; pass --overwrite to replace it.")
        if target.suffix.lower() != ".csv":
            raise ToolError("--export writes a .csv file.")
        with target.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["nombre", "grupo", "pases", "confirmacion", "asistentes", "mesa", "dieta", "nota"])
            for g in gs:
                w.writerow([g["name"], g["g_group"] or "", g["g_seats"] or "",
                            {"yes": "sí", "no": "no"}.get(g["g_rsvp"], "pendiente"),
                            g["g_coming"] if g["g_rsvp"] == "yes" else "",
                            p.tables.get(g["g_table"], {}).get("name", "") if g["g_table"] else "",
                            g["g_diet"] or "", g["g_note"] or ""])
        out["exported"] = {"file": str(target), "rows": len(gs)}
    elif not args.counts:
        out["guests"] = [p.guest_view(g) for g in gs]
    return out


def cmd_table(mem: Memory, args, now: datetime) -> dict:
    p = Plan(mem, now.tzinfo, now.date())
    ev = p.event(args.event, planning_only=True)
    key = p.child_key("seating_table", ev, args.name)
    current = p.tables.get(key)
    entity = {"key": key, "type": "seating_table", "name": args.name.strip()}
    facts: list[tuple[str, Any]] = []
    if args.remove:
        if not current:
            raise ToolError(f"There is no table {args.name!r}.")
        seated = [g["name"] for g in p.live_guests(ev) if g["g_table"] == key]
        if seated:
            raise ToolError(f"{args.name} has {len(seated)} invitations seated ({', '.join(seated[:5])}); "
                            "move them first.")
        entity_write(mem, args, f"Table {args.name} removed", entity, [("tb_state", "removed")])
        return {"ok": True, "removed": key}
    if not current:
        if args.seats is None:
            raise ToolError("How many places? --seats.")
        facts += [("of_event", ev["key"]), ("tb_state", "active"),
                  ("tb_order", args.order if args.order is not None else len(p.of(p.tables, ev)) + 1)]
    elif current["tb_state"] == "removed":
        facts.append(("tb_state", "active"))
    if args.seats is not None:
        facts.append(("tb_seats", seats_value(args.seats, "--seats")))
    if current and args.order is not None:
        facts.append(("tb_order", args.order))
    if current and not facts:
        return {"ok": True, "unchanged": True, "table": key}
    entity_write(mem, args, f"Table {args.name}", entity, facts)
    p = Plan(mem, now.tzinfo, now.date())
    use = next(t for t in p.table_use(p.events[ev["key"]]) if t["table"] == key)
    return {"ok": True, "created": not current, **use}


def cmd_seat(mem: Memory, args, now: datetime) -> dict:
    p = Plan(mem, now.tzinfo, now.date())
    ev = p.event(args.event, planning_only=True)
    g = p.find(p.guests, ev, args.guest, "invitation", "guest")
    if (g["g_state"] or "active") != "active":
        raise ToolError(f"{g['name']} was removed.")
    entity = {"key": g["key"], "type": "guest", "name": g["name"]}
    if norm(args.table) == "none":
        entity_write(mem, args, f"{g['name']} unseated", entity, [], ["g_table"])
        return {"ok": True, "guest": g["name"], "table": None}
    t = p.find(p.tables, ev, args.table, "table", "seating_table")
    if (t["tb_state"] or "active") != "active":
        raise ToolError(f"{t['name']} was removed.")
    places = p.expected(g)
    if not places:
        raise ToolError(f"{g['name']} declined; there is no one to seat.")
    use = next(u for u in p.table_use(ev) if u["table"] == t["key"])
    already = g["g_table"] == t["key"]
    free = use["free"] + (places if already else 0)
    if places > free and not args.over:
        raise ToolError(f"{g['name']} needs {places} places and {t['name']} has {max(free, 0)} free of "
                        f"{t['tb_seats']}. Choose another table, or --over if the owner wants to squeeze them in.")
    if not already:
        entity_write(mem, args, f"{g['name']} seated at {t['name']}", entity, [("g_table", t["key"])])
    p = Plan(mem, now.tzinfo, now.date())
    use = next(u for u in p.table_use(p.events[ev["key"]]) if u["table"] == t["key"])
    return {"ok": True, "guest": g["name"], "places": places, "unchanged": already, **use,
            **({"over_capacity": True} if use["free"] < 0 else {})}


def cmd_tables(mem: Memory, args, now: datetime) -> dict:
    p = Plan(mem, now.tzinfo, now.date())
    ev = p.event(args.event)
    use = p.table_use(ev)
    unseated = [{"name": g["name"], "group": g["g_group"], "places": p.expected(g), "rsvp": g["g_rsvp"] or "pending"}
                for g in p.live_guests(ev) if not g["g_table"] and p.expected(g)]
    return {"ok": True, "event": ev["name"], "tables": use, "places_at_tables": sum(t["seats"] or 0 for t in use),
            "places_used": sum(t["used"] for t in use), "unseated": unseated,
            "unseated_places": sum(u["places"] for u in unseated),
            "over_capacity": [t["name"] for t in use if t["free"] < 0],
            "note": "a confirmed invitation takes the places confirmed; a pending one all its seats; a declined none"}


def cmd_program(mem: Memory, args, now: datetime) -> dict:
    p = Plan(mem, now.tzinfo, now.date())
    ev = p.event(args.event)
    if args.at or args.remove:
        if ev["state"] != "planning":
            raise ToolError(f"{ev['name']} is {ev['state']}.")
        if args.remove:
            item = p.find(p.program, ev, args.remove, "program item", "program_item")
            entity_write(mem, args, f"Program item removed", {"key": item["key"], "type": "program_item",
                                                              "name": item["name"]}, [("pg_state", "removed")])
        else:
            m = re.fullmatch(r"(\d{1,2}):(\d{2})", args.at.strip())
            if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
                raise ToolError(f"--at is HH:MM (24 hours), not {args.at!r}")
            hhmm = f"{int(m.group(1)):02d}:{m.group(2)}"
            text = text_field(args.text, "--text")
            if not text:
                raise ToolError("What happens at that time? --text.")
            key = p.child_key("program_item", ev, f"{hhmm.replace(':', '')}-{text}")
            facts = [("of_event", ev["key"]), ("pg_time", hhmm), ("pg_state", "active")]
            if args.vendor:
                facts.append(("pg_vendor", p.find(p.vendors, ev, args.vendor, "vendor", "vendor")["key"]))
            entity_write(mem, args, f"Program {hhmm} {text}", {"key": key, "type": "program_item", "name": text},
                         facts)
        p = Plan(mem, now.tzinfo, now.date())
        ev = p.events[ev["key"]]
    items = sorted((i for i in p.of(p.program, ev) if (i["pg_state"] or "active") == "active"),
                   key=lambda i: program_sort(i["pg_time"]))
    return {"ok": True, "event": ev["name"], "date": ev["date"].isoformat() if ev["date"] else None,
            "program": [{"item": i["key"], "at": i["pg_time"], "what": i["name"],
                         "vendor": p.vendors.get(i["pg_vendor"], {}).get("name") if i["pg_vendor"] else None,
                         **({"after_midnight": True} if program_sort(i["pg_time"])[0] else {})} for i in items],
            "note": "times from 00:00 to 05:59 go after midnight, at the end"}


def cmd_brief(mem: Memory, args, now: datetime) -> dict:
    try:
        p = Plan(mem, now.tzinfo, now.date())
    except ToolError as error:
        if error.code != MEMORY_ERROR:
            raise
        return {"ok": True, "today": now.date().isoformat(), "setup_needed": True,
                "message": "No memory or no eventos-sociales settings: start the memory if there is none, then "
                           "TOOL setup."}
    high_volume = (mem.run("event-types") or {}).get("high_volume", {})
    seed = load_seed()
    seeded = {t["key"] for t in seed["templates"]}
    out: dict[str, Any] = {"ok": True, "today": now.date().isoformat(), "weekday": WEEKDAY_NAMES[now.weekday()],
                           "todo_here": "task_captured" in high_volume}
    if not seeded <= set(p.templates):
        out["setup_needed"] = True
        out["message"] = "eventos-sociales was updated: run TOOL setup (it keeps the owner's data)."
    events = []
    for ev in p.ordered_events(include_closed=False):
        late = [t for t in p.of(p.tasks, ev) if (t["task_state"] or "pending") == "pending"
                and (p.due(t, ev) or date.max) < now.date()]
        week = [t for t in p.of(p.tasks, ev) if (t["task_state"] or "pending") == "pending"
                and now.date() <= (p.due(t, ev) or date.max) <= now.date() + timedelta(days=6)]
        due = [p.vendor_view(v, ev) for v in p.of(p.vendors, ev) if v["v_state"] == "hired"]
        due = [{"name": v["name"], "balance": v["balance"], "pay_off_by": v["pay_off_by"]} for v in due
               if v.get("days_to_pay_off") is not None and v["days_to_pay_off"] <= 14]
        view = event_view(p, ev)
        events.append({k: view[k] for k in ("event", "name", "date", "weekday", "days_left")} |
                      {"late_tasks": len(late), "tasks_this_week": len(week), "payments_due_14_days": due,
                       "rsvp_pending_invitations": p.guest_counts(ev)["pending_invitations"],
                       **({"already_happened": True} if ev["date"] and ev["date"] < now.date() else {})})
    out["events"] = events
    if not events:
        out["empty"] = True
    return out


# -- CLI ------------------------------------------------------------------------------------
def main() -> None:
    p = argparse.ArgumentParser(prog="eventos.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"eventos.py {__version__}")
    p.add_argument("--mem", help="Path to project-memory's memory.py")
    p.add_argument("--db", help="Path to the memory (default: the current project's)")
    p.add_argument("--tz", default=os.environ.get("HOWWARE_TZ") or local_offset(), help="UTC offset, e.g. --tz=-06:00")
    p.add_argument("--now", default=os.environ.get("EVENTOS_NOW"), help=argparse.SUPPRESS)  # fixed clock for tests
    sub = p.add_subparsers(dest="command", required=True)

    def cmd(name: str, by: bool = True, source: bool = True, event: bool = True):
        s = sub.add_parser(name)
        if by:
            s.add_argument("--by", required=True, help="person:<id> of the owner")
        if source:
            s.add_argument("--source", help="The owner's literal words")
        if event:
            s.add_argument("--event", help="event key or name (optional when only one is in planning)")
        return s

    cmd("setup", source=False, event=False)
    cmd("now", by=False, source=False, event=False)
    cmd("brief", by=False, source=False, event=False)
    s = cmd("templates", by=False, source=False, event=False)
    s.add_argument("--all", action="store_true", help="include retired templates")
    s.add_argument("--detail", action="store_true", help="include each template's tasks")
    s = cmd("template", event=False)
    s.add_argument("--key", required=True, help="template:<slug> or a short name")
    s.add_argument("--from-event", help="save this event's tasks and budget shares as the template")
    s.add_argument("--name")
    s.add_argument("--state", help="active | retired")
    s = cmd("event", event=False)
    s.add_argument("--key", required=True, help="event:<slug> or a short name, e.g. boda-ana-luis")
    s.add_argument("--name")
    s.add_argument("--kind", help="boda, xv, bautizo, aniversario...")
    s.add_argument("--date", help="YYYY-MM-DD, the day of the event")
    s.add_argument("--template", help="template key or name (see templates), or none")
    s.add_argument("--hosts", help="who it is for, in the owner's words")
    s.add_argument("--capacity", help="places the venue allows, or none")
    s.add_argument("--budget", help="total budget in pesos, or none")
    s.add_argument("--state", help=" | ".join(EVENT_STATES))
    s = cmd("events", by=False, source=False, event=False)
    s.add_argument("--all", action="store_true", help="include done and cancelled events")
    s = cmd("agenda", by=False, source=False)
    s.add_argument("--weeks", type=int, default=4, help="how many weeks ahead to list (default 4)")
    s = cmd("tasks", by=False, source=False)
    s.add_argument("--state", default="pending", help="pending | done | dropped | all")
    s.add_argument("--area")
    s.add_argument("--search")
    s = cmd("task")
    s.add_argument("--key", help="the task's key or title, to change it")
    s.add_argument("--title", help="a new task's title, or a new title")
    s.add_argument("--offset", help="-3m, -2w, -5d, 0d, +1w: relative to the event day")
    s.add_argument("--due", help="YYYY-MM-DD: a fixed day")
    s.add_argument("--area", help="budget area, or general")
    s.add_argument("--note")
    s.add_argument("--done", action="store_true")
    s.add_argument("--date", help="YYYY-MM-DD it was done (today by default)")
    s.add_argument("--drop", action="store_true", help="take it out of the plan (it stays in the file)")
    s.add_argument("--reopen", action="store_true")
    s.add_argument("--reason", help="why, in the owner's words")
    s = cmd("budget", by=False)
    s.add_argument("--by", help="person:<id> of the owner (needed to change it)")
    s.add_argument("--total", help="the total budget, in pesos")
    s.add_argument("--suggest", action="store_true", help="show the template's suggested split of the total")
    s.add_argument("--apply-suggested", action="store_true", help="plan every area with its suggested amount")
    s.add_argument("--set", action="append", help="area=amount in pesos, repeatable; a new name creates an area")
    s = cmd("vendor")
    s.add_argument("--name", required=True)
    s.add_argument("--key", help="the vendor's key, to rename it")
    s.add_argument("--area", help="its budget area")
    s.add_argument("--total", help="contract total in pesos, or none")
    s.add_argument("--state", help=" | ".join(VENDOR_STATES))
    s.add_argument("--pay-off-by", help="YYYY-MM-DD the balance is due, or none")
    s.add_argument("--contact")
    s.add_argument("--note")
    s = cmd("vendors", by=False, source=False)
    s.add_argument("--area")
    s.add_argument("--all", action="store_true", help="include discarded vendors")
    s = cmd("pay")
    s.add_argument("--amount", required=True, help="pesos")
    s.add_argument("--vendor")
    s.add_argument("--area", help="for a payment without a vendor")
    s.add_argument("--payer", required=True, help="who paid, in the owner's words")
    s.add_argument("--date", help="YYYY-MM-DD (today by default)")
    s.add_argument("--note", help="deposit, settlement...")
    s.add_argument("--nonce", help="tells apart two identical payments")
    s = cmd("unpay", event=False)
    s.add_argument("--key", required=True)
    s.add_argument("--reason", required=True)
    s = cmd("payments", by=False, source=False)
    s.add_argument("--payer")
    s = cmd("sponsor")
    s.add_argument("--role", required=True, help="lazo, arras, pastel, velación...")
    s.add_argument("--names", help="who, in the owner's words")
    s.add_argument("--state", help=" | ".join(SPONSOR_STATES))
    s.add_argument("--covers", help="what they give or pay for")
    s.add_argument("--amount", help="what they cover, in pesos, or none")
    s.add_argument("--area", help="the budget area it covers, or none")
    s.add_argument("--reason")
    s = cmd("sponsors", by=False, source=False)
    s.add_argument("--all", action="store_true", help="include removed sponsors")
    s = cmd("guest")
    s.add_argument("--name", help="the invitation as the owner names it (a person, a couple, a family)")
    s.add_argument("--key", help="an existing invitation's key or name")
    s.add_argument("--rename", help="a new name for the invitation given with --key")
    s.add_argument("--group")
    s.add_argument("--seats", help="places in the invitation (pases)")
    s.add_argument("--rsvp", help="pending | yes | no")
    s.add_argument("--coming", help="places confirmed (yes); all the seats by default")
    s.add_argument("--diet")
    s.add_argument("--note")
    s.add_argument("--remove", action="store_true")
    s.add_argument("--reason")
    s = cmd("guests", by=False)
    s.add_argument("--by", help="person:<id> of the owner (needed with --file)")
    s.add_argument("--file", help="import a JSON list or a CSV (nombre, grupo, pases, dieta, nota...); - for stdin")
    s.add_argument("--group")
    s.add_argument("--rsvp")
    s.add_argument("--search")
    s.add_argument("--unseated", action="store_true", help="only invitations without a table")
    s.add_argument("--counts", action="store_true", help="only the totals")
    s.add_argument("--all", action="store_true", help="include removed invitations")
    s.add_argument("--export", help="write the list shown to this .csv file")
    s.add_argument("--overwrite", action="store_true")
    s = cmd("table")
    s.add_argument("--name", required=True, help='"Mesa 5", "Mesa de honor"...')
    s.add_argument("--seats")
    s.add_argument("--order", type=int)
    s.add_argument("--remove", action="store_true")
    s = cmd("seat")
    s.add_argument("--guest", required=True)
    s.add_argument("--table", required=True, help="a table, or none to unseat")
    s.add_argument("--over", action="store_true", help="seat even if the table is full")
    s = cmd("tables", by=False, source=False)
    s = cmd("program", by=False)
    s.add_argument("--by", help="person:<id> of the owner (needed to change it)")
    s.add_argument("--at", help="HH:MM")
    s.add_argument("--text", help="what happens")
    s.add_argument("--vendor", help="the vendor in charge")
    s.add_argument("--remove", help="an item's key or text")
    args = p.parse_args()

    commands = {"setup": cmd_setup, "brief": cmd_brief, "templates": cmd_templates, "template": cmd_template,
                "event": cmd_event, "events": cmd_events, "agenda": cmd_agenda, "tasks": cmd_tasks, "task": cmd_task,
                "budget": cmd_budget, "vendor": cmd_vendor, "vendors": cmd_vendors, "pay": cmd_pay,
                "unpay": cmd_unpay, "payments": cmd_payments, "sponsor": cmd_sponsor, "sponsors": cmd_sponsors,
                "guest": cmd_guest, "guests": cmd_guests, "table": cmd_table, "seat": cmd_seat, "tables": cmd_tables,
                "program": cmd_program}
    try:
        tz = parse_tz(args.tz)
        if args.now:
            try:
                now = datetime.fromisoformat(args.now).replace(tzinfo=tz)
            except ValueError:
                raise ToolError(f"--now must be YYYY-MM-DDTHH:MM, not {args.now!r}") from None
        else:
            now = datetime.now(tz).replace(microsecond=0)
        writes = {"budget": ("total", "set", "apply_suggested"), "guests": ("file",), "program": ("at", "remove")}
        if args.command in writes and any(getattr(args, a, None) for a in writes[args.command]) and not args.by:
            raise ToolError(f"{args.command} needs --by to change anything.")
        if args.command == "now":
            result, code = cmd_now(None, args, now), OK
        else:
            mem = Memory(find_helper(args.mem), args.db)
            mem.check_version()
            result, code = commands[args.command](mem, args, now), OK
    except ToolError as error:
        result, code = {"ok": False, "error": {"code": error.code, "message": str(error)}}, error.code
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(code)


if __name__ == "__main__":
    main()
