import json

from contract import fail
from narration.decide import settle_group_tick
from narration.playback import commit_result, read_result
from panel.evidence import PressEvidence, decode_evidence


def init_correction_schema(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS received_authorizations (
            receipt_order INTEGER PRIMARY KEY,
            event_id TEXT NOT NULL UNIQUE,
            session_id INTEGER NOT NULL REFERENCES sessions(session_id),
            group_id TEXT NOT NULL,
            tick INTEGER NOT NULL,
            rule_id TEXT,
            press_ids TEXT NOT NULL,
            payload TEXT NOT NULL
        )
    ''')


def read_received_authorization(db, event_id):
    return db.execute(
        'SELECT * FROM received_authorizations WHERE event_id = ?', (event_id,)
    ).fetchone()


def merge_authorization(db, evidence, fixed):
    if fixed is None:
        fail(409, 'authorization_conflict',
             'No final authorization was issued for that group tick')
    if (fixed.delivery_id != evidence.event_id or fixed.rule_id != evidence.rule_id
            or fixed.press_ids != evidence.press_ids):
        fail(409, 'authorization_conflict',
             'The authorization body differs from the fixed authorization')
    confirmation = {
        'session_id': evidence.session_id, 'group_id': evidence.group_id, 'tick': evidence.tick,
        'event_id': evidence.event_id, 'status': 'received',
    }
    existing = read_received_authorization(db, evidence.event_id)
    if existing is not None:
        if json.loads(existing['payload']) != evidence.payload():
            fail(409, 'authorization_conflict',
                 'This authorization event already has a different body')
        return confirmation
    db.execute('''
        INSERT INTO received_authorizations
            (event_id, session_id, group_id, tick, rule_id, press_ids, payload)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (evidence.event_id, evidence.session_id, evidence.group_id, evidence.tick,
          evidence.rule_id, json.dumps(evidence.press_ids), json.dumps(evidence.payload())))
    return confirmation


def _received_press(db, session_id, board_id, tick, press_id):
    row = db.execute('''
        SELECT payload FROM received_evidence
        WHERE event_id = ? AND session_id = ? AND board_id = ? AND tick = ? AND kind = 'press'
    ''', (press_id, session_id, board_id, tick)).fetchone()
    if row is None:
        return None
    evidence = decode_evidence(json.loads(row['payload']))
    return evidence if isinstance(evidence, PressEvidence) else None


def attempt_authorized_start(db, scope, fixed):
    if fixed is None:
        return None
    if read_received_authorization(db, fixed.delivery_id) is None:
        return None
    if fixed.rule_id is None:
        return commit_result(db, scope)
    rule = next((item for item in scope.group.rules if item.rule_id == fixed.rule_id), None)
    if rule is None:
        fail(409, 'authorization_conflict',
             'The fixed authorization names a rule outside this group')
    sources = []
    for board in rule.requires:
        press_id = fixed.press_ids.get(board)
        if press_id is None:
            return None
        press = _received_press(db, scope.session.session_id, board, scope.tick, press_id)
        if press is None:
            return None
        sources.append({
            'board_id': board, 'session_id': press.session_id, 'tick': press.tick,
            'event_id': press.event_id, 'request_id': press.request_id,
            'position': scope.session.bindings[board].position,
        })
    clip = scope.show.draft.audio[rule.audio_id]
    return commit_result(db, scope, rule_id=rule.rule_id, clip=clip, sources=sources)


def settle(db, scope, fixed=None):
    """Settle a group tick under the rules of its session mode."""
    original = read_result(db, scope)
    if original is not None:
        return original
    if scope.session.mode != 'correctable':
        return settle_group_tick(db, scope)
    return attempt_authorized_start(db, scope, fixed)
