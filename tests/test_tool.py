"""Tests of the tool against a real, temporary memory. Synthetic data only.

The memory helper is found in HOWWARE_MEMORY_HELPER, in the installed project-memory skill or in a sibling checkout.
The clock is fixed with EVENTOS_NOW so dates and countdowns are reproducible.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "skill" / "eventos-sociales" / "scripts" / "eventos.py"
BY = "person:test"
NOW = "2026-10-12T10:00"


def find_helper() -> Path | None:
    for c in (os.environ.get("HOWWARE_MEMORY_HELPER"), Path.home() / ".claude/skills/project-memory/scripts/memory.py",
              ROOT.parent / "long-term-memory-for-AI" / "db" / "memory.py"):
        if c and Path(c).is_file():
            return Path(c)
    return None


HELPER = find_helper()


@unittest.skipUnless(HELPER, "project-memory is not installed")
class ToolTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.db = str(self.dir / "memory.sqlite")
        subprocess.run([sys.executable, str(HELPER), "--db", self.db, "init", "--owner-name", "Test",
                        "--owner-key", BY], check=True, capture_output=True)
        self.assertTrue(self.tool("setup", "--by", BY)["ok"])

    def tearDown(self):
        self.tmp.cleanup()

    def tool(self, *args: str, now: str = NOW, code: int = 0, stdin: str | None = None) -> dict:
        env = {**os.environ, "EVENTOS_NOW": now, "PYTHONIOENCODING": "utf-8"}
        proc = subprocess.run([sys.executable, str(TOOL), "--mem", str(HELPER), "--db", self.db, "--tz=-06:00", *args],
                              capture_output=True, text=True, encoding="utf-8", env=env, input=stdin)
        self.assertEqual(proc.returncode, code, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)

    def wedding(self, date: str = "2027-03-20", key: str = "boda-ana-luis") -> dict:
        return self.tool("event", "--key", key, "--name", f"Boda {key}", "--date", date, "--template", "boda",
                         "--capacity", "150", "--by", BY)

    # -- events and the template ---------------------------------------------------------------
    def test_setup_is_idempotent(self):
        again = self.tool("setup", "--by", BY)
        self.assertEqual(again["templates_installed"], [])
        self.assertEqual(again["templates_updated"], [])
        self.assertEqual(self.tool("templates")["templates"][0]["template"], "template:boda")

    def test_event_applies_the_template_and_flags_late_start(self):
        ev = self.wedding()
        seed = json.loads((TOOL.parent / "seed.json").read_text(encoding="utf-8"))["templates"][0]
        self.assertEqual(ev["tasks_created"], len(seed["tasks"]))
        self.assertEqual(ev["budget_areas_created"], len(seed["areas"]))
        self.assertEqual(ev["days_left"], 159)
        # five months to go: everything due before today was late from the start
        late = ev["late_from_start"]["tasks"]
        self.assertTrue(all(t["due"] < "2026-10-12" for t in late))
        self.assertIn("event_task:boda-ana-luis--lugar", [t["task"] for t in late])
        agenda = self.tool("agenda")["events"][0]
        self.assertEqual(len(agenda["late"]["from_the_start"]), len(late))
        self.assertEqual(agenda["late"]["slipped"], [])
        # a month later, a task that came due meanwhile has slipped, not "from the start"
        later = self.tool("agenda", now="2026-11-25T10:00")["events"][0]
        self.assertIn("event_task:boda-ana-luis--tramites-civil", [t["task"] for t in later["late"]["slipped"]])

    def test_offsets_are_calendar_exact(self):
        self.wedding(date="2027-03-31")
        tasks = {t["task"].split("--")[1]: t for t in self.tool("tasks", "--state", "all")["tasks"]}
        self.assertEqual(tasks["pruebas-finales"]["due"], "2027-02-28")     # -1m from Mar 31: end of February
        self.assertEqual(tasks["numero-final"]["due"], "2027-03-17")        # -2w
        self.assertEqual(tasks["rentados"]["due"], "2027-04-07")            # +1w

    def test_date_change_moves_offsets_not_fixed_dates(self):
        self.wedding()
        self.tool("task", "--title", "Llevar el vestido a la tintorería", "--due", "2027-03-25", "--by", BY)
        self.tool("task", "--title", "Contratar mariachi", "--offset=-2m", "--area", "musica", "--by", BY)
        moved = self.tool("event", "--key", "boda-ana-luis", "--date", "2027-03-13", "--by", BY)
        self.assertEqual(moved["date_changed"]["from"], "2027-03-20")
        self.assertEqual([t["title"] for t in moved["date_changed"]["fixed_tasks_after_the_event"]],
                         ["Llevar el vestido a la tintorería"])
        tasks = {t["title"]: t for t in self.tool("tasks")["tasks"]}
        self.assertEqual(tasks["Contratar mariachi"]["due"], "2027-01-13")
        self.assertEqual(tasks["Contratar mariachi"]["area"], "Música")
        self.assertEqual(tasks["Llevar el vestido a la tintorería"]["due"], "2027-03-25")

    def test_task_done_drop_reopen(self):
        self.wedding()
        done = self.tool("task", "--key", "lugar", "--done", "--date", "2026-10-01", "--by", BY)
        self.assertEqual((done["state"], done["done_on"]), ("done", "2026-10-01"))
        self.tool("task", "--key", "luna-de-miel", "--drop", "--by", BY, code=2)        # needs a reason
        self.tool("task", "--key", "luna-de-miel", "--drop", "--reason", "nos la regalan", "--by", BY)
        self.assertEqual(self.tool("tasks", "--state", "dropped")["shown"], 1)
        self.tool("task", "--key", "luna-de-miel", "--reopen", "--by", BY)
        self.assertEqual(self.tool("tasks", "--state", "dropped")["shown"], 0)
        self.tool("task", "--key", "lugar", "--done", "--date", "2026-12-01", "--by", BY, code=2)  # future
        self.tool("task", "--title", "Sin fecha", "--by", BY, code=2)
        self.tool("task", "--title", "x", "--offset", "dos meses", "--by", BY, code=2)

    def test_several_events_need_the_event(self):
        self.wedding()
        self.wedding(date="2027-06-05", key="boda-sofi-beto")
        result = self.tool("agenda", code=2)
        self.assertIn("--event", result["error"]["message"])
        self.assertEqual(len(self.tool("agenda", "--event", "all")["events"]), 2)
        self.assertEqual(self.tool("tasks", "--event", "boda-sofi-beto")["event"], "Boda boda-sofi-beto")

    def test_event_refusals(self):
        self.tool("event", "--key", "x", "--name", "X", "--date", "2026-01-01", "--template", "boda", "--by", BY, code=2)
        self.tool("event", "--key", "x", "--name", "X", "--date", "2027-01-01", "--template", "nope", "--by", BY,
                  code=2)
        bare = self.tool("event", "--key", "xv-mia", "--name", "XV de Mía", "--date", "2027-08-01", "--template",
                         "none", "--kind", "xv", "--by", BY)
        self.assertEqual((bare["tasks"]["pending"], bare["template"]), (0, "none"))

    # -- money ----------------------------------------------------------------------------------
    def test_suggested_split_adds_up_exactly(self):
        self.wedding()
        out = self.tool("budget", "--total", "123,457.89", "--by", BY)
        self.assertEqual(out["total_budget"], "$123,457.89")
        applied = self.tool("budget", "--apply-suggested", "--by", BY)
        self.assertEqual(applied["planned"], "$123,457.89")
        self.assertEqual(applied["unplanned"], "$0.00")
        changed = self.tool("budget", "--set", "banquete=50000", "--set", "Luna de miel=30000", "--by", BY)
        areas = {a["area"]: a for a in changed["areas"]}
        self.assertEqual(areas["banquete"]["planned"], "$50,000.00")
        self.assertEqual(areas["luna-de-miel"]["label"], "Luna de miel")
        self.tool("budget", "--set", "banquete=mucho", "--by", BY, code=2)
        self.tool("budget", "--total", "1000", code=2)                                   # changing needs --by

    def test_vendors_payments_and_sponsors(self):
        self.wedding()
        self.tool("budget", "--set", "pastel=7000", "--set", "foto-video=35000", "--by", BY)
        self.tool("vendor", "--name", "Foto Luz", "--area", "foto-video", "--state", "hired", "--by", BY, code=2)
        v = self.tool("vendor", "--name", "Foto Luz", "--area", "foto-video", "--total", "32000", "--state", "hired",
                      "--pay-off-by", "2027-03-01", "--by", BY)
        self.assertEqual(v["balance"], "$32,000.00")
        paid = self.tool("pay", "--vendor", "foto luz", "--amount", "$8,000", "--payer", "Ana y Luis", "--note",
                         "anticipo", "--date", "2026-10-10", "--by", BY)
        self.assertEqual(paid["vendor"]["balance"], "$24,000.00")
        again = self.tool("pay", "--vendor", "foto luz", "--amount", "8000", "--payer", "ana y luis", "--date",
                          "2026-10-10", "--by", BY)
        self.assertTrue(again["unchanged"])
        second = self.tool("pay", "--vendor", "foto luz", "--amount", "8000", "--payer", "Ana y Luis", "--date",
                           "2026-10-10", "--nonce", "2", "--by", BY)
        self.assertEqual(second["vendor"]["balance"], "$16,000.00")
        self.tool("unpay", "--key", second["payment"], "--reason", "duplicado", "--by", BY)
        self.tool("vendor", "--name", "Pastelería Rosa", "--area", "pastel", "--total", "9000", "--state", "hired",
                  "--by", BY)
        self.tool("sponsor", "--role", "pastel", "--names", "Tíos Marta y Jorge", "--amount", "9000", "--by", BY,
                  code=2)                                                       # an amount needs its area
        self.tool("sponsor", "--role", "pastel", "--names", "Tíos Marta y Jorge", "--state", "accepted", "--covers",
                  "El pastel", "--amount", "9000", "--area", "pastel", "--by", BY)
        self.tool("pay", "--area", "decoracion", "--amount", "1500.50", "--payer", "Mamá de Ana", "--by", BY)
        b = self.tool("budget")
        areas = {a["area"]: a for a in b["areas"]}
        self.assertEqual(areas["pastel"]["hosts_share"], "$0.00")
        self.assertEqual(areas["pastel"]["left"], "$7,000.00")
        self.assertEqual(areas["foto-video"]["owed"], "$24,000.00")
        self.assertEqual(areas["decoracion"]["paid_without_vendor"], "$1,500.50")
        self.assertEqual(b["hosts_share"], "$33,500.50")
        self.assertEqual(b["paid"], "$9,500.50")
        pays = self.tool("payments")
        self.assertEqual(pays["by_payer"], {"Ana y Luis": "$8,000.00", "Mamá de Ana": "$1,500.50"})
        vendors = self.tool("vendors")
        self.assertEqual((vendors["hired_total"], vendors["balance_total"]), ("$41,000.00", "$33,000.00"))
        due = self.tool("brief", now="2027-02-20T09:00")["events"][0]["payments_due_14_days"]
        self.assertEqual(due, [{"name": "Foto Luz", "balance": "$24,000.00", "pay_off_by": "2027-03-01"}])
        self.tool("pay", "--vendor", "Foto Luz", "--amount", "100", "--payer", "x", "--date", "2026-12-01",
                  "--by", BY, code=2)                                           # future payment

    # -- guests, tables and program --------------------------------------------------------------
    def test_guest_import_rsvp_and_counts(self):
        self.wedding()
        (self.dir / "inv.csv").write_text("Nombre;Grupo;Pases;Dieta\nFamilia Pérez;Novia;4;1 vegetariano\n"
                                          "Tíos Ramírez;Novio;2;\nSofía;Amigos;1;\n", encoding="utf-8")
        imp = self.tool("guests", "--file", str(self.dir / "inv.csv"), "--by", BY)
        self.assertEqual((imp["imported"], imp["totals"]["seats_invited"]), (3, 7))
        again = self.tool("guests", "--file", str(self.dir / "inv.csv"), "--by", BY)
        self.assertEqual((again["imported"], len(again["already_here"])), (0, 3))
        js = json.dumps([{"name": "Primo Beto", "group": "Novio", "seats": 2, "rsvp": "sí"}])
        self.tool("guests", "--file", "-", "--by", BY, stdin=js)
        self.tool("guest", "--name", "Familia Pérez", "--rsvp", "sí", "--coming", "3", "--by", BY)
        self.tool("guest", "--name", "Tíos Ramírez", "--rsvp", "no", "--by", BY)
        self.tool("guest", "--name", "Familia Pérez", "--coming", "5", "--by", BY, code=2)
        self.tool("guest", "--name", "Sofía", "--coming", "1", "--by", BY, code=2)     # not confirmed
        c = self.tool("guests", "--counts")["totals"]
        self.assertEqual((c["invitations"], c["seats_invited"], c["confirmed"], c["declined"], c["pending_seats"]),
                         (4, 9, 5, 3, 1))
        self.assertEqual(c["expected_at_most"], 6)
        self.assertEqual(c["by_group"]["Novia"], {"invitations": 1, "seats": 4, "confirmed": 3, "pending": 0})
        self.tool("guest", "--name", "Sofía", "--remove", "--by", BY, code=2)           # needs a reason
        self.tool("guest", "--name", "Sofía", "--remove", "--reason", "ya no", "--by", BY)
        self.assertEqual(self.tool("guests", "--counts")["totals"]["invitations"], 3)
        out = self.dir / "lista.csv"
        self.tool("guests", "--export", str(out), "--rsvp", "yes")
        with out.open(encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))
        self.assertEqual(rows[0][:5], ["nombre", "grupo", "pases", "confirmacion", "asistentes"])
        self.assertEqual(sorted(r[0] for r in rows[1:]), ["Familia Pérez", "Primo Beto"])
        self.tool("guests", "--export", str(out), code=2)                                # no silent overwrite

    def test_tables_check_capacity(self):
        self.wedding()
        self.tool("guest", "--name", "Familia Pérez", "--seats", "4", "--rsvp", "yes", "--coming", "3", "--by", BY)
        self.tool("guest", "--name", "Primo Beto", "--seats", "2", "--by", BY)
        self.tool("guest", "--name", "Tíos Ramírez", "--seats", "2", "--rsvp", "no", "--by", BY)
        self.tool("table", "--name", "Mesa 1", "--seats", "4", "--by", BY)
        first = self.tool("seat", "--guest", "Pérez", "--table", "Mesa 1", "--by", BY)
        self.assertEqual((first["used"], first["free"]), (3, 1))
        refused = self.tool("seat", "--guest", "Beto", "--table", "Mesa 1", "--by", BY, code=2)
        self.assertIn("1 free of 4", refused["error"]["message"])
        self.tool("seat", "--guest", "Ramírez", "--table", "Mesa 1", "--by", BY, code=2)
        squeezed = self.tool("seat", "--guest", "Beto", "--table", "Mesa 1", "--over", "--by", BY)
        self.assertTrue(squeezed["over_capacity"])
        self.tool("seat", "--guest", "Beto", "--table", "none", "--by", BY)
        plan = self.tool("tables")
        self.assertEqual(plan["unseated"], [{"name": "Primo Beto", "group": None, "places": 2, "rsvp": "pending"}])
        self.assertEqual(plan["over_capacity"], [])
        self.tool("table", "--name", "Mesa 1", "--remove", "--by", BY, code=2)           # still has guests

    def test_program_sorts_after_midnight(self):
        self.wedding()
        for at, text in (("20:00", "Vals"), ("1:30", "Tornafiesta"), ("18:00", "Ceremonia")):
            self.tool("program", "--at", at, "--text", text, "--by", BY)
        prog = self.tool("program")["program"]
        self.assertEqual([p["what"] for p in prog], ["Ceremonia", "Vals", "Tornafiesta"])
        self.tool("program", "--remove", "Vals", "--by", BY)
        self.assertEqual(len(self.tool("program")["program"]), 2)
        self.tool("program", "--at", "25:00", "--text", "x", "--by", BY, code=2)

    # -- templates and brief -----------------------------------------------------------------------
    def test_save_an_event_as_a_template(self):
        self.wedding()
        self.tool("budget", "--total", "200000", "--set", "banquete=100000", "--by", BY)
        self.tool("task", "--key", "luna-de-miel", "--drop", "--reason", "no", "--by", BY)
        self.tool("task", "--title", "Contratar mariachi", "--due", "2027-01-20", "--by", BY)
        self.tool("template", "--key", "boda", "--from-event", "boda-ana-luis", "--by", BY, code=2)  # seed's
        saved = self.tool("template", "--key", "mi-boda", "--from-event", "boda-ana-luis", "--name", "Mi boda",
                          "--by", BY)
        seed_tasks = len(json.loads((TOOL.parent / "seed.json").read_text(encoding="utf-8"))["templates"][0]["tasks"])
        self.assertEqual(saved["tasks"], seed_tasks)                     # one dropped, one added
        self.assertEqual(saved["areas"][0], {"key": "banquete", "label": "Banquete y bebidas", "percent": 50})
        mine = self.tool("event", "--key", "boda-2", "--name", "Boda 2", "--date", "2027-05-22", "--template",
                         "mi-boda", "--by", BY)
        tasks = {t["title"]: t for t in self.tool("tasks", "--event", "boda-2")["tasks"]}
        self.assertEqual(tasks["Contratar mariachi"]["when"], "-2m")
        self.assertNotIn("Planear y reservar la luna de miel", tasks)
        self.assertEqual(mine["template"], "template:mi-boda")
        self.assertEqual(self.tool("setup", "--by", BY)["templates_updated"], [])     # owner's is never touched

    def test_brief(self):
        self.assertTrue(self.tool("brief")["empty"])
        self.wedding()
        brief = self.tool("brief")
        self.assertNotIn("setup_needed", brief)
        ev = brief["events"][0]
        self.assertEqual((ev["days_left"], ev["rsvp_pending_invitations"]), (159, 0))
        self.assertGreater(ev["late_tasks"], 0)
        after = self.tool("brief", now="2027-03-22T10:00")["events"][0]
        self.assertTrue(after["already_happened"])
        self.tool("event", "--key", "boda-ana-luis", "--state", "done", "--by", BY)
        self.assertTrue(self.tool("brief")["empty"])
        self.tool("task", "--title", "x", "--due", "2027-01-01", "--event", "boda-ana-luis", "--by", BY, code=2)


class NoSetupTest(unittest.TestCase):
    @unittest.skipUnless(HELPER, "project-memory is not installed")
    def test_brief_without_setup(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "memory.sqlite")
            subprocess.run([sys.executable, str(HELPER), "--db", db, "init", "--owner-name", "T", "--owner-key", BY],
                           check=True, capture_output=True)
            proc = subprocess.run([sys.executable, str(TOOL), "--mem", str(HELPER), "--db", db, "brief"],
                                  capture_output=True, text=True, encoding="utf-8")
            self.assertTrue(json.loads(proc.stdout)["setup_needed"])


class ContractTest(unittest.TestCase):
    def test_version(self):
        out = subprocess.run([sys.executable, str(TOOL), "--version"], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0)
        self.assertIn("eventos.py ", out.stdout)

    def test_now_needs_no_memory(self):
        env = {**os.environ, "EVENTOS_NOW": NOW}
        out = subprocess.run([sys.executable, str(TOOL), "--tz=-06:00", "now"], capture_output=True, text=True,
                             env=env)
        self.assertEqual(json.loads(out.stdout)["weekday"], "monday")


if __name__ == "__main__":
    unittest.main()
