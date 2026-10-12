# Changelog

## 0.1.1

- **Fixed:** when a command stopped early (for example, `brief` before `setup`), the parallel reads of the
  memory could be left running and keep the memory file open; on Windows the file then couldn't be moved or
  deleted. The tool now waits for all of them.

## 0.1.0 — first version

- Protocol for planning a wedding (or XV años, a baptism…) without an app, for the couple or a wedding planner with
  several events: start an event, what's next, adjust the plan, budget, vendors and payments, sponsors (padrinos),
  guests and RSVPs, tables, the day's program, after the event, saving a template.
- **Wedding template** with 37 steps from 12 months before to the thank-you notes, each due relative to the date
  (`-12m`, `-2w`, `+1w`), and 12 budget areas with suggested shares. The plan is the hosts' to change; a new event
  date moves every relative step.
- Starting late separates what was due before planning began from what slipped since.
- Budget split adding up to the cent; per area: planned, hired, covered by sponsors, hosts' share, paid, owed, left.
- Payments idempotent (vendor, day, amount, payer), with who paid; voiding keeps them in the file.
- Invitations with seats, RSVP, places coming and diet; import from CSV or JSON, export to CSV; counts by group and
  against the venue's capacity.
- Tables with capacity checked; the day's program in order past midnight.
- An event can be saved as the owner's own template; the howware's templates update with it and never overwrite
  the owner's.
