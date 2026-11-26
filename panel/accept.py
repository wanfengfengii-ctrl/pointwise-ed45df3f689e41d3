from contract import fail
from panel.delivery import queue_evidence
from panel.evidence import make_press_evidence
from panel.receipt import OperationReceipt, lookup_receipt, save_receipt
from panel.ticks import read_panel_tick, record_press


def touch(db, session_id, board_id, tick, request_id, resolve_board):
    original = lookup_receipt(db, session_id, request_id, original=('touch', board_id, tick))
    if original is not None:
        return original
    scope = resolve_board(session_id, board_id, tick)
    if read_panel_tick(db, scope).seal_id is not None:
        fail(409, 'panel_sealed', 'The board tick is sealed and cannot take a new press')
    delivery_id = queue_evidence(db, make_press_evidence(scope, request_id))
    record_press(db, scope, delivery_id)
    receipt = OperationReceipt(session_id, request_id, 'touch', board_id, tick, delivery_id)
    return save_receipt(db, receipt)
