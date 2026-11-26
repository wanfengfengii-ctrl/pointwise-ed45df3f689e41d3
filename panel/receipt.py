from dataclasses import asdict, dataclass

from contract import fail


@dataclass(frozen=True)
class OperationReceipt:
    session_id: int
    request_id: str
    operation: str
    board_id: str
    tick: int
    delivery_id: str

    def payload(self):
        status = 'accepted' if self.operation == 'touch' else 'sealed'
        return {**asdict(self), 'status': status}


def init_receipt_schema(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS panel_receipts (
            session_id INTEGER NOT NULL,
            request_id TEXT NOT NULL,
            operation TEXT NOT NULL CHECK (operation IN ('touch', 'seal')),
            board_id TEXT NOT NULL,
            tick INTEGER NOT NULL,
            delivery_id TEXT NOT NULL REFERENCES deliveries(delivery_id),
            PRIMARY KEY (session_id, request_id)
        )
    ''')


def lookup_receipt(db, session_id, request_id, *, original=None):
    row = db.execute('''
        SELECT session_id, request_id, operation, board_id, tick, delivery_id
        FROM panel_receipts WHERE session_id = ? AND request_id = ?
    ''', (session_id, request_id)).fetchone()
    if row is None:
        return None
    receipt = OperationReceipt(**dict(row))
    if original is not None and original != (receipt.operation, receipt.board_id, receipt.tick):
        fail(409, 'request_conflict', 'That request identifier was used with a different operation or board tick')
    return receipt


def save_receipt(db, receipt: OperationReceipt):
    db.execute('''
        INSERT INTO panel_receipts(session_id, request_id, operation, board_id, tick, delivery_id)
        VALUES (:session_id, :request_id, :operation, :board_id, :tick, :delivery_id)
    ''', asdict(receipt))
    return receipt
