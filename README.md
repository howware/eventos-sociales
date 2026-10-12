<h1 align="center">eventos-sociales · social events planner, without an app</h1>

<p align="center">
  <b>Planning a wedding, XV años or a baptism? Tell your AI agent the date. A countdown template says what to do
  and when; you adjust it. Vendors, payments, budget, sponsors, guests, tables and the day's program, kept exact.</b>
</p>

<p align="center">
  <a href="https://github.com/howware/eventos-sociales/actions/workflows/ci.yml"><img src="https://github.com/howware/eventos-sociales/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/version-0.1.1-blue" alt="Version 0.1.1">
  <a href="https://howware.org"><img src="https://img.shields.io/badge/howware-0.2-5a45d6" alt="howware 0.2"></a>
  <img src="https://img.shields.io/badge/python-3.9%2B-blue" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/license-Apache%202.0-green" alt="Apache 2.0">
</p>

<p align="center"><a href="README.es.md">Español</a> · <a href="docs/building.md">How it was built</a></p>

> **A [howware](https://howware.org):** your know-how, put to work with AI. Here the know-how is how a wedding is
> planned in Mexico (what is booked first, what is paid when, who the *padrinos* are), plus **your own decisions**:
> what stays in the plan, how much goes where, who sits with whom. No app: you say it, a small tool keeps dates and
> money exact, and a memory you own keeps everything. For couples planning their own event and for wedding
> planners with several.

```text
› We're getting married on March 20 next year. About 150 guests, budget of 350 thousand.
✓ Ana & Luis's wedding: Saturday March 20, 2027, 159 days to go. The wedding template is in place: 37 steps.
  Starting five months out, 17 steps were due already. Which of these do you have? Then I suggest an order:
  venue and church first (they set the date and capacity), then banquet and photography.

› We already have the venue and the church. What's next?
✓ Late: banquet, photography and video, music, the dress, the sponsors. Next, by Tue Oct 20: prenuptial
  talks, the suit, the rings, the invitations. Start with the banquet: it's the biggest part of the budget.

› We hired Foto Luz for 32 thousand, we paid 8 as a deposit. Balance by March 1st.
✓ Foto Luz, hired: $32,000.00 · paid $8,000.00 (Ana & Luis) · balance $24,000.00 by Mon Mar 1.
  Photography and video: planned $35,000.00, $3,000.00 left.

› The Pérez family confirmed, 3 of 4. How many are coming?
✓ Pérez family: 3 confirmed. In total 112 confirmed, 31 pending (up to 143), 12 declined. Capacity 150.
```

## What it does

| You say | It does |
|---|---|
| "We're getting married on…" | Creates the **event** and applies the **template**: 37 steps from 12 months before to the thank-you notes, each due relative to the date. If you start late, it separates what was due before you started from what slipped, and the agent proposes an order |
| "What's next?" · "What's missing?" | The **agenda**: late, this week, the next weeks, and the rest only as counts. One step at a time |
| "Add hiring a mariachi two months before" · "We don't need a honeymoon" | **Your plan**: add, move, finish or drop steps. If the date changes, everything relative moves with it |
| "Our budget is 350 thousand" | The template's **suggested split** by area (banquet, venue, photography…), adding up to the cent; you accept it or set your own |
| "We hired the photographer…" · "We paid a deposit" | **Vendors** with contract, balance and pay-off date; **payments** with who paid (the couple, the parents, a sponsor) |
| "My aunt and uncle are the cake sponsors" | **Padrinos**: role, state and what they cover; what they pay lowers your share of the budget |
| "Here is our guest list" · "The Ramírez aren't coming" | **Invitations** with seats (pases), RSVP, diet; import from a CSV or JSON, export a CSV for the venue |
| "Seat the Pérez family at table 1" | **Tables** with capacity checked, and who is still unseated |
| "Let's do the minute-by-minute" | The **day's program**, in order, past midnight too |
| (planners) "Save this wedding as my template" | Your own **template** for the next events |

## How it works

| Part | Here |
|---|---|
| Protocol | [`skill/eventos-sociales/SKILL.md`](skill/eventos-sociales/SKILL.md): the method and the agent's rules, in plain words |
| Tool | [`eventos.py`](skill/eventos-sociales/scripts/eventos.py): only what must be exact: due dates from the countdown, the agenda, the budget split and balances in cents, idempotent payments, seat counts and table capacity, the program's order, CSV import and export |
| Template | [`seed.json`](skill/eventos-sociales/scripts/seed.json): the wedding template (tasks with their offsets, budget areas with suggested shares). Your changes live in your memory |
| Memory | The [Long-Term Memory for AI](https://github.com/howware/long-term-memory-for-AI) adapter: your events, in a local file, with history |

## Install

```bash
git clone https://github.com/howware/long-term-memory-for-AI
python long-term-memory-for-AI/tools/install_skill.py --target ~/.claude/skills/project-memory
git clone https://github.com/howware/eventos-sociales
python eventos-sociales/tools/install_skill.py                                             # Claude Code
python eventos-sociales/tools/install_skill.py --target ~/.codex/skills/eventos-sociales    # Codex
```

Create a folder for your event (or for all your events, if you are a planner), open Claude Code there (add the
persistent-memory instruction of
[Long-Term Memory for AI](https://github.com/howware/long-term-memory-for-AI#set-up-a-project) to its `CLAUDE.md`)
and say *"We're getting married on…"*.

## Privacy and limits

| Designed to stay on your computer | What the AI agent sees |
|---|---|
| The memory file with your events, plan, budget, vendors, payments, sponsors, invitations, tables and program. A guest list you import is read by the tool, which keeps only name, group, seats, RSVP, diet and note | The plan and its dates; amounts and who paid; vendors; the invitations as you name them, when it queries them; what you type |

**What it cannot do or guarantee:**
- What the agent sees leaves your computer for your AI provider, under its terms. **Your guests are other people**
  who did not choose to share their names or diets: you can use nicknames or initials ("Familia P.", "Tía Lupe").
  The protocol tells the agent not to store their phones, addresses or anything beyond what planning needs.
- The memory file is not encrypted.
- **Removing hides, it doesn't erase:** a dropped task, a removed invitation or a voided payment stays in the file.
- **No notifications.** What is due shows up when you open a conversation.
- The template and the suggested budget are **general references**, not legal or financial advice. Civil and
  church requirements change by place: confirm them there.
- The memory lives on one computer: if two people plan together, it isn't shared automatically.
- The seating plan is a list per table; a drawn plan of the room doesn't fit in a conversation.

## Development

```bash
python -m unittest discover -s tests -v
git ls-files -z | xargs -0 python tools/check_private_data.py
```

Tests use synthetic data only. See [AGENTS.md](AGENTS.md).

## License

[Apache 2.0](LICENSE).
