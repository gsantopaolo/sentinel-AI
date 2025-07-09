from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timedelta
import logging
import os
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()
readiness_time_out = int(os.getenv('READINESS_TIME_OUT', 500))


class ReadinessProbe:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(ReadinessProbe, cls).__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self):
        if not hasattr(self, 'initialized'):  # Ensure the logger is only initialized once
            self.logger = logging.getLogger(self.__class__.__name__)
            self.last_seen = datetime.utcnow()
            self.initialized = True

    def is_service_ready(self):
        # Check if the difference between the current time and last_seen is more than the readiness timeout
        if datetime.utcnow() - self.last_seen > timedelta(seconds=readiness_time_out):
            return False
        return True

    def update_last_seen(self):
        self.logger.debug("Readiness probe last seen being updated")
        self.last_seen = datetime.utcnow()

    class ReadinessProbeHandler(BaseHTTPRequestHandler):
        def __init__(self, *args, readiness_probe=None, **kwargs):
            self.logger = logging.getLogger(self.__class__.__name__)
            self.readiness_probe = readiness_probe
            super().__init__(*args, **kwargs)

        def do_GET(self):
            if self.path == '/healthz':
                if self.readiness_probe.is_service_ready():
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"OK")
                    self.logger.debug("/healthz response 200")
                else:
                    self.send_response(503)
                    self.end_headers()
                    self.wfile.write(b"Service Unavailable")
                    self.logger.error(f"❌ /healthz response 503 - this means the service didn't update_last_seen for "
                                      f"more than {readiness_time_out} seconds ")
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not Found")
                self.logger.debug('ReadinessProbeHandler GET /')

    def start_server(self):
        try:
            self.logger.info("Initializing readiness probe server")
            server_address = ('', 8080)
            httpd = HTTPServer(server_address,
                               lambda *args, **kwargs: self.ReadinessProbeHandler(*args, readiness_probe=self,
                                                                                  **kwargs))
            self.logger.info(f"Readiness probe server started on {server_address}8080")
            httpd.serve_forever()
        except Exception as e:
            self.logger.error(f"❌ Readiness probe failed to start: {e}")
