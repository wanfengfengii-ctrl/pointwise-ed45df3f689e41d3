import json
from dataclasses import asdict, dataclass

from program.audio import AudioClip
from session.scope import GroupTick


@dataclass(frozen=True)
class PlayResult:
    session_id: int
    group_id: str
    tick: int
    status: str
    start_id: int | None = None
    rule_id: str | None = None
    clip: AudioClip | None = None
    sources: tuple[dict, ...] = ()

    def payload(self):
        result = {'session_id': self.session_id, 'group_id': self.group_id,
                  'tick': self.tick, 'status': self.status}
        if self.status == 'started':
            result.update(start_id=self.start_id, rule_id=self.rule_id,
                          clip=asdict(self.clip), sources=list(self.sources))
        return result


def init_playback_schema(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS play_starts (
            start_id INTEGER PRIMARY KEY,
            session_id INTEGER NOT NULL REFERENCES sessions(session_id),
            group_id TEXT NOT NULL,
            tick INTEGER NOT NULL,
            details TEXT NOT NULL,
            UNIQUE (session_id, group_id, tick)
        );
        CREATE TABLE IF NOT EXISTS group_results (
            session_id INTEGER NOT NULL REFERENCES sessions(session_id),
            group_id TEXT NOT NULL,
            tick INTEGER NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('started', 'silent')),
            start_id INTEGER UNIQUE REFERENCES play_starts(start_id),
            PRIMARY KEY (session_id, group_id, tick),
            CHECK ((status = 'started' AND start_id IS NOT NULL)
                OR (status = 'silent' AND start_id IS NULL))
        );
    ''')


_RESULT_ROWS = '''
    SELECT r.session_id, r.group_id, r.tick, r.status, r.start_id, p.details
    FROM group_results AS r LEFT JOIN play_starts AS p ON p.start_id = r.start_id
'''


def _read_row(row):
    identity = (row['session_id'], row['group_id'], row['tick'], row['status'])
    if row['status'] == 'silent':
        return PlayResult(*identity)
    details = json.loads(row['details'])
    return PlayResult(*identity, row['start_id'], details['rule_id'],
                      AudioClip(**details['clip']), tuple(details['sources']))


def read_result(db, scope: GroupTick):
    row = db.execute(_RESULT_ROWS + ' WHERE r.session_id = ? AND r.group_id = ? AND r.tick = ?',
                     scope.key()).fetchone()
    return _read_row(row) if row is not None else None


def commit_result(db, scope: GroupTick, *, rule_id=None, clip=None, sources=()):
    original = read_result(db, scope)
    if original is not None:
        return original
    start_id = None
    status = 'silent'
    if rule_id is not None:
        details = {'rule_id': rule_id, 'clip': asdict(clip), 'sources': list(sources)}
        cursor = db.execute('''
            INSERT INTO play_starts(session_id, group_id, tick, details) VALUES (?, ?, ?, ?)
        ''', (*scope.key(), json.dumps(details)))
        start_id = cursor.lastrowid
        status = 'started'
    db.execute('''
        INSERT INTO group_results(session_id, group_id, tick, status, start_id) VALUES (?, ?, ?, ?, ?)
    ''', (*scope.key(), status, start_id))
    return PlayResult(*scope.key(), status, start_id, rule_id, clip, tuple(sources))


def read_session_results(db, session_id):
    rows = db.execute(_RESULT_ROWS + ' WHERE r.session_id = ? ORDER BY r.tick, r.group_id', (session_id,))
    return [_read_row(row) for row in rows]


def read_started_plays(db, session_id):
    rows = db.execute('''
        SELECT session_id, group_id, tick, 'started' AS status, start_id, details
        FROM play_starts WHERE session_id = ? ORDER BY start_id
    ''', (session_id,))
    return [_read_row(row) for row in rows]
