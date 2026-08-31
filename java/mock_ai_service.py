"""
Mock Python AI Service for local testing of Spring Boot FIFO poller and invoice trigger.
Listens on http://localhost:8000
"""

import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse
import json
from datetime import datetime

PORT = 8000

class MockAiHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status": "UP", "service": "Mock Python AI Service"}')
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == '/extract/invoice':
            content_length = int(self.headers.get('Content-Length', 0))
            post_body = self.rfile.read(content_length).decode('utf-8')
            
            # Parse form-urlencoded body (e.g. document_id=uuid)
            parsed_data = urllib.parse.parse_qs(post_body)
            document_id = parsed_data.get('document_id', [None])[0]

            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"\n[{timestamp}] ========================================================", flush=True)
            print(f"[MOCK AI SERVICE] INVOICE TRIGGER RECEIVED!", flush=True)
            print(f"   Endpoint:    POST /extract/invoice", flush=True)
            print(f"   Document ID: {document_id}", flush=True)
            print(f"   Raw Body:    {post_body}", flush=True)
            print(f"========================================================================\n", flush=True)

            # Return 200 OK
            response_payload = {
                "status": "PROCESSING",
                "message": "Document accepted for asynchronous AI extraction.",
                "document_id": document_id,
                "timestamp": timestamp
            }

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response_payload).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error": "Endpoint not found"}')

    def log_message(self, format, *args):
        # Override to keep logs clean
        sys.stderr.write(f"[HTTP] {self.address_string()} - {format % args}\n")

def run():
    server_address = ('', PORT)
    httpd = HTTPServer(server_address, MockAiHandler)
    print(f"*** Mock Python AI Service running on http://localhost:{PORT} ***", flush=True)
    print(f"    Waiting for triggers at POST http://localhost:{PORT}/extract/invoice ...\n", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down Mock Python AI Service.")
        httpd.server_close()

if __name__ == '__main__':
    run()

