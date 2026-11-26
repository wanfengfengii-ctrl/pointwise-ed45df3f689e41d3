import json

from contract import fail
from panel.evidence import PressEvidence, SealEvidence


def init_delivery_schema(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS deliveries (
            delivery_id TEXT PRIMARY KEY,
            payload TEXT NOT NULL
        )
    ''')


def queue_evidence(db, evidence: PressEvidence | SealEvidence):
    db.execute(
        'INSERT INTO deliveries(delivery_id, payload) VALUES (?, ?)',
        (evidence.event_id, json.dumps(evidence.payload())),
    )
    return evidence.event_id


def read_delivery(db, delivery_id):
    row = db.execute('SELECT payload FROM deliveries WHERE delivery_id = ?', (delivery_id,)).fetchone()
    if row is None:
        fail(404, 'unknown_delivery', 'No delivery exists for that identifier')
    return json.loads(row['payload'])
