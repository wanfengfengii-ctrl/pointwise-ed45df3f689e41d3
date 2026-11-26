import json
from dataclasses import dataclass

from contract import fail
from narration.lookup import read_review_results
from program.release import load_show
from review.coverage import find_pending_ticks
from review.timeline import build_timeline
from session.closing import read_closed_range
from session.opening import read_session


@dataclass(frozen=True)
class StoredReport:
    report_id: int
    session_id: int
    last_tick: int
    entries: tuple[dict, ...]

    def payload(self):
        return {'status': 'published', 'report_id': self.report_id, 'session_id': self.session_id,
                'last_tick': self.last_tick, 'entries': list(self.entries)}


def init_review_schema(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            report_id INTEGER PRIMARY KEY,
            session_id INTEGER NOT NULL UNIQUE REFERENCES sessions(session_id),
            last_tick INTEGER NOT NULL,
            entries TEXT NOT NULL
        )
    ''')


def _from_row(row):
    return StoredReport(row['report_id'], row['session_id'], row['last_tick'],
                        tuple(json.loads(row['entries'])))


def read_report(db, report_id):
    row = db.execute('SELECT * FROM reports WHERE report_id = ?', (report_id,)).fetchone()
    if row is None:
        fail(404, 'unknown_report', f'Report {report_id} has not been published')
    return _from_row(row)


def publish_report(db, session_id):
    closed = read_closed_range(db, session_id)
    original = db.execute('SELECT * FROM reports WHERE session_id = ?', (session_id,)).fetchone()
    if original is not None:
        return _from_row(original).payload()
    session = read_session(db, session_id)
    show = load_show(db, session.show_id)
    results = read_review_results(db, session_id)
    pending = find_pending_ticks(closed, show.draft.groups, results)
    if pending:
        return {'status': 'pending', 'session_id': session_id, 'last_tick': closed.last_tick,
                'pending': pending}
    entries = tuple(entry.payload() for entry in build_timeline(results))
    cursor = db.execute('INSERT INTO reports(session_id, last_tick, entries) VALUES (?, ?, ?)',
                        (session_id, closed.last_tick, json.dumps(entries)))
    return StoredReport(cursor.lastrowid, session_id, closed.last_tick, entries).payload()
