import logging
import requests
import os
import json
from datetime import datetime

# ————— Configuration & Logging —————
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format=os.getenv("LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
)
logger = logging.getLogger("sentinel-tester")

BASE = os.getenv("API_BASE_URL", "http://localhost:8000")

# ————— Helper Function —————
def call_api(method: str, path: str, payload=None):
    url = f"{BASE}{path}"
    logger.info(f"📱 {method} {path}")
    try:
        resp = requests.request(method, url, json=payload, timeout=5)
        status = resp.status_code
        if 200 <= status < 300:
            logger.info(f"🗄️ {method} {path} -> {status}")
        elif 400 <= status < 500:
            logger.warning(f"⚠️ {method} {path} -> {status}: {resp.text}")
        else:
            logger.error(f"❌ {method} {path} -> {status}: {resp.text}")
        return resp
    except requests.RequestException as e:
        logger.error(f"❌ Error calling {method} {path}: {e}")
        return None

# ————— Test Sequence —————
if __name__ == "__main__":
    # 1. Ingest
    events = [
        {
            "id": "evt-001",
            "source": "tester",
            "title": "Test Event",
            "body": "This is a test.",
            "published_at": datetime.utcnow().isoformat() + "Z"
        }
    ]
    call_api("POST", "/ingest", events)

    # 2. List sources (should be empty or existing)
    list_resp = call_api("GET", "/sources")
    sources = list_resp.json() if list_resp and list_resp.ok else []

    # 3. Create Source
    payload = {
        "name": "test-source",
        "url": "https://example.com",
        "title": "Example Title",
        "body": "Example body",
        "published_at": datetime.utcnow().isoformat() + "Z"
    }
    create_resp = call_api("POST", "/sources", payload)
    new_id = create_resp.json().get("id") if create_resp and create_resp.ok else None

    # 4. Get by ID
    if new_id:
        call_api("GET", f"/sources/{new_id}")

        # 5. Update
        upd_payload = {
            "name": "test-source-upd",
            "url": "https://example.org",
            "title": "Updated Title",
            "body": "Updated body",
            "published_at": datetime.utcnow().isoformat() + "Z",
            "is_active": False
        }
        call_api("PUT", f"/sources/{new_id}", upd_payload)

        # 6. Delete
        call_api("DELETE", f"/sources/{new_id}")

        # 7. Confirm deletion
        call_api("GET", f"/sources/{new_id}")
    else:
        logger.error("❌ Could not create source; aborting further tests.")
