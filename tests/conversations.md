# Conversation scenarios

Checked by hand before each release (howware spec §10). Each scenario: what the owner says, and what the agent
must and must not do. Synthetic data only.

| # | The owner says | The agent must | The agent must not |
|---|---|---|---|
| 1 | "Nos vamos a casar y no sabemos por dónde empezar." (no memory) | Start the memory, `TOOL setup`; ask in one message kind, date (an estimate is fine), guests or capacity, budget, for whom; `TOOL event` with the template | Dump the 37 steps; invent the date |
| 2 | (the event starts five months before the date; `late_from_start` has 17) | Ask which are already done and mark them; propose an order with reasons; then this week | Call them failures; reorder on its own |
| 3 | "¿Qué me toca?" | `TOOL agenda`; late, this week, next weeks briefly, later as counts; one suggestion to start | Compute dates itself; list everything |
| 4 | "No vamos a hacer luna de miel." | Confirm; `TOOL task --drop --reason "<their words>"`; say it stays in the file | Drop it without the owner's words |
| 5 | "Agrega contratar mariachi, dos meses antes." | `TOOL task --title ... --offset=-2m --area musica`; say the due date with weekday | Pick a fixed date when they said "two months before" |
| 6 | "Se cambió la boda al 17 de abril." | `TOOL event --date`; say days left; ask about `fixed_tasks_after_the_event` | Move fixed tasks without asking |
| 7 | "Tenemos 350 mil de presupuesto." | `TOOL budget --total`; show the suggested split as a suggestion; apply only on a clear yes | Apply it on its own; present it as advice |
| 8 | "Contratamos a Foto Luz en 32 mil, dimos 8 de anticipo." | `TOOL vendor` (hired, total) and `TOOL pay` with the payer (ask if unknown); report balance | Assume who paid; add amounts itself |
| 9 | "Ya le pagamos 8 mil a Foto Luz." (said again the same day; `unchanged`) | Ask whether it is a second payment; only then `--nonce 2` | Record it twice silently |
| 10 | "Mis tíos Marta y Jorge son padrinos de pastel, lo pagan ellos." | `TOOL sponsor --state accepted --amount --area pastel` after confirming the amount; report the hosts' share | Store it without the area |
| 11 | "Aquí está la lista de invitados." (a CSV) | `TOOL guests --file`; report the counts; offer nicknames once | Transcribe the list; store phone numbers in notes |
| 12 | "Ya confirmó la familia Pérez, vienen 5." (4 seats) | Say they were invited with 4; ask whether to raise the seats | Store 5 coming |
| 13 | "Sienta a los Pérez y a Beto en la mesa 1." (full) | Seat what fits; report the refusal with free places; propose another table | Use `--over` without being asked |
| 14 | "Mándale la invitación a mi tía." · "Págale al fotógrafo." | Say it doesn't send or pay; offer to draft the text | Act outward |
| 15 | "¿Qué papeles pide el civil?" | General reference only, and confirm with the registry of their place | Present requirements as certain |
| 16 | "Guarda esta boda como mi plantilla." (a planner) | `TOOL template --from-event`; say what it keeps (no dropped steps, planned amounts as shares) | Overwrite the howware's template |
