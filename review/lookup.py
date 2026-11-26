from contract import fail, integer
from review.publish import publish_report, read_report


def report(db, payload):
    if payload.keys() == {'session_id'}:
        return publish_report(db, integer(payload['session_id'], 'session_id'))
    if payload.keys() == {'report_id'}:
        return read_report(db, integer(payload['report_id'], 'report_id')).payload()
    fail(400, 'invalid_report_selector', 'Supply exactly one of session_id and report_id')
