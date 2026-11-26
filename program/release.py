import json
from dataclasses import dataclass

from contract import fail
from program.drafts import ShowDraft, build_draft


@dataclass(frozen=True)
class IssuedShow:
    show_id: int
    draft: ShowDraft

    def payload(self):
        return {'show_id': self.show_id, **self.draft.payload()}


def init_program_schema(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS shows (
            show_id INTEGER PRIMARY KEY,
            draft TEXT NOT NULL
        )
    ''')


def issue(db, payload):
    draft = build_draft(payload)
    cursor = db.execute('INSERT INTO shows(draft) VALUES (?)', (json.dumps(draft.payload()),))
    return IssuedShow(cursor.lastrowid, draft)


def load_show(db, show_id):
    row = db.execute('SELECT draft FROM shows WHERE show_id = ?', (show_id,)).fetchone()
    if row is None:
        fail(404, 'unknown_show', f'Show {show_id} has not been issued')
    return IssuedShow(show_id, build_draft(json.loads(row['draft'])))
