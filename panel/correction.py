import json
from dataclasses import dataclass
from itertools import product

from contract import fail
from panel.delivery import queue_evidence
from panel.evidence import make_authorization_evidence
from program.rules import select_rule
from session.scope import BoardTick, GroupTick


@dataclass(frozen=True)
class Proposal:
    proposal_id: int
    session_id: int
    group_id: str
    tick: int
    request_id: str
    rule_id: str | None
    press_ids: dict[str, str]

    def payload(self):
        return {
            'status': 'proposed',
            'proposal_id': self.proposal_id,
            'session_id': self.session_id,
            'group_id': self.group_id,
            'tick': self.tick,
            'request_id': self.request_id,
            'rule_id': self.rule_id,
            'press_ids': dict(self.press_ids),
        }


@dataclass(frozen=True)
class Authorization:
    authorization_id: int
    session_id: int
    group_id: str
    tick: int
    rule_id: str | None
    delivery_id: str
    press_ids: dict[str, str]

    def payload(self):
        return {
            'status': 'authorized',
            'authorization_id': self.authorization_id,
            'session_id': self.session_id,
            'group_id': self.group_id,
            'tick': self.tick,
            'rule_id': self.rule_id,
            'delivery_id': self.delivery_id,
            'press_ids': dict(self.press_ids),
        }


_SCHEMA = '''
    CREATE TABLE IF NOT EXISTS correction_proposals (
        proposal_id INTEGER PRIMARY KEY,
        session_id INTEGER NOT NULL,
        group_id TEXT NOT NULL,
        tick INTEGER NOT NULL,
        request_id TEXT NOT NULL,
        rule_id TEXT,
        press_ids TEXT NOT NULL,
        UNIQUE (session_id, request_id)
    );
    CREATE TABLE IF NOT EXISTS correction_withdrawals (
        session_id INTEGER NOT NULL,
        press_id TEXT NOT NULL,
        board_id TEXT NOT NULL,
        tick INTEGER NOT NULL,
        request_id TEXT NOT NULL,
        PRIMARY KEY (session_id, press_id)
    );
    CREATE TABLE IF NOT EXISTS correction_retractions (
        session_id INTEGER NOT NULL,
        request_id TEXT NOT NULL,
        board_id TEXT NOT NULL,
        tick INTEGER NOT NULL,
        press_id TEXT NOT NULL,
        response TEXT NOT NULL,
        PRIMARY KEY (session_id, request_id)
    );
    CREATE TABLE IF NOT EXISTS correction_authorize_requests (
        session_id INTEGER NOT NULL,
        request_id TEXT NOT NULL,
        group_id TEXT NOT NULL,
        tick INTEGER NOT NULL,
        PRIMARY KEY (session_id, request_id)
    );
    CREATE TABLE IF NOT EXISTS correction_authorizations (
        authorization_id INTEGER PRIMARY KEY,
        session_id INTEGER NOT NULL,
        group_id TEXT NOT NULL,
        tick INTEGER NOT NULL,
        rule_id TEXT,
        delivery_id TEXT NOT NULL UNIQUE,
        UNIQUE (session_id, group_id, tick)
    );
    CREATE TABLE IF NOT EXISTS correction_authorization_presses (
        authorization_id INTEGER NOT NULL
            REFERENCES correction_authorizations(authorization_id),
        session_id INTEGER NOT NULL,
        board_id TEXT NOT NULL,
        press_id TEXT NOT NULL,
        PRIMARY KEY (authorization_id, board_id)
    );
    CREATE INDEX IF NOT EXISTS correction_adopted_press
        ON correction_authorization_presses(session_id, press_id);
'''


def init_correction_schema(db):
    db.executescript(_SCHEMA)


def _proposal(row):
    return Proposal(row['proposal_id'], row['session_id'], row['group_id'], row['tick'],
                    row['request_id'], row['rule_id'], json.loads(row['press_ids']))


def require_mode(session):
    if session.mode != 'correctable':
        fail(409, 'not_correctable', 'This session was not opened in correctable mode')


def registered_presses(db, session_id, board_id, tick):
    return [
        row['event_id']
        for row in db.execute('''
            SELECT event_id FROM panel_presses
            WHERE session_id = ? AND board_id = ? AND tick = ? ORDER BY admission_order
        ''', (session_id, board_id, tick))
    ]


def press_registered(db, session_id, board_id, tick, press_id):
    return db.execute('''
        SELECT 1 FROM panel_presses
        WHERE session_id = ? AND board_id = ? AND tick = ? AND event_id = ?
    ''', (session_id, board_id, tick, press_id)).fetchone() is not None


def board_sealed(db, session_id, board_id, tick):
    return db.execute('''
        SELECT 1 FROM panel_seals WHERE session_id = ? AND board_id = ? AND tick = ?
    ''', (session_id, board_id, tick)).fetchone() is not None


def read_proposal(db, proposal_id):
    row = db.execute('SELECT * FROM correction_proposals WHERE proposal_id = ?',
                     (proposal_id,)).fetchone()
    return None if row is None else _proposal(row)


def read_proposal_by_request(db, session_id, request_id):
    row = db.execute('''
        SELECT * FROM correction_proposals WHERE session_id = ? AND request_id = ?
    ''', (session_id, request_id)).fetchone()
    return None if row is None else _proposal(row)


def propose(db, scope: GroupTick, request_id, rule_id, press_ids):
    require_mode(scope.session)
    session_id, group_id, tick = scope.session.session_id, scope.group.group_id, scope.tick
    original = read_proposal_by_request(db, session_id, request_id)
    if original is not None:
        if ((original.group_id, original.tick, original.rule_id, original.press_ids)
                != (group_id, tick, rule_id, press_ids)):
            fail(409, 'request_conflict',
                 'That request identifier already proposed different content')
        return original.payload()
    if rule_id is None:
        if press_ids:
            fail(400, 'invalid_press_ids', 'A silent proposal cannot select a press')
    else:
        rule = next((item for item in scope.group.rules if item.rule_id == rule_id), None)
        if rule is None:
            fail(404, 'unknown_rule', f'Group {group_id} has no rule {rule_id}')
        if set(press_ids) != set(rule.requires):
            fail(400, 'invalid_press_ids',
                 'A proposal must select exactly the boards required by its rule')
        for board, press_id in press_ids.items():
            if not press_registered(db, session_id, board, tick, press_id):
                fail(404, 'unknown_press', f'Press {press_id} was not accepted on board {board}')
    cursor = db.execute('''
        INSERT INTO correction_proposals(session_id, group_id, tick, request_id, rule_id, press_ids)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (session_id, group_id, tick, request_id, rule_id, json.dumps(press_ids)))
    return Proposal(cursor.lastrowid, session_id, group_id, tick, request_id, rule_id,
                    dict(press_ids)).payload()


def withdrawn_press_ids(db, session_id):
    return {
        row['press_id']
        for row in db.execute('SELECT press_id FROM correction_withdrawals WHERE session_id = ?',
                              (session_id,))
    }


def _possible_states(effective, sealed):
    # V1 semantics: any effective press pins a board down; without a press, only a
    # seal can confirm the board is up, otherwise a late press could still arrive.
    if effective:
        return (True,)
    if sealed:
        return (False,)
    return False, True


def settled_rule(group, effective, sealed):
    """Return the rule every still-possible board state agrees on, and whether it is settled."""
    winners = set()
    for states in product(*(
            _possible_states(effective[board], sealed[board]) for board in group.boards
    )):
        pressed = {board for board, down in zip(group.boards, states) if down}
        winners.add(select_rule(group, pressed))
        if len(winners) > 1:
            return None, False
    return winners.pop(), True


def is_adopted(db, session_id, press_id):
    return db.execute('''
        SELECT 1 FROM correction_authorization_presses
        WHERE session_id = ? AND press_id = ? LIMIT 1
    ''', (session_id, press_id)).fetchone() is not None


def read_authorization(db, session_id, group_id, tick):
    row = db.execute('''
        SELECT * FROM correction_authorizations WHERE session_id = ? AND group_id = ? AND tick = ?
    ''', (session_id, group_id, tick)).fetchone()
    if row is None:
        return None
    presses = {
        item['board_id']: item['press_id']
        for item in db.execute('''
            SELECT board_id, press_id FROM correction_authorization_presses
            WHERE authorization_id = ? ORDER BY board_id
        ''', (row['authorization_id'],))
    }
    return Authorization(row['authorization_id'], row['session_id'], row['group_id'],
                         row['tick'], row['rule_id'], row['delivery_id'], presses)


def read_authorize_request(db, session_id, request_id):
    return db.execute('''
        SELECT * FROM correction_authorize_requests WHERE session_id = ? AND request_id = ?
    ''', (session_id, request_id)).fetchone()


def _record_authorize_request(db, scope: GroupTick, request_id):
    db.execute('''
        INSERT INTO correction_authorize_requests(session_id, request_id, group_id, tick)
        VALUES (?, ?, ?, ?)
    ''', (scope.session.session_id, request_id, scope.group.group_id, scope.tick))


def _adoption(proposal, rule, effective):
    if proposal.rule_id != (rule.rule_id if rule is not None else None):
        fail(409, 'proposal_conflict',
             'The proposal names a rule which is no longer the effective rule')
    if rule is None:
        if proposal.press_ids:
            fail(409, 'proposal_conflict', 'A silent proposal cannot select a press')
        return {}
    if set(proposal.press_ids) != set(rule.requires):
        fail(409, 'proposal_conflict',
             'The proposal does not select exactly the boards its rule requires')
    for board, press_id in proposal.press_ids.items():
        if press_id not in effective[board]:
            fail(409, 'proposal_conflict',
                 'The proposal relies on a press which is no longer effective')
    return dict(proposal.press_ids)


def authorize(db, scope: GroupTick, request_id, proposal_id=None):
    require_mode(scope.session)
    session_id, group_id, tick = scope.session.session_id, scope.group.group_id, scope.tick
    original_request = read_authorize_request(db, session_id, request_id)
    if original_request is not None and (
            original_request['group_id'], original_request['tick']) != (group_id, tick):
        fail(409, 'request_conflict',
             'That request identifier already authorized a different group tick')
    completed = read_authorization(db, session_id, group_id, tick)
    if completed is not None:
        if original_request is None:
            _record_authorize_request(db, scope, request_id)
        return completed.payload()
    proposal = None
    if proposal_id is not None:
        proposal = read_proposal(db, proposal_id)
        if proposal is None:
            fail(404, 'unknown_proposal', f'Proposal {proposal_id} has not been submitted')
        if (proposal.session_id, proposal.group_id, proposal.tick) != (session_id, group_id, tick):
            fail(409, 'proposal_conflict', 'The proposal belongs to a different group tick')

    withdrawn = withdrawn_press_ids(db, session_id)
    effective = {
        board: [press_id for press_id in registered_presses(db, session_id, board, tick)
                if press_id not in withdrawn]
        for board in scope.group.boards
    }
    sealed = {
        board: board_sealed(db, session_id, board, tick) for board in scope.group.boards
    }
    # As in V1, the effective state reads a board with any accepted, un-withdrawn press
    # as down, and a seal with no effective press as the confirmed empty reference. An
    # unsealed board with no press stays open, because a late press could still come.
    rule, decided = settled_rule(scope.group, effective, sealed)
    if not decided:
        # The rule must be unambiguous across every still-possible board state; until
        # then a late press or a retraction could still select a different rule.
        if original_request is None:
            _record_authorize_request(db, scope, request_id)
        return {'status': 'pending', 'session_id': session_id, 'group_id': group_id, 'tick': tick}
    if proposal is not None:
        adopted = _adoption(proposal, rule, effective)
    elif rule is not None:
        adopted = {board: effective[board][0] for board in rule.requires}
    else:
        adopted = {}

    rule_id = rule.rule_id if rule is not None else None
    evidence = make_authorization_evidence(scope, rule_id, adopted)
    delivery_id = queue_evidence(db, evidence)
    cursor = db.execute('''
        INSERT INTO correction_authorizations(session_id, group_id, tick, rule_id, delivery_id)
        VALUES (?, ?, ?, ?, ?)
    ''', (session_id, group_id, tick, rule_id, delivery_id))
    authorization_id = cursor.lastrowid
    for board, press_id in adopted.items():
        db.execute('''
            INSERT INTO correction_authorization_presses
                (authorization_id, session_id, board_id, press_id)
            VALUES (?, ?, ?, ?)
        ''', (authorization_id, session_id, board, press_id))
    if original_request is None:
        _record_authorize_request(db, scope, request_id)
    return Authorization(authorization_id, session_id, group_id, tick, rule_id, delivery_id,
                         dict(adopted)).payload()


def retract(db, scope: BoardTick, press_id, request_id, mode='correctable'):
    if mode != 'correctable':
        fail(409, 'not_correctable', 'This session was not opened in correctable mode')
    row = db.execute('''
        SELECT * FROM correction_retractions WHERE session_id = ? AND request_id = ?
    ''', (scope.session_id, request_id)).fetchone()
    if row is not None:
        if (row['board_id'], row['tick'], row['press_id']) != (
                scope.board_id, scope.tick, press_id):
            fail(409, 'request_conflict',
                 'That request identifier already retracted a different press')
        return json.loads(row['response'])
    if not press_registered(db, scope.session_id, scope.board_id, scope.tick, press_id):
        fail(404, 'unknown_press', f'Press {press_id} was not accepted on board {scope.board_id}')
    response = {'session_id': scope.session_id, 'board_id': scope.board_id, 'tick': scope.tick,
                'press_id': press_id}
    if is_adopted(db, scope.session_id, press_id):
        response['status'] = 'protected'
    else:
        db.execute('''
            INSERT OR IGNORE INTO correction_withdrawals
                (session_id, press_id, board_id, tick, request_id)
            VALUES (?, ?, ?, ?, ?)
        ''', (scope.session_id, press_id, scope.board_id, scope.tick, request_id))
        response['status'] = 'withdrawn'
    db.execute('''
        INSERT INTO correction_retractions(session_id, request_id, board_id, tick, press_id, response)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (scope.session_id, request_id, scope.board_id, scope.tick, press_id, json.dumps(response)))
    return response
