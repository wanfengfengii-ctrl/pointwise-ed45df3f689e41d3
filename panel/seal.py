from panel.delivery import queue_evidence
from panel.evidence import make_seal_evidence
from panel.receipt import OperationReceipt, lookup_receipt, save_receipt
from panel.ticks import read_panel_tick, record_seal


def seal(db, session_id, board_id, tick, request_id, resolve_board):
    original = lookup_receipt(db, session_id, request_id, original=('seal', board_id, tick))
    if original is not None:
        return original
    scope = resolve_board(session_id, board_id, tick)
    state = read_panel_tick(db, scope)
    delivery_id = state.seal_id
    if delivery_id is None:
        delivery_id = queue_evidence(db, make_seal_evidence(scope, request_id, state.press_ids))
        record_seal(db, scope, delivery_id)
    receipt = OperationReceipt(session_id, request_id, 'seal', board_id, tick, delivery_id)
    return save_receipt(db, receipt)
