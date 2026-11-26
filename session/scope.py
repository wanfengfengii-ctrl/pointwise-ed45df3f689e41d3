from dataclasses import dataclass

from contract import fail
from program.release import IssuedShow, load_show
from program.rules import GroupRules
from session.clock import is_opened_tick
from session.opening import SessionRecord, read_session


@dataclass(frozen=True)
class BoardTick:
    session_id: int
    board_id: str
    tick: int
    group_id: str
    position: str

    def key(self):
        return self.session_id, self.board_id, self.tick


@dataclass(frozen=True)
class GroupTick:
    session: SessionRecord
    show: IssuedShow
    group: GroupRules
    tick: int

    def key(self):
        return self.session.session_id, self.group.group_id, self.tick


def _opened_session(db, session_id, tick):
    session = read_session(db, session_id)
    if not is_opened_tick(session, tick):
        fail(409, 'tick_not_open', f'Tick {tick} was not opened in session {session_id}')
    return session


def resolve_board_tick(db, session_id, board_id, tick):
    session = _opened_session(db, session_id, tick)
    binding = session.bindings.get(board_id)
    if binding is None:
        fail(404, 'unknown_board', f'Board {board_id} is not bound in this session')
    return BoardTick(session_id, board_id, tick, binding.group_id, binding.position)


def resolve_group_tick(db, session_id, group_id, tick):
    session = _opened_session(db, session_id, tick)
    show = load_show(db, session.show_id)
    group = show.draft.groups.get(group_id)
    if group is None:
        fail(404, 'unknown_group', f'Group {group_id} does not belong to this session')
    return GroupTick(session, show, group, tick)
