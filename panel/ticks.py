from dataclasses import dataclass

from session.scope import BoardTick


@dataclass(frozen=True)
class PanelTickRecord:
    press_ids: tuple[str, ...]
    seal_id: str | None


def init_panel_schema(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS panel_presses (
            admission_order INTEGER PRIMARY KEY,
            event_id TEXT NOT NULL UNIQUE REFERENCES deliveries(delivery_id),
            session_id INTEGER NOT NULL,
            board_id TEXT NOT NULL,
            tick INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS panel_presses_scope
            ON panel_presses(session_id, board_id, tick, admission_order);
        CREATE TABLE IF NOT EXISTS panel_seals (
            session_id INTEGER NOT NULL,
            board_id TEXT NOT NULL,
            tick INTEGER NOT NULL,
            event_id TEXT NOT NULL UNIQUE REFERENCES deliveries(delivery_id),
            PRIMARY KEY (session_id, board_id, tick)
        );
    ''')


def read_panel_tick(db, scope: BoardTick):
    presses = db.execute('''
        SELECT event_id FROM panel_presses
        WHERE session_id = ? AND board_id = ? AND tick = ? ORDER BY admission_order
    ''', scope.key())
    seal = db.execute('''
        SELECT event_id FROM panel_seals WHERE session_id = ? AND board_id = ? AND tick = ?
    ''', scope.key()).fetchone()
    return PanelTickRecord(tuple(row['event_id'] for row in presses), seal['event_id'] if seal else None)


def record_press(db, scope: BoardTick, event_id):
    db.execute('INSERT INTO panel_presses(session_id, board_id, tick, event_id) VALUES (?, ?, ?, ?)',
               (*scope.key(), event_id))


def record_seal(db, scope: BoardTick, event_id):
    db.execute('INSERT INTO panel_seals(session_id, board_id, tick, event_id) VALUES (?, ?, ?, ?)',
               (*scope.key(), event_id))
