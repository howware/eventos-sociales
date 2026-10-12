# How this howware was built

A record of building `eventos-sociales` with the
[`howware-builder`](https://github.com/howware/howware/blob/main/skills/howware-builder/SKILL.md) protocol. The
owner's words are kept verbatim, in Spanish.

## 1. Choosing it

The owner brought the idea already formed:

> «tengo un muy buen howware, un planeador de bodas y eventos similares»

It passes the howware test almost entirely. The value of a wedding planner app is the countdown, the money and the
guest list, and a conversation handles all three: "¿qué me toca?", "ya pagamos el anticipo", "ya confirmó la
familia Pérez". What does not fit is the drawn plan of the room, where tables are dragged around a picture. Tables
are kept as lists, with the capacity checked by the tool.

## 2. Interview

| Topic | The owner's words |
|---|---|
| Who it is for | «puede ser para la pareja o para un weeding planner» |
| What matters most | «casi siempre el problema es que por ejemplo los novios no saben por donde empezar y muchas veces lo que necesitan es una plantilla y a partir de esa plantilla van agregando y quitando cosas, la plantilla les da una direccion de que hacer y cuando hacerlo y asi les reduce el estres» |
| Scope of the first version | «todo lo que se pueda» |
| Real use | «tengo un amigo que si lo usaria en un evento real, pero como yo ya me case ya se de que se trata» |
| The wedding template (the draft proposed, from 12 months to after the event) | «por el momento todo esta bien, segun iteremos vamos mejorando la plantilla» |
| Suggested budget | «hay que darles la opcion de lo sugerido pero las parejas finalmente deciden» |
| The name | «eventos creo que se puede confundir con cosas de programacion y sistemas» → «planner de eventos sociales / social events planner» |

## 3. Design decisions

| Decision | Why |
|---|---|
| The template is the center: each step has an offset from the event day (`-12m`, `-2w`, `+1w`) and is copied into the event as its own task | The owner's point: a template gives direction and lowers stress, and the couple adds and removes from it. Copying makes the plan theirs; offsets make a new date move everything |
| A step can also have a fixed date, which doesn't move; when the date changes, fixed steps that fall after the event are listed | A fitting or a vendor's appointment doesn't move with the wedding |
| Starting late separates "late from the start" from "slipped" | Most couples don't start 12 months before. What was due before they began is not their failure, and the agent proposes an order instead |
| The agenda shows late, this week and the next weeks; the rest only as counts by month | Less stress: one step at a time |
| The suggested split is computed by the tool in whole pesos by largest remainder, so it adds up to the total; it is applied only on a yes | «lo sugerido pero las parejas finalmente deciden» |
| Per area: hired, covered by sponsors, the hosts' share, paid, owed, left | In Mexico the padrinos pay for part of the event, and the parents often pay vendors: who pays matters as much as how much |
| Payments are events with a stable key (vendor, day, amount, payer); a second identical one needs `--nonce` | Saying "ya pagamos" twice must not pay twice |
| An invitation (one envelope, with its seats) is the unit, not each person | That is how invitations, RSVPs and tables work in practice; places coming can be fewer than seats |
| Only name, group, seats, RSVP, diet, note and table are stored about a guest | Guests are third parties; the privacy section says so and suggests nicknames |
| Several events in one memory, with `--event` optional when only one is in planning | The same tool serves a couple and a planner |
| A planner can save an event as their own template; the howware's templates update with it, the owner's never | A planner's way of working is their know-how |
| Only the wedding template in 0.1 | It is the one the owner reviewed; XV años and baptisms can start with `--template none` and be saved as templates |

## 4. Real use

Pending: a friend of the owner will use it for a real wedding.

## 5. Not included in 0.1

Templates for XV años, baptisms and anniversaries; a drawn plan of the room; sharing the plan between two
computers; crossing payments with `finanzas-personales` and bank statements; sending invitations or messages;
notifications.
