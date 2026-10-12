<h1 align="center">eventos-sociales · planner de eventos sociales, sin app</h1>

<p align="center">
  <b>¿Organizas una boda, unos XV años o un bautizo? Dile la fecha a tu agente de IA. Una plantilla con cuenta
  regresiva te dice qué hacer y cuándo; tú la ajustas. Proveedores, pagos, presupuesto, padrinos, invitados, mesas
  y el programa del día, exactos.</b>
</p>

<p align="center">
  <a href="https://github.com/howware/eventos-sociales/actions/workflows/ci.yml"><img src="https://github.com/howware/eventos-sociales/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/versión-0.1.0-blue" alt="Versión 0.1.0">
  <a href="https://howware.org/es/"><img src="https://img.shields.io/badge/howware-0.2-5a45d6" alt="howware 0.2"></a>
  <img src="https://img.shields.io/badge/python-3.9%2B-blue" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/licencia-Apache%202.0-green" alt="Apache 2.0">
</p>

<p align="center"><a href="README.md">English</a> · <a href="docs/building.md">Cómo se construyó</a></p>

> **Un [howware](https://howware.org/es/):** tu saber hacer, puesto a trabajar con IA. Aquí el saber hacer es cómo se
> planea una boda en México (qué se aparta primero, qué se paga cuándo, quiénes son los padrinos) y **tus propias
> decisiones**: qué se queda en el plan, cuánto va a cada cosa, quién se sienta con quién. No hay app: tú lo dices,
> una herramienta pequeña mantiene exactas las fechas y el dinero, y una memoria que es tuya lo guarda todo. Para
> parejas que organizan su propio evento y para wedding planners con varios.

```text
› Nos casamos el 20 de marzo del año que entra. Como 150 invitados, presupuesto de 350 mil.
✓ Boda de Ana y Luis: sábado 20 de marzo de 2027, faltan 159 días. Ya está la plantilla de boda: 37 pasos.
  Como empiezan a cinco meses, 17 pasos ya tocaban. ¿Cuáles ya tienen? Luego les propongo un orden:
  primero el lugar y la iglesia (definen la fecha y el cupo), luego banquete y fotografía.

› Ya tenemos el salón y la iglesia. ¿Qué sigue?
✓ Atrasados: banquete, foto y video, música, el vestido, los padrinos. Lo siguiente, para el martes 20 de
  octubre: pláticas, traje, argollas, invitaciones. Empiecen por el banquete: es la parte más grande del
  presupuesto.

› Contratamos a Foto Luz en 32 mil, dimos 8 de anticipo. El resto antes del 1 de marzo.
✓ Foto Luz, contratado: $32,000.00 · pagado $8,000.00 (Ana y Luis) · saldo $24,000.00 para el lun 1 de mar.
  Fotografía y video: planeado $35,000.00, quedan $3,000.00.

› Ya confirmó la familia Pérez, vienen 3 de 4. ¿Cuántos van?
✓ Familia Pérez: 3 confirmados. En total 112 confirmados, 31 pendientes (hasta 143), 12 no vienen. Cupo 150.
```

## Qué hace

| Tú dices | Hace |
|---|---|
| "Nos casamos el…" | Crea el **evento** y aplica la **plantilla**: 37 pasos desde 12 meses antes hasta los agradecimientos, cada uno relativo a la fecha. Si empiezas tarde, separa lo que ya tocaba antes de empezar de lo que se fue atrasando, y el agente propone un orden |
| "¿Qué me toca?" · "¿Qué me falta?" | La **agenda**: lo atrasado, lo de esta semana, las próximas semanas, y lo demás solo como conteo. Un paso a la vez |
| "Agrega contratar mariachi dos meses antes" · "No vamos a tener luna de miel" | **Tu plan**: agregar, mover, terminar o quitar pasos. Si cambia la fecha, todo lo relativo se mueve con ella |
| "Nuestro presupuesto es de 350 mil" | El **reparto sugerido** de la plantilla por rubro (banquete, lugar, fotografía…), que suma al centavo; lo aceptas o pones tus montos |
| "Contratamos al fotógrafo…" · "Dimos un anticipo" | **Proveedores** con contrato, saldo y fecha para liquidar; **pagos** con quién pagó (los novios, los papás, un padrino) |
| "Mis tíos son padrinos de pastel" | **Padrinos**: rol, estado y lo que cubren; lo que pagan baja la parte de los anfitriones en el presupuesto |
| "Aquí está la lista de invitados" · "Los Ramírez no vienen" | **Invitaciones** con pases, confirmación y dieta; importa un CSV o JSON y exporta un CSV para el salón |
| "Sienta a la familia Pérez en la mesa 1" | **Mesas** con cupo revisado, y quién falta de sentar |
| "Hagamos el minuto a minuto" | El **programa del día**, en orden, también después de medianoche |
| (planners) "Guarda esta boda como mi plantilla" | Tu propia **plantilla** para los siguientes eventos |

## Cómo funciona

| Parte | Aquí |
|---|---|
| Protocolo | [`skill/eventos-sociales/SKILL.md`](skill/eventos-sociales/SKILL.md): el método y las reglas del agente, en palabras simples |
| Herramienta | [`eventos.py`](skill/eventos-sociales/scripts/eventos.py): solo lo que debe ser exacto: las fechas de la cuenta regresiva, la agenda, el reparto del presupuesto y los saldos en centavos, pagos sin duplicados, conteo de pases y cupo de mesas, el orden del programa, importar y exportar CSV |
| Plantilla | [`seed.json`](skill/eventos-sociales/scripts/seed.json): la plantilla de boda (pasos con su anticipación, rubros con su porcentaje sugerido). Tus cambios viven en tu memoria |
| Memoria | El adaptador [Long-Term Memory for AI](https://github.com/howware/long-term-memory-for-AI): tus eventos, en un archivo local, con historial |

## Instalación

```bash
git clone https://github.com/howware/long-term-memory-for-AI
python long-term-memory-for-AI/tools/install_skill.py --target ~/.claude/skills/project-memory
git clone https://github.com/howware/eventos-sociales
python eventos-sociales/tools/install_skill.py                                             # Claude Code
python eventos-sociales/tools/install_skill.py --target ~/.codex/skills/eventos-sociales    # Codex
```

Crea una carpeta para tu evento (o para todos tus eventos, si eres planner), abre Claude Code ahí (agrega a su
`CLAUDE.md` la instrucción de memoria persistente de
[Long-Term Memory for AI](https://github.com/howware/long-term-memory-for-AI#set-up-a-project)) y di *"Nos casamos
el…"*.

## Privacidad y límites

| Pensado para quedarse en tu computadora | Lo que ve el agente de IA |
|---|---|
| El archivo de memoria con tus eventos, plan, presupuesto, proveedores, pagos, padrinos, invitaciones, mesas y programa. Una lista de invitados que importas la lee la herramienta, que guarda solo nombre, grupo, pases, confirmación, dieta y nota | El plan y sus fechas; los montos y quién pagó; los proveedores; las invitaciones como tú las nombras, cuando las consulta; lo que escribes |

**Lo que no puede hacer ni garantizar:**
- Lo que ve el agente sale de tu computadora hacia tu proveedor de IA, bajo sus términos. **Tus invitados son otras
  personas** que no eligieron compartir sus nombres ni sus dietas: puedes usar apodos o iniciales ("Familia P.",
  "Tía Lupe"). El protocolo le indica al agente no guardar sus teléfonos, direcciones ni nada más allá de lo que
  pide la organización.
- El archivo de memoria no está cifrado.
- **Quitar oculta, no borra:** un paso quitado, una invitación eliminada o un pago anulado se quedan en el archivo.
- **No hay notificaciones.** Lo pendiente aparece cuando abres una conversación.
- La plantilla y el presupuesto sugerido son **referencias generales**, no asesoría legal ni financiera. Los
  requisitos del civil y de la iglesia cambian según el lugar: confírmalos ahí.
- La memoria vive en una computadora: si dos personas planean juntas, no se comparte sola.
- El acomodo de mesas es una lista por mesa; un plano dibujado del salón no cabe en una conversación.

## Desarrollo

```bash
python -m unittest discover -s tests -v
git ls-files -z | xargs -0 python tools/check_private_data.py
```

Las pruebas usan solo datos sintéticos. Ver [AGENTS.md](AGENTS.md).

## Licencia

[Apache 2.0](LICENSE).
