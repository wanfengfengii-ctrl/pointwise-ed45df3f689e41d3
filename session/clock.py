from dataclasses import replace

from contract import fail
from session.opening import SessionRecord, read_session


def open_tick(db, session_id, tick):
    session = read_session(db, session_id)
    if session.closed_tick is not None:
        fail(409, 'session_closed', 'A closed session cannot open a new tick')
    expected = session.last_tick + 1
    if tick != expected:
        fail(409, 'tick_out_of_sequence', f'Tick {expected} must open next')
    db.execute('UPDATE sessions SET last_tick = ? WHERE session_id = ?', (tick, session_id))
    return replace(session, last_tick=tick)


def is_opened_tick(session: SessionRecord, tick: int):
    return type(tick) is int and 1 <= tick <= session.last_tick
