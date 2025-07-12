import os
import json
import logging
import threading
import streamlit as st
import pandas as pd
import requests
from dotenv import load_dotenv
from src.lib_py.middlewares.readiness_probe import ReadinessProbe

# ————— Load Environment & Configure Logging —————
load_dotenv()
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FORMAT = os.getenv(
    "LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO), format=LOG_FORMAT)
logger = logging.getLogger("sentinel-web")

# ————— Configuration —————
BASE_URL = os.getenv("API_BASE_URL", "http://api:8000")
READINESS_TIME_OUT = int(os.getenv("WEB_READINESS_TIME_OUT", 500))

# ————— Readiness Probe on Startup —————
if "startup_done" not in st.session_state:
    logger.info("🛠️ Sentinel-AI Web UI starting...")
    probe = ReadinessProbe(readiness_time_out=READINESS_TIME_OUT)
    t = threading.Thread(target=probe.start_server, daemon=True)
    t.start()
    logger.info("✅ Readiness probe server started.")
    st.session_state.startup_done = True

# ————— Helper: API Call —————
def make_request(method: str, endpoint: str, data=None):
    url = f"{BASE_URL}{endpoint}"
    logger.info(f"📱 {method} {url}")
    try:
        resp = requests.request(method, url, json=data, timeout=5)
        resp.raise_for_status()
        logger.info(f"🗄️ {method} {endpoint} returned {resp.status_code}")
        return resp
    except requests.exceptions.RequestException as e:
        status = getattr(e.response, 'status_code', 'N/A')
        logger.error(f"❌ {method} {endpoint} error {status}: {e}")
        st.error(f"An error occurred: {e}")
        return None

# ————— Render Functions —————
def render_ingest():
    st.header("Ingest Data")
    default = [
        {"id":"evt-123","source":"manual","title":"Example","body":"...","published_at":"2025-07-10T10:00:00Z"}
    ]
    payload_str = st.text_area("JSON Array of Events", json.dumps(default, indent=2), height=200)
    if st.button("Ingest Data"):
        try:
            events = json.loads(payload_str)
            if not isinstance(events, list):
                st.error("Payload must be a JSON array of event objects.")
                return
            r = make_request("POST", "/ingest", events)
            if r:
                st.success(r.json().get("message", "ACK"))
        except json.JSONDecodeError:
            st.error("Invalid JSON payload.")


def render_retrieve():
    st.header("Retrieve Data")
    batch_id = st.text_input("Batch ID")
    if st.button("Retrieve"):
        if batch_id:
            r = make_request("GET", f"/retrieve?batch_id={batch_id}")
            if r: st.json(r.json())
        else:
            st.warning("Please enter a Batch ID.")


def render_news(endpoint: str, title: str):
    st.header(title)
    r = make_request("GET", endpoint)
    if r:
        data = r.json()
        if data:
            df = pd.DataFrame(data)
            st.dataframe(df)
        else:
            st.info("No items to display.")


def render_rerank():
    st.header("Rerank News")
    default = {"strategy":"custom","parameters":{"importance_weight":0.7,"recency_weight":0.3}}
    payload_str = st.text_area("Rerank Payload", json.dumps(default, indent=2), height=150)
    if st.button("Rerank News"):
        try:
            payload = json.loads(payload_str)
            r = make_request("POST", "/news/rerank", payload)
            if r: st.success(r.json().get("message", "Reranked"))
        except json.JSONDecodeError:
            st.error("Invalid JSON payload.")


def render_sources():
    st.header("Manage Sources")

    # List current source records
    st.subheader("Current Sources")
    r = make_request("GET", "/sources")
    sources = r.json() if r else []
    if sources:
        df = pd.DataFrame(sources)
        st.dataframe(df)
    else:
        st.info("No sources found.")

    st.markdown("---")

    # Create new source record
    st.subheader("Create New Source")
    with st.form("create_source"):
        name = st.text_input("Source Name (e.g. 'reddit')")
        url = st.text_input("URL")
        title = st.text_input("Title")
        body = st.text_area("Body (optional)")
        from datetime import datetime
        published_at = st.text_input("Published At (ISO-8601 UTC)", value=datetime.utcnow().isoformat() + "Z")
        if st.form_submit_button("Create"):
            if not name:
                st.error("Source Name cannot be empty.")
                return
            if not url:
                st.error("URL cannot be empty.")
                return
            if not title:
                st.error("Title cannot be empty.")
                return

            payload = {
                "name": name,
                "url": url,
                "title": title,
                "body": body or None,
                "published_at": published_at # Send as string, let API parse
            }
            res = make_request("POST", "/sources", payload)
            if res: st.success("Source created!")

    st.markdown("---")

    # Update/Delete existing source
    if sources:
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Update Source")
            ids = [s["id"] for s in sources]
            sid = st.selectbox("Select Source ID", ids, key="up_id")
            src = next(s for s in sources if s["id"] == sid)
            new_name = st.text_input("Source Name", value=src["name"])
            new_url = st.text_input("URL", value=src["url"])
            new_title = st.text_input("Title", value=src["title"])
            new_body = st.text_area("Body (optional)", value=src.get("body", ""))
            new_published = st.text_input("Published At", value=src.get("published_at", ""))
            if st.button("Update"):
                payload = {
                    "name": new_name,
                    "url": new_url,
                    "title": new_title,
                    "body": new_body or None,
                    "published_at": new_published
                }
                r2 = make_request("PUT", f"/sources/{sid}", payload)
                if r2: st.success("Source updated!")
        with col2:
            st.subheader("Delete Source")
            sid2 = st.selectbox("Select Source ID to Delete", [s["id"] for s in sources], key="del_id")
            if st.button("Delete"):
                r3 = make_request("DELETE", f"/sources/{sid2}")
                if r3: st.success("Source deleted!")


def render_edit_source():
    st.header("Edit Source")
    r = make_request("GET", "/sources")
    sources = r.json() if r else []
    if not sources:
        st.info("No sources to edit.")
        return
    sid = st.selectbox("Select Source ID", [s["id"] for s in sources], key="edit_id")
    src = next(s for s in sources if s["id"] == sid)
    name_val = st.text_input("Source Name", value=src["name"])
    url_val = st.text_input("URL", value=src["url"])
    title_val = st.text_input("Title", value=src["title"])
    body_val = st.text_area("Body (optional)", value=src.get("body", ""))
    published_val = st.text_input("Published At", value=src.get("published_at", ""))
    if st.button("Save Changes"):
        payload = {
            "name": name_val,
            "url": url_val,
            "title": title_val,
            "body": body_val or None,
            "published_at": published_val
        }
        res = make_request("PUT", f"/sources/{sid}", payload)
        if res: st.success("Source details updated!")

# ————— Main App Layout with Sidebar —————
st.set_page_config(page_title="Sentinel AI", layout="wide")
st.title("Sentinel AI - Web Interface")

if "current_page" not in st.session_state:
    st.session_state.current_page = "Ingest Data"

# Sidebar Navigation
st.sidebar.title("Navigation")
api_options = {
    "Ingest Data": render_ingest,
    "Retrieve Data": render_retrieve,
    "All News": lambda: render_news("/news", "All News"),
    "Filtered News": lambda: render_news("/news/filtered", "Filtered News"),
    "Ranked News": lambda: render_news("/news/ranked", "Ranked News"),
    "Rerank News": render_rerank,
    "Manage Sources": render_sources,
    "Edit Source": render_edit_source
}

for name, func in api_options.items():
    if st.sidebar.button(name):
        st.session_state.current_page = name

# Render the selected page
api_options[st.session_state.current_page]()

# Footer
st.markdown("""
---
This application is developed by **[Gian Paolo Santopaolo](https://genmind.ch)**.  
Feel free to explore the codebase and contribute on GitHub:  
**[https://github.com/gsantopaolo/sentinel-AI/](https://github.com/gsantopaolo/sentinel-AI/)**  
Licensed under the **MIT License**.
"""
)
