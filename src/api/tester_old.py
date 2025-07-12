import logging
import requests
import os

# ————— Configuration & Logging —————
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format=os.getenv(
        "LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    ),
)
logger = logging.getLogger("sentinel-tester")

BASE = os.getenv("API_BASE_URL", "http://localhost:8000")

# ————— Helper Function —————
def call_api(method: str, path: str, payload: dict = None):
    url = f"{BASE}{path}"
    logger.info(f"📱 {method} {path}")
    try:
        response = requests.request(method, url, json=payload, timeout=5)
        status = response.status_code
        if 200 <= status < 300:
            logger.info(f"🗄️ Received {status} from {method} {path}")
        elif 400 <= status < 500:
            logger.warning(f"⚠️ {method} {path} returned client error {status}: {response.text}")
        else:
            logger.error(f"❌ {method} {path} returned server error {status}: {response.text}")
        return response
    except requests.RequestException as e:
        logger.error(f"❌ Error calling {method} {path}: {e}")
        return None

# ————— Test Sequence —————
if __name__ == "__main__":
    # 1. List (should be empty)
    call_api("GET", "/sources")

    # 2. Create
    payload = {"name": "foo", "type": "bar", "config": {"a": 1}}
    create_resp = call_api("POST", "/sources", payload)
    new_id = None
    if create_resp and create_resp.ok:
        new_id = create_resp.json().get("id")

    # 3. Get by ID
    if new_id:
        call_api("GET", f"/sources/{new_id}")

        # 4. Update
        upd_payload = {"name": "foo2", "type": "bar2", "config": {"b": 2}}
        call_api("PUT", f"/sources/{new_id}", upd_payload)

        # 5. Delete
        call_api("DELETE", f"/sources/{new_id}")

        # 6. Confirm gone
        call_api("GET", f"/sources/{new_id}")
    else:
        logger.error("❌ Failed to create source; aborting subsequent tests.")
