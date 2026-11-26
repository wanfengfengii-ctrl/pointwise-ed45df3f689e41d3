from dataclasses import asdict, dataclass

from contract import fail
from session.opening import read_session


@dataclass(frozen=True)
class ClosedRange:
    session_id: int
    last_tick: int

    def ticks(self):
        return range(1, self.last_tick + 1)

    def payload(self):
        return asdict(self)


def close_session(db, session_id):
    session = read_session(db, session_id)
    if session.closed_tick is not None:
        return ClosedRange(session_id, session.closed_tick)
    db.execute('UPDATE sessions SET closed_tick = last_tick WHERE session_id = ?', (session_id,))
    return ClosedRange(session_id, session.last_tick)


def read_closed_range(db, session_id):
    session = read_session(db, session_id)
    if session.closed_tick is None:
        fail(409, 'session_not_closed', 'Close the session before publishing its report')
    return ClosedRange(session_id, session.closed_tick)
