"""
Load/replay harness for Occurrence Desk.
Owner: Sowmya — Queue, Autoscaling, Observability & Load

Simulates analysts submitting documents for parsing, hitting the real
upload-url -> complete flow against the live API. Used to measure
whether submit latency stays flat as load increases (the project's
core async-processing claim).

Usage:
    locust -f services/replay/locustfile.py --host http://127.0.0.1:8000
Then open http://localhost:8089 to configure users and start the test.
"""
import hashlib
import random
import string
from locust import HttpUser, task, between


class AnalystUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        """Log in once per simulated user before sending traffic."""
        response = self.client.post(
            "/api/v1/auth/login",
            json={"email": "analyst@occdesk.example", "password": "occdesk-local"},
        )
        if response.status_code == 200:
            token = response.json().get("access_token") or response.json().get("token")
            self.client.headers.update({"Authorization": f"Bearer {token}"})

    @task
    def submit_document(self):
        """Reserve a document row (upload-url) — this is the endpoint
        whose latency must stay flat at p95 under load, per the project's
        success criteria."""
        fake_bytes = "".join(random.choices(string.ascii_letters, k=64)).encode()
        fake_sha256 = hashlib.sha256(fake_bytes).hexdigest()

        self.client.post(
            "/api/v1/documents/upload-url",
            json={
                "filename": "replay-test.pdf",
                "byte_size": 184320,
                "sha256": fake_sha256,
            },
            name="/api/v1/documents/upload-url",
        )
