import http.client
import json
from pathlib import Path
import socket
import tempfile
import threading
import unittest

from laboratorio.web_store import Store
from laboratorio.web_app import make_server


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name).resolve() / 'app')
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.store.close)
        self.server = make_server(self.store, 0)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.addCleanup(self.stop)
        self.port = self.server.server_address[1]
        self.host = f'127.0.0.1:{self.port}'
        self.origin = 'http://' + self.host
        status, body, headers = self.request('GET', '/api/bootstrap', token=False)
        self.assertEqual(status, 200)
        self.token = body['result']['csrf_token']
        self.assertIn("script-src 'self'", headers['Content-Security-Policy'])

    def stop(self):
        self.server.shutdown()
        self.thread.join(3)
        self.server.server_close()

    def request(self, method, path, body=None, token=True, headers=None):
        h = {'Host': self.host, 'Origin': self.origin, 'Content-Type': 'application/json'}
        if token: h['X-App-Token'] = self.token
        if headers: h.update(headers)
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        try:
            c.request(method, path, body=body, headers=h)
            r = c.getresponse()
            return r.status, json.loads(r.read()), dict(r.getheaders())
        finally: c.close()

    def test_flows(self):
        status, body, _ = self.request('POST', '/api/catalog', '{"seed":17,"per_family":1}')
        self.assertEqual(status, 200)
        cases = body['result']['cases']
        status, body, _ = self.request('POST', '/api/evaluations', json.dumps({'name': 'HTTP', 'cases': cases, 'responses': []}))
        self.assertEqual(status, 200)
        identifier = body['result']['id']
        status, body, _ = self.request('GET', '/api/export?kind=experiment&id=' + identifier)
        self.assertEqual(status, 200)
        self.assertEqual(body['result']['records'][0]['manifest']['state'], 'AVAILABLE')

    def test_boundaries(self):
        for headers in ({'Host': 'localhost:' + str(self.port)}, {'Origin': 'https://evil.test'},
                        {'X-App-Token': 'wrong'}, {'Content-Type': 'text/plain'},
                        {'Content-Length': '2000001'}, {'Transfer-Encoding': 'chunked'}):
            status, _, _ = self.request('POST', '/api/catalog', '{}', headers=headers)
            self.assertIn(status, (400, 403, 413))
        for body in ('{"seed":NaN,"per_family":1}', '{"seed":1,"seed":2,"per_family":1}', b'\xff'):
            self.assertEqual(self.request('POST', '/api/catalog', body)[0], 400)
        self.assertEqual(self.request('GET', '/api/state', token=False)[0], 403)
        for path in ('/api/nope', '/api/%73tate', '/../../etc/passwd'):
            self.assertEqual(self.request('GET', path)[0], 404)
        self.assertEqual(self.request('GET', '/api/export?kind=evaluation&id=' + '0'*32)[0], 404)
        self.assertEqual(self.request('GET', '/api/bootstrap?token=secret', token=False)[0], 400)
        self.assertEqual(self.request('POST', '/api/demo', '{"path":"/tmp"}')[0], 400)

    def test_duplicate_length_and_host(self):
        for extra in ('Content-Length: 2\r\nContent-Length: 2', 'Host: evil\r\nContent-Length: 2'):
            raw = (f'POST /api/demo HTTP/1.0\r\nHost: {self.host}\r\nOrigin: {self.origin}\r\nX-App-Token: {self.token}\r\nContent-Type: application/json\r\n{extra}\r\n\r\n{{}}').encode()
            with socket.create_connection(('127.0.0.1', self.port), timeout=5) as s:
                s.sendall(raw)
                response = s.recv(8192)
            self.assertIn(response.split(b' ')[1], (b'400', b'403'))



class WireTests(unittest.TestCase):
    """Real HTTP parser and Store over a local socketpair; no bind or mocks."""
    def test_wire_validation_and_real_catalog(self):
        from types import SimpleNamespace
        from laboratorio.web_app import Handler
        with tempfile.TemporaryDirectory() as temp:
            with Store(Path(temp).resolve() / 'app') as store:
                server = SimpleNamespace(store=store, host='127.0.0.1:12345',
                    origin='http://127.0.0.1:12345', token='session-token')
                def exchange(tail, body=b'{}', path='/api/catalog'):
                    a, b = socket.socketpair()
                    thread = threading.Thread(target=lambda: Handler(a, ('127.0.0.1', 1), server))
                    thread.start()
                    raw = (f'POST {path} HTTP/1.0\r\nHost: {server.host}\r\nOrigin: {server.origin}\r\nX-App-Token: session-token\r\nContent-Type: application/json\r\n' + tail + '\r\n\r\n').encode() + body
                    b.settimeout(6)
                    b.sendall(raw)
                    b.shutdown(socket.SHUT_WR)
                    chunks = []
                    while True:
                        part = b.recv(65536)
                        if not part: break
                        chunks.append(part)
                        if b'\r\n\r\n' in b''.join(chunks):
                            head, payload = b''.join(chunks).split(b'\r\n\r\n', 1)
                            size = int(next(line.split(b':')[1] for line in head.split(b'\r\n') if line.startswith(b'Content-Length:')))
                            if len(payload) == size: break
                    thread.join(6)
                    a.close(); b.close()
                    head, payload = b''.join(chunks).split(b'\r\n\r\n', 1)
                    return int(head.split(b' ')[1]), json.loads(payload)
                body = b'{"seed":17,"per_family":1}'
                status, payload = exchange(f'Content-Length: {len(body)}', body)
                self.assertEqual(status, 200)
                self.assertEqual(len(payload['result']['cases']), 5)
                for tail, body, expected in [
                    ('Content-Length: 2\r\nContent-Length: 2', b'{}', 400),
                    ('Content-Length: 2000001', b'{}', 413),
                    ('Content-Length: 4', b'{}', 400),
                    ('Transfer-Encoding: chunked', b'{}', 400),
                    ('Content-Length: 1', b'\xff', 400),
                    ('Content-Length: 2\r\nHost: evil', b'{}', 403),
                    ('Content-Length: 2\r\nOrigin: https://evil.test', b'{}', 403),
                    ('Content-Length: 2\r\nX-App-Token: other', b'{}', 403)]:
                    self.assertEqual(exchange(tail, body)[0], expected)
                self.assertEqual(exchange('Content-Length: 2', path='/api/unknown')[0], 404)

if __name__ == '__main__': unittest.main()
