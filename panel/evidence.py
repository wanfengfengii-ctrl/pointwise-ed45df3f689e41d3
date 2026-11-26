import hashlib
import json
from dataclasses import dataclass

from contract import array, fail, fields, integer, text
from session.scope import BoardTick


@dataclass(frozen=True)
class PressEvidence:
    event_id: str
    session_id: int
    board_id: str
    tick: int
    request_id: str

    def payload(self):
        return {
            'kind': 'press', 'event_id': self.event_id, 'session_id': self.session_id,
            'board_id': self.board_id, 'tick': self.tick, 'request_id': self.request_id,
        }


@dataclass(frozen=True)
class SealEvidence:
    event_id: str
    session_id: int
    board_id: str
    tick: int
    press_ids: tuple[str, ...]

    def payload(self):
        return {
            'kind': 'seal', 'event_id': self.event_id, 'session_id': self.session_id,
            'board_id': self.board_id, 'tick': self.tick, 'press_ids': list(self.press_ids),
        }


def _event_id(kind, scope, request_id):
    identity = json.dumps((kind, *scope.key(), request_id), separators=(',', ':')).encode('ascii')
    return hashlib.sha256(identity).hexdigest()


def make_press_evidence(scope: BoardTick, request_id: str):
    return PressEvidence(_event_id('press', scope, request_id), *scope.key(), request_id)


def make_seal_evidence(scope: BoardTick, request_id: str, press_ids):
    return SealEvidence(_event_id('seal', scope, request_id), *scope.key(), tuple(press_ids))


def decode_evidence(value):
    if not isinstance(value, dict):
        fail(400, 'invalid_evidence', 'Expected an evidence object')
    kind = value.get('kind')
    common = ('kind', 'event_id', 'session_id', 'board_id', 'tick')
    if kind == 'press':
        fields(value, (*common, 'request_id'))
    elif kind == 'seal':
        fields(value, (*common, 'press_ids'))
    else:
        fail(400, 'invalid_evidence', 'Evidence kind must be press or seal')
    identity = (
        text(value['event_id'], 'event_id'), integer(value['session_id'], 'session_id'),
        text(value['board_id'], 'board_id'), integer(value['tick'], 'tick'),
    )
    if kind == 'press':
        return PressEvidence(*identity, text(value['request_id'], 'request_id'))
    press_ids = tuple(text(ref, 'press_ids') for ref in array(value['press_ids'], 'press_ids'))
    if len(set(press_ids)) != len(press_ids) or identity[0] in press_ids:
        fail(400, 'invalid_evidence', 'A seal must list distinct press references')
    return SealEvidence(*identity, press_ids)
