"""Sequential loopback HTTP/1.0 application; no authority endpoints or CORS."""
import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib import resources
import io
import json
import re
import secrets
import socket
import sys
import time

from . import evaluation
from .web_store import Store, AppError, LIMITS

ASSETS = {'/': ('index.html', 'text/html; charset=utf-8'),
          '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
          '/style.css': ('style.css', 'text/css; charset=utf-8'),
          '/icon.svg': ('icon.svg', 'image/svg+xml')}
POSTS = {'/api/catalog': 'catalog', '/api/evaluations': 'evaluate',
         '/api/experiments/verify': 'verify_experiment', '/api/forecasts': 'forecast',
         '/api/resolutions': 'resolve', '/api/evidence': 'evidence',
         '/api/evidence/verify': 'verify_evidence', '/api/demo': 'demo'}
CSP = "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-src 'none'; frame-ancestors 'none'; form-action 'none'"


class DeadlineReader(io.RawIOBase):
    def __init__(self, connection):
        self.connection = connection
        self.deadline = time.monotonic() + 5

    def readable(self): return True

    def readinto(self, buffer):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0: raise TimeoutError()
        self.connection.settimeout(min(1.0, remaining))
        return self.connection.recv_into(buffer)


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'
    server_version = 'LocalApp'
    sys_version = ''

    def setup(self):
        self.request.settimeout(1)
        super().setup()
        self.rfile.close()
        self.rfile = io.BufferedReader(DeadlineReader(self.connection), buffer_size=8192)

    def log_message(self, *args): pass
    def log_error(self, *args): pass

    def handle(self):
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
            self.close_connection = True

    def _send(self, status, data, content_type='application/json; charset=utf-8'):
        self.close_connection = True
        self.send_response(status)
        for key, value in {'Content-Type': content_type, 'Content-Length': str(len(data)),
                           'Connection': 'close', 'Cache-Control': 'no-store',
                           'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
                           'Referrer-Policy': 'no-referrer', 'Content-Security-Policy': CSP}.items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != 'HEAD': self.wfile.write(data)

    def _json(self, status, payload):
        if status == 200 and self.path.partition('?')[0] == '/api/state':
            output = io.BytesIO()
            for part in json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(',', ':')).iterencode(payload):
                raw = part.encode('utf-8')
                if output.tell() + len(raw) > LIMITS['max_state_json_bytes']:
                    raise AppError(413, 'LIMIT', 'Estado demasiado grande.')
                output.write(raw)
            return self._send(status, output.getvalue())
        self._send(status, json.dumps(payload, ensure_ascii=False, allow_nan=False,
                                      separators=(',', ':')).encode('utf-8'))

    def _error(self, error):
        self._json(error.status, {'ok': False, 'error': {'code': error.code, 'message': error.message}})

    def send_error(self, code, message=None, explain=None):
        self._error(AppError(413 if code == 431 else 400, 'INVALID_REQUEST', 'Solicitud inválida.'))

    def _one(self, name):
        values = self.headers.get_all(name, [])
        return values[0] if len(values) == 1 else None

    def _security(self):
        if self._one('Host') != self.server.host:
            raise AppError(403, 'FORBIDDEN', 'Solicitud rechazada.')
        if self.headers.get_all('Transfer-Encoding'):
            raise AppError()
        lengths = self.headers.get_all('Content-Length', [])
        if len(lengths) > 1: raise AppError()
        if self.command == 'GET' and lengths and lengths != ['0']: raise AppError()
        route, separator, query = self.path.partition('?')
        if separator and route != '/api/export':
            if (route != '/api/state' or self.command != 'GET'
                    or re.fullmatch(r'offset=(0|[1-9][0-9]{0,2})', query) is None
                    or int(query[7:]) > 300): raise AppError()
        if route.startswith('/api/') and route != '/api/bootstrap':
            token = self._one('X-App-Token')
            if token is None or not secrets.compare_digest(token.encode(), self.server.token.encode()):
                raise AppError(403, 'FORBIDDEN', 'Solicitud rechazada.')
        if self.command == 'POST':
            if self._one('Origin') != self.server.origin:
                raise AppError(403, 'FORBIDDEN', 'Solicitud rechazada.')
            if self._one('Content-Type') != 'application/json': raise AppError()
        return route, query

    def _body(self):
        length = self._one('Content-Length')
        if length is None or re.fullmatch(r'[0-9]{1,10}', length) is None: raise AppError()
        count = int(length)
        if count > LIMITS['max_body_bytes']:
            raise AppError(413, 'LIMIT', 'Cuerpo demasiado grande.')
        try:
            raw = self.rfile.read(count)
            if len(raw) != count: raise AppError()
            return evaluation.loads_strict(raw.decode('utf-8', errors='strict'))
        except (ValueError, UnicodeError, TimeoutError):
            raise AppError() from None

    def _dispatch(self):
        route, query = self._security()
        if self.command == 'GET':
            if route == '/api/bootstrap':
                return {'csrf_token': self.server.token, 'version': '1', 'limits': dict(LIMITS)}
            if route == '/api/state': return self.server.store.state(offset=int(query[7:]) if query else 0)
            if route == '/api/export':
                # No unquoting, arbitrary paths, duplicate keys or token query parameters.
                match = re.fullmatch(r'kind=(evaluation|experiment|evidence|demo)&id=([a-f0-9]{32})', query)
                reverse = re.fullmatch(r'id=([a-f0-9]{32})&kind=(evaluation|experiment|evidence|demo)', query)
                if match: return self.server.store.export(match[1], match[2])
                if reverse: return self.server.store.export(reverse[2], reverse[1])
                raise AppError()
            if route in ASSETS:
                name, mime = ASSETS[route]
                try:
                    raw = resources.files('laboratorio').joinpath('web_assets', name).read_bytes()
                except (FileNotFoundError, ModuleNotFoundError):
                    raise AppError(404, 'ASSET_NOT_AVAILABLE', 'Recurso aún no disponible.') from None
                self._send(200, raw, mime)
                return _SENT
        elif self.command == 'POST' and route in POSTS:
            return getattr(self.server.store, POSTS[route])(self._body())
        raise AppError(404, 'NOT_FOUND', 'Recurso desconocido.')

    def _run(self):
        try:
            result = self._dispatch()
            if result is not _SENT: self._json(200, {'ok': True, 'result': result})
        except AppError as error:
            self._error(error)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            self.close_connection = True
        except Exception:
            self._error(AppError(500, 'INTERNAL_ERROR', 'Operación no confirmada.'))

    do_GET = do_POST = do_HEAD = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _run


_SENT = object()


class LocalServer(HTTPServer):
    request_queue_size = 5
    allow_reuse_address = False

    def handle_error(self, request, client_address): pass


def make_server(store, port=8765):
    if type(port) is not int or not 0 <= port <= 65535: raise AppError()
    server = LocalServer(('127.0.0.1', port), Handler)
    server.timeout = 0.5
    server.store = store
    server.token = secrets.token_urlsafe(32)
    server.host = f'127.0.0.1:{server.server_address[1]}'
    server.origin = 'http://' + server.host
    return server


class Parser(argparse.ArgumentParser):
    def error(self, message): self.exit(2, 'Argumentos inválidos.\n')


def main(argv=None):
    parser = Parser(description='Aplicación local; no autentica humanos.', allow_abbrev=False)
    parser.add_argument('--workspace', default='runs/app')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--operator-root')
    args = parser.parse_args(argv)
    try:
        with Store(args.workspace, operator_root=args.operator_root) as store:
            with make_server(store, args.port) as server:
                print(server.origin, flush=True)
                try: server.serve_forever(poll_interval=0.25)
                except KeyboardInterrupt: pass
        return 0
    except (AppError, OSError, ValueError):
        print('No se pudo iniciar la aplicación local.', file=sys.stderr)
        return 2


if __name__ == '__main__': raise SystemExit(main())
