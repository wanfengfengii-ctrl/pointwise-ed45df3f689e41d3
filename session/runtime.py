import argparse
import json
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from contract import ServiceError, fail, fields, integer, text
from narration.decide import settle_group_tick
from narration.facts import init_narration_facts_schema
from narration.intake import receive
from narration.lookup import inspect
from narration.playback import init_playback_schema, read_started_plays
from panel.accept import touch
from panel.delivery import init_delivery_schema, read_delivery
from panel.evidence import decode_evidence
from panel.receipt import init_receipt_schema, lookup_receipt
from panel.seal import seal
from panel.ticks import init_panel_schema
from program.release import init_program_schema, issue, load_show
from review.lookup import report
from review.publish import init_review_schema
from session.clock import open_tick
from session.closing import close_session
from session.opening import init_session_schema, open_session, read_session
from session.scope import GroupTick, resolve_board_tick


@dataclass(frozen=True)
class Stores:
    venue: Path
    panels: Path


_VENUE_SCHEMA = (init_program_schema, init_session_schema, init_narration_facts_schema,
                 init_playback_schema, init_review_schema)
_PANEL_SCHEMA = (init_delivery_schema, init_panel_schema, init_receipt_schema)
_MAX_BODY = 1_048_576
_POST = frozenset(('issue', 'open', 'tick', 'touch', 'seal', 'receive', 'close', 'report'))
_GET = frozenset(('show', 'session', 'receipt', 'delivery', 'inspect', 'plays'))
_NUMERIC = frozenset(('show_id', 'session_id', 'report_id', 'tick'))


def _connect(path):
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys = ON')
    return db


def initialize(database):
    venue = Path(database).resolve()
    stores = Stores(venue, venue.with_name(venue.name + '.panels'))
    for path, schemas in ((stores.venue, _VENUE_SCHEMA), (stores.panels, _PANEL_SCHEMA)):
        with closing(_connect(path)) as db, db:
            for init_schema in schemas:
                init_schema(db)
    return stores


@contextmanager
def _transaction(path, *, write=False):
    with closing(_connect(path)) as db, db:
        db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
        yield db


def _panel_operation(stores, action, payload):
    fields(payload, ('session_id', 'board_id', 'tick', 'request_id'))
    session_id = integer(payload['session_id'], 'session_id')
    board_id = text(payload['board_id'], 'board_id')
    tick = integer(payload['tick'], 'tick')
    request_id = text(payload['request_id'], 'request_id')

    def resolve(session_id, board_id, tick):
        with _transaction(stores.venue) as db:
            return resolve_board_tick(db, session_id, board_id, tick)

    operation = touch if action == 'touch' else seal
    with _transaction(stores.panels, write=True) as db:
        return operation(db, session_id, board_id, tick, request_id, resolve).payload()


def _panel_query(stores, action, payload):
    with _transaction(stores.panels) as db:
        if action == 'delivery':
            fields(payload, ('delivery_id',))
            return read_delivery(db, text(payload['delivery_id'], 'delivery_id'))
        fields(payload, ('session_id', 'request_id'))
        session_id = integer(payload['session_id'], 'session_id')
        receipt = lookup_receipt(db, session_id, text(payload['request_id'], 'request_id'))
        if receipt is None:
            fail(404, 'unknown_receipt', 'No receipt exists for that request in the session')
        return receipt.payload()


def _verified_delivery(stores, payload):
    fields(payload, ('evidence',))
    evidence = decode_evidence(payload['evidence'])
    with _transaction(stores.panels) as db:
        try:
            issued = read_delivery(db, evidence.event_id)
        except ServiceError as error:
            if error.code != 'unknown_delivery':
                raise
            fail(409, 'evidence_conflict', 'The delivery identifier was never issued')
    if issued != evidence.payload():
        fail(409, 'evidence_conflict', 'The body differs from the issued delivery')
    return evidence


def _venue_operation(db, action, payload):
    if action == 'issue':
        return issue(db, payload).payload()
    if action == 'open':
        fields(payload, ('show_id', 'bindings'))
        return open_session(db, integer(payload['show_id'], 'show_id'), payload['bindings']).payload()
    if action == 'show':
        fields(payload, ('show_id',))
        return load_show(db, integer(payload['show_id'], 'show_id')).payload()
    if action == 'report':
        return report(db, payload)
    required = {'tick': ('tick',), 'inspect': ('group_id', 'tick')}.get(action, ())
    fields(payload, ('session_id', *required))
    session_id = integer(payload['session_id'], 'session_id')
    if action == 'session':
        return read_session(db, session_id).payload()
    if action == 'close':
        return close_session(db, session_id).payload()
    if action == 'plays':
        read_session(db, session_id)
        return {'session_id': session_id, 'starts': [play.payload() for play in read_started_plays(db, session_id)]}
    tick = integer(payload['tick'], 'tick')
    if action == 'inspect':
        return inspect(db, session_id, text(payload['group_id'], 'group_id'), tick)
    session = open_tick(db, session_id, tick)
    show = load_show(db, session.show_id)
    for group in show.draft.groups.values():
        settle_group_tick(db, GroupTick(session, show, group, tick))
    return {'session_id': session_id, 'tick': tick}


def handle_request(stores: Stores, action: str, payload):
    if action not in _GET and action not in _POST:
        fail(404, 'unknown_route', 'Unknown gallery operation')
    if not isinstance(payload, dict):
        fail(400, 'invalid_shape', 'Expected a JSON object')
    if action in ('touch', 'seal'):
        return _panel_operation(stores, action, payload)
    if action in ('receipt', 'delivery'):
        return _panel_query(stores, action, payload)
    if action == 'receive':
        evidence = _verified_delivery(stores, payload)
        with _transaction(stores.venue, write=True) as db:
            return receive(db, evidence)
    with _transaction(stores.venue, write=action in _POST) as db:
        return _venue_operation(db, action, payload)


def _query_payload(query):
    try:
        pairs = parse_qsl(query, keep_blank_values=True, strict_parsing=True, errors='strict', max_num_fields=12)
    except (ValueError, UnicodeError):
        fail(400, 'invalid_query', 'Malformed query parameters')
    result = {}
    for key, value in pairs:
        if key in result:
            fail(400, 'invalid_query', f'Repeated query parameter {key}')
        if key in _NUMERIC:
            if not value or len(value) > 19 or not value.isascii() or not value.isdecimal():
                fail(400, 'invalid_query', f'{key} must be a decimal integer')
            value = int(value)
        result[key] = value
    return result


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            fail(400, 'invalid_json', f'Duplicate JSON key {key}')
        result[key] = value
    return result


class _Handler(BaseHTTPRequestHandler):
    def _send(self, status, payload):
        body = json.dumps(payload, ensure_ascii=True).encode('ascii')
        try:
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def _body(self):
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            fail(400, 'invalid_length', 'Invalid Content-Length')
        if not 0 < length <= _MAX_BODY:
            fail(400, 'invalid_length', 'Send a JSON body of at most 1 MiB')
        try:
            return json.loads(self.rfile.read(length).decode('utf-8'), object_pairs_hook=_unique_object)
        except (ValueError, UnicodeError, RecursionError):
            fail(400, 'invalid_json', 'Malformed UTF-8 JSON body')

    def _dispatch(self, method):
        try:
            try:
                target = urlsplit(self.path)
            except ValueError:
                fail(400, 'invalid_query', 'Malformed request target')
            action = target.path.removeprefix('/')
            allowed = _GET if method == 'GET' else _POST
            if action not in allowed:
                if action in _GET or action in _POST:
                    self.send_header_for_method_error(action)
                    return
                fail(404, 'unknown_route', 'Unknown gallery operation')
            if method == 'POST' and target.query:
                fail(400, 'invalid_query', 'POST arguments belong in the JSON body')
            payload = _query_payload(target.query) if method == 'GET' else self._body()
            response = handle_request(self.server.stores, action, payload)
        except ServiceError as error:
            self._send(error.status, {'error': error.code, 'message': str(error)})
        except sqlite3.Error:
            self.log_error('SQLite failed while handling %s', self.path)
            self._send(503, {'error': 'storage_failure', 'message': 'The storage operation could not complete'})
        else:
            self._send(200, response)

    def send_header_for_method_error(self, action):
        method = 'GET' if action in _GET else 'POST'
        self._send(405, {'error': 'method_not_allowed', 'message': f'Use {method} for this operation'})

    def do_GET(self):
        self._dispatch('GET')

    def do_POST(self):
        self._dispatch('POST')

    def log_message(self, format, *args):
        pass


class _GalleryServer(ThreadingHTTPServer):
    def __init__(self, address, stores):
        self.stores = stores
        super().__init__(address, _Handler)


def create_server(database, port=0):
    return _GalleryServer(('127.0.0.1', port), initialize(database))


def main():
    parser = argparse.ArgumentParser(description='Run the local touch gallery JSON service')
    parser.add_argument('--db', required=True, help='SQLite path for the venue')
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()
    with create_server(args.db, args.port) as server:
        print(f'Listening on http://127.0.0.1:{server.server_port}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            return


if __name__ == '__main__':
    main()
