import http.server
import http.client
import json
import os
import sys

DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'frontend', 'dist')
PORT = 3000

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIST, **kwargs)

    def do_GET(self):
        if self.path.startswith('/api/') or self.path.startswith('/health') or self.path.startswith('/metrics'):
            try:
                conn = http.client.HTTPConnection('localhost', 3000)
                conn.request('GET', self.path, headers={'Host': 'localhost:3000'})
                resp = conn.getresponse()
                self.send_response(resp.status)
                for h in resp.getheaders():
                    if h[0].lower() not in ('transfer-encoding', 'connection'):
                        self.send_header(h[0], h[1])
                self.end_headers()
                self.wfile.write(resp.read())
                conn.close()
            except Exception as e:
                self.send_response(502)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())
        else:
            super().do_GET()

    def do_POST(self):
        if self.path.startswith('/api/') or self.path.startswith('/health'):
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length) if content_length else None
            try:
                conn = http.client.HTTPConnection('localhost', 3000)
                headers = {'Host': 'localhost:3000', 'Content-Type': 'application/json'}
                conn.request('POST', self.path, body=body, headers=headers)
                resp = conn.getresponse()
                self.send_response(resp.status)
                for h in resp.getheaders():
                    if h[0].lower() not in ('transfer-encoding', 'connection'):
                        self.send_header(h[0], h[1])
                self.end_headers()
                self.wfile.write(resp.read())
                conn.close()
            except Exception as e:
                self.send_response(502)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())
        else:
            self.send_response(405)
            self.end_headers()

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
        super().end_headers()

    def log_message(self, format, *args):
        pass

print(f'Serving {DIST} on port {PORT}')
sys.stdout.flush()
http.server.HTTPServer(('', PORT), Handler).serve_forever()
