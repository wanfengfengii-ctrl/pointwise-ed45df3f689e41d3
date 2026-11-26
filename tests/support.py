import json
import unittest
from contextlib import contextmanager
from http.client import HTTPConnection, RemoteDisconnected
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.parse import urlencode

from session.runtime import create_server


class RejectedRequest(Exception):
    def __init__(self, status, payload):
        super().__init__(f'HTTP {status}: {payload}')
        self.status = status
        self.code = payload['error']


class Client:
    def __init__(self, host, port):
        self.host, self.port = host, port

    def _request(self, method, path, payload=None):
        connection = HTTPConnection(self.host, self.port, timeout=10)
        try:
            body = None if payload is None else json.dumps(payload).encode('ascii')
            headers = {} if body is None else {'Content-Type': 'application/json'}
            connection.request(method, path, body, headers)
            response = connection.getresponse()
            result = json.loads(response.read())
            if response.status != 200:
                raise RejectedRequest(response.status, result)
            return result
        finally:
            connection.close()

    def get(self, action, **query):
        return self._request('GET', '/' + action + '?' + urlencode(query))

    def post(self, action, **payload):
        return self._request('POST', '/' + action, payload)

    def deliver(self, receipt):
        evidence = self.get('delivery', delivery_id=receipt['delivery_id'])
        return self.post('receive', evidence=evidence)


@contextmanager
def _running(server):
    with server:
        thread = Thread(target=server.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True)
        thread.start()
        try:
            yield Client(*server.server_address)
        finally:
            server.shutdown()
            thread.join()


class LocalGallery:
    def __init__(self, database):
        self.database = database
        self.running = None
        self.client = None

    def __enter__(self):
        self.running = _running(create_server(self.database))
        self.client = self.running.__enter__()
        return self

    def __exit__(self, *exc):
        if self.running is not None:
            running, self.running = self.running, None
            self.client = None
            running.__exit__(*exc)

    def restart(self):
        self.__exit__(None, None, None)
        self.__enter__()

    def lose_reply(self, action, **payload):
        upstream = self.client
        committed = []

        class Relay(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                committed.append(upstream.post(self.path.removeprefix('/'), **body))
                self.close_connection = True

        with _running(HTTPServer(('127.0.0.1', 0), Relay)) as relay:
            try:
                relay.post(action, **payload)
            except RemoteDisconnected:
                if len(committed) == 1:
                    return committed[0]
                raise AssertionError('Relay disconnected without observing an upstream commit')
        raise AssertionError('The client received a response which should have been lost')


def gallery_input(*groups):
    sample = Path(__file__).resolve().parents[1] / 'examples' / 'gallery.json'
    data = json.loads(sample.read_text(encoding='utf-8'))
    if groups:
        data['show']['groups'] = [group for group in data['show']['groups'] if group['group_id'] in groups]
        data['bindings'] = [entry for entry in data['bindings'] if entry['group_id'] in groups]
    return data


def open_gallery(client, data):
    show = client.post('issue', **data['show'])
    return client.post('open', show_id=show['show_id'], bindings=data['bindings'])


def panel_operation(client, operation, session_id, board, tick, request):
    return client.post(operation, session_id=session_id, board_id=board, tick=tick, request_id=request)


class GalleryTest(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.gallery = self.enterContext(LocalGallery(Path(directory) / 'gallery.sqlite3'))

    @property
    def client(self):
        return self.gallery.client

    def open_gallery(self, *groups):
        return open_gallery(self.client, gallery_input(*groups))['session_id']

    def rejected(self, code, action, *, method='post', status=409, **payload):
        with self.assertRaises(RejectedRequest) as caught:
            getattr(self.client, method)(action, **payload)
        self.assertEqual((caught.exception.status, caught.exception.code), (status, code))

    def tick(self, session_id, tick):
        result = self.client.post('tick', session_id=session_id, tick=tick)
        self.assertEqual(result, {'session_id': session_id, 'tick': tick})

    def panel(self, action, session, board, tick, request):
        return panel_operation(self.client, action, session, board, tick, request)

    def inspect(self, session, tick, group='atlas'):
        return self.client.get('inspect', session_id=session, group_id=group, tick=tick)

    def plays(self, session):
        return self.client.get('plays', session_id=session)['starts']

    def assert_sources(self, result, *receipts):
        positions = {'L': 'atlas-west', 'R': 'atlas-east', 'M': 'minerals-west', 'N': 'minerals-east'}
        expected = [
            {'session_id': item['session_id'], 'tick': item['tick'], 'board_id': item['board_id'],
             'request_id': item['request_id'], 'event_id': item['delivery_id'],
             'position': positions[item['board_id']]}
            for item in receipts
        ]
        self.assertEqual(result['sources'], expected)
