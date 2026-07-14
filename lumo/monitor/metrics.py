import sqlite3

from lumo.monitor.events import Event

COUNTERS = {
    "proposed": "intent.proposed",
    "refused": "intent.refused",
    "injection_blocked": "injection.blocked",
    "held": "intent.held",
    "released": "intent.released",
    "reverted": "intent.reverted",
    "refunded": "intent.refunded",
}
EVENT_TO_COUNTER = {event: counter for counter, event in COUNTERS.items()}

PROM_COUNTERS = {
    "proposed": "lumo_intents_proposed_total",
    "refused": "lumo_intents_refused_total",
    "injection_blocked": "lumo_injection_blocked_total",
    "held": "lumo_intents_held_total",
    "released": "lumo_intents_released_total",
    "reverted": "lumo_intents_reverted_total",
    "refunded": "lumo_intents_refunded_total",
}
PROM_GAUGES = {
    "escrowed_value": "lumo_escrowed_value_stroops",
    "intents_open": "lumo_intents_open",
}


class Metrics:
    def __init__(self):
        self.counters = dict.fromkeys(COUNTERS, 0)

    def __call__(self, event: Event) -> None:
        counter = EVENT_TO_COUNTER.get(event.name)
        if counter:
            self.counters[counter] += 1


def snapshot(conn: sqlite3.Connection) -> dict:
    counts = {
        r["name"]: r["n"]
        for r in conn.execute("SELECT name, count(*) AS n FROM events GROUP BY name")
    }
    escrowed_value = conn.execute(
        "SELECT coalesce(sum(CAST(amount AS INTEGER)), 0) AS v FROM intents "
        "WHERE status = 'escrowed'"
    ).fetchone()["v"]
    intents_open = conn.execute(
        "SELECT count(*) AS n FROM intents "
        "WHERE status IN ('proposed', 'held', 'escrowed')"
    ).fetchone()["n"]
    return {
        "counters": {counter: counts.get(event, 0) for counter, event in COUNTERS.items()},
        "gauges": {"escrowed_value": escrowed_value, "intents_open": intents_open},
    }


def render_prometheus(snap: dict) -> str:
    lines = []
    for counter, metric in PROM_COUNTERS.items():
        lines += [
            f"# HELP {metric} Total {COUNTERS[counter]} events.",
            f"# TYPE {metric} counter",
            f"{metric} {snap['counters'][counter]}",
        ]
    for gauge, metric in PROM_GAUGES.items():
        lines += [
            f"# HELP {metric} Current {gauge.replace('_', ' ')}.",
            f"# TYPE {metric} gauge",
            f"{metric} {snap['gauges'][gauge]}",
        ]
    return "\n".join(lines) + "\n"
