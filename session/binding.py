from dataclasses import dataclass

from contract import array, fail, fields, text
from program.release import IssuedShow


@dataclass(frozen=True)
class PanelBinding:
    board_id: str
    group_id: str
    position: str


def verify_bindings(show: IssuedShow, entries):
    expected = {
        board: group.group_id
        for group in show.draft.groups.values()
        for board in group.boards
    }
    bindings = {}
    positions = set()
    for entry in array(entries, 'bindings'):
        fields(entry, ('board_id', 'group_id', 'position'))
        board = text(entry['board_id'], 'board_id')
        group = text(entry['group_id'], 'group_id')
        position = text(entry['position'], 'position')
        if expected.get(board) != group or board in bindings or position in positions:
            fail(400, 'invalid_binding', 'Each board needs its show group and a distinct physical position')
        bindings[board] = PanelBinding(board, group, position)
        positions.add(position)
    if bindings.keys() != expected.keys():
        fail(400, 'invalid_binding', f'Missing boards {sorted(expected.keys() - bindings.keys())}')
    return bindings
