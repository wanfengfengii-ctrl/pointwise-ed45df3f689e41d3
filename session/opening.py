import json
from dataclasses import asdict, dataclass

from contract import fail
from program.release import load_show
from session.binding import PanelBinding, verify_bindings


@dataclass(frozen=True)
class SessionRecord:
    session_id: int
    show_id: int
    bindings: dict[str, PanelBinding]
    last_tick: int = 0
    closed_tick: int | None = None

    def payload(self):
        return {
            'session_id': self.session_id,
            'show_id': self.show_id,
            'bindings': [asdict(binding) for binding in self.bindings.values()],
            'last_tick': self.last_tick,
            'closed_tick': self.closed_tick,
        }


def init_session_schema(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            session_id INTEGER PRIMARY KEY,
            show_id INTEGER NOT NULL REFERENCES shows(show_id),
            bindings TEXT NOT NULL,
            last_tick INTEGER NOT NULL DEFAULT 0 CHECK (last_tick >= 0),
            closed_tick INTEGER CHECK (closed_tick = last_tick)
        )
    ''')


def open_session(db, show_id, entries):
    show = load_show(db, show_id)
    bindings = verify_bindings(show, entries)
    body = json.dumps([asdict(binding) for binding in bindings.values()])
    cursor = db.execute('INSERT INTO sessions(show_id, bindings) VALUES (?, ?)', (show_id, body))
    return SessionRecord(cursor.lastrowid, show.show_id, bindings)


def read_session(db, session_id):
    row = db.execute('SELECT * FROM sessions WHERE session_id = ?', (session_id,)).fetchone()
    if row is None:
        fail(404, 'unknown_session', f'Session {session_id} has not been opened')
    bindings = {entry['board_id']: PanelBinding(**entry) for entry in json.loads(row['bindings'])}
    return SessionRecord(session_id, row['show_id'], bindings, row['last_tick'], row['closed_tick'])
