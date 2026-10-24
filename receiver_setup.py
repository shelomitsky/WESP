"""Private loopback bridge for widget setup; passwords never enter shell argv."""
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading


class Bridge:
    def __init__(self, runtime, callback):
        import manage
        self.path=Path(runtime)/'receiver-setup.json'
        token=secrets.token_hex(32)
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):
                pass  # Request bodies and headers can contain credentials.

            def do_POST(self):
                self.connection.settimeout(5)
                if (self.path!='/setup' or not hmac.compare_digest(
                        self.headers.get('Authorization',''),'Bearer '+token)):
                    self.send_error(403)
                    return
                try:
                    size=int(self.headers.get('Content-Length','0'))
                    if not 0<size<=8192 or self.headers.get_content_type()!='application/json':
                        raise ValueError('Invalid setup request')
                    data=json.loads(self.rfile.read(size))
                    if not isinstance(data,dict):
                        raise ValueError('Invalid setup request')
                    result=dict(ok=True,receiver=callback(data))
                except Exception:
                    # Firmware/network exceptions may include request details;
                    # return a fixed public error, never repr(request/password).
                    result=dict(ok=False,error='Could not configure the receiver. Check the USB connection and settings.')
                body=json.dumps(result).encode()
                self.send_response(200)
                self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(body)))
                self.send_header('Cache-Control','no-store')
                self.end_headers()
                self.wfile.write(body)

        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.server.daemon_threads=False
        self.server.block_on_close=True
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        meta=dict(url='http://127.0.0.1:'+str(self.server.server_port)+'/setup',bearer=token)
        try:
            manage.atomic_write(self.path,json.dumps(meta).encode(),0o600)
        except Exception:
            self.server.shutdown()
            self.server.server_close()
            raise

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.path.unlink(missing_ok=True)
