import json
from dataclasses import dataclass

from contract import fail
from panel.evidence import PressEvidence, SealEvidence, decode_evidence
from session.scope import BoardTick, GroupTick


@dataclass(frozen=True)
class ReceivedBoard:
    presses: tuple[PressEvidence, ...]
    seal: SealEvidence | None

    @property
    def first_press(self):
        return self.presses[0] if self.presses else None


def init_narration_facts_schema(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS received_evidence (
            receipt_order INTEGER PRIMARY KEY,
            event_id TEXT NOT NULL UNIQUE,
            session_id INTEGER NOT NULL REFERENCES sessions(session_id),
            board_id TEXT NOT NULL,
            tick INTEGER NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('press', 'seal')),
            payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS received_evidence_scope
            ON received_evidence(session_id, board_id, tick, receipt_order);
        CREATE UNIQUE INDEX IF NOT EXISTS received_seal_scope
            ON received_evidence(session_id, board_id, tick) WHERE kind = 'seal';
    ''')


def _read_board(db, session_id, board_id, tick):
    rows = db.execute('''
        SELECT payload FROM received_evidence WHERE session_id = ? AND board_id = ? AND tick = ?
        ORDER BY receipt_order
    ''', (session_id, board_id, tick))
    presses = []
    seal = None
    for row in rows:
        evidence = decode_evidence(json.loads(row['payload']))
        if isinstance(evidence, PressEvidence):
            presses.append(evidence)
        else:
            seal = evidence
    return ReceivedBoard(tuple(presses), seal)


def merge_evidence(db, scope: BoardTick, evidence: PressEvidence | SealEvidence):
    if (evidence.session_id, evidence.board_id, evidence.tick) != scope.key():
        fail(409, 'evidence_conflict', 'Evidence refers to a different board tick')
    body = evidence.payload()
    confirmation = {key: body[key] for key in ('session_id', 'board_id', 'tick', 'event_id')}
    confirmation['status'] = 'received'
    existing = db.execute('SELECT payload FROM received_evidence WHERE event_id = ?',
                          (evidence.event_id,)).fetchone()
    if existing is not None:
        if json.loads(existing['payload']) != body:
            fail(409, 'evidence_conflict', 'This event identifier already has a different body')
        return confirmation
    state = _read_board(db, *scope.key())
    if isinstance(evidence, SealEvidence):
        if state.seal is not None or not set(evidence.press_ids).issuperset(
            press.event_id for press in state.presses
        ):
            fail(409, 'evidence_conflict', 'Seal disagrees with the board tick already received')
    elif state.seal is not None and evidence.event_id not in state.seal.press_ids:
        fail(409, 'evidence_conflict', 'This press is outside the received seal')
    db.execute('''
        INSERT INTO received_evidence(event_id, session_id, board_id, tick, kind, payload)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (evidence.event_id, *scope.key(), body['kind'], json.dumps(body)))
    return confirmation


def read_group_facts(db, scope: GroupTick):
    return {
        board: _read_board(db, scope.session.session_id, board, scope.tick)
        for board in scope.group.boards
    }
