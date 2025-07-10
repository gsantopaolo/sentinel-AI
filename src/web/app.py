import streamlit as st
import requests
import pandas as pd
import json

# --- API Configuration ---
BASE_URL = "http://localhost:8000"

# --- Helper Functions ---
def make_request(method, endpoint, data=None):
    """Makes a request to the API and handles errors."""
    try:
        response = requests.request(method, f"{BASE_URL}{endpoint}", json=data)
        response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)
        return response
    except requests.exceptions.RequestException as e:
        st.error(f"An error occurred: {e}")
        return None

# --- UI Rendering Functions ---
def render_ingest():
    st.header("Ingest Data")

    default_payload = {
        "source": "manual",
        "events": [
            {
                "id": "evt-123",
                "title": "Example Event",
                "content": "This is the content of the example event.",
                "timestamp": "2025-07-10T10:00:00Z"
            }
        ]
    }

    payload_str = st.text_area(
        "JSON Payload",
        value=json.dumps(default_payload, indent=2),
        height=250
    )

    if st.button("Ingest Data"):
        try:
            payload = json.loads(payload_str)
            response = make_request("POST", "/ingest", data=payload)
            if response:
                st.success(response.json().get("message", "Success!"))
                
        except json.JSONDecodeError:
            st.error("Invalid JSON. Please check the format.")

def render_retrieve():
    st.header("Retrieve Data")
    batch_id = st.text_input("Enter Batch ID")
    if st.button("Retrieve"):
        if batch_id:
            response = make_request("GET", f"/retrieve?batch_id={batch_id}")
            if response:
                st.json(response.json())
        else:
            st.warning("Please enter a Batch ID.")

def render_news(endpoint, title):
    st.header(title)
    response = make_request("GET", endpoint)
    if response:
        data = response.json()
        if data:
            df = pd.DataFrame(data)
            st.dataframe(df)
        else:
            st.info("No news to display.")

def render_rerank():
    st.header("Rerank News")

    default_payload = {
        "strategy": "custom",
        "parameters": {
            "importance_weight": 0.7,
            "recency_weight": 0.3
        }
    }

    payload_str = st.text_area(
        "Rerank Payload",
        value=json.dumps(default_payload, indent=2),
        height=150
    )

    if st.button("Rerank News"):
        try:
            payload = json.loads(payload_str)
            response = make_request("POST", "/news/rerank", data=payload)
            if response:
                st.success(response.json().get("message", "Success!"))
        except json.JSONDecodeError:
            st.error("Invalid JSON. Please check the format.")

def render_sources():
    st.header("Manage Sources")

    # Display current sources
    st.subheader("Current Sources")
    response = make_request("GET", "/sources")
    if response:
        sources = response.json()
        if sources:
            df = pd.DataFrame(sources)
            st.dataframe(df)
        else:
            st.info("No sources found.")

    # Create a new source
    st.subheader("Create New Source")
    with st.form("create_source_form"):
        # In a real app, you'd have fields for the source details
        submitted = st.form_submit_button("Create Source")
        if submitted:
            response = make_request("POST", "/sources")
            if response and response.status_code == 201:
                st.success("Source created successfully!")
                st.json(response.json())

    # Update a source
    st.subheader("Update Source")
    source_id_to_update = st.number_input("Source ID to Update", min_value=1, step=1)
    if st.button("Update Source"): 
        response = make_request("PUT", f"/sources/{source_id_to_update}")
        if response:
            st.success(response.json().get("message"))

    # Delete a source
    st.subheader("Delete Source")
    source_id_to_delete = st.number_input("Source ID to Delete", min_value=1, step=1)
    if st.button("Delete Source"):
        response = make_request("DELETE", f"/sources/{source_id_to_delete}")
        if response and response.status_code == 204:
            st.success(f"Source {source_id_to_delete} deleted successfully!")

# --- Main App --- 
st.set_page_config(page_title="Sentinel AI", layout="wide")
st.title("Sentinel AI - Web Interface")

# Initialize session state for current page
if 'current_page' not in st.session_state:
    st.session_state.current_page = "Ingest Data"

# --- Sidebar Navigation ---
st.sidebar.title("Navigation")
api_options = {
    "Ingest Data": render_ingest,
    "Retrieve Data": render_retrieve,
    "All News": lambda: render_news("/news", "All News"),
    "Filtered News": lambda: render_news("/news/filtered", "Filtered News"),
    "Ranked News": lambda: render_news("/news/ranked", "Ranked News"),
    "Rerank News": render_rerank,
    "Manage Sources": render_sources,
}

for page_name, page_func in api_options.items():
    if st.sidebar.button(page_name):
        st.session_state.current_page = page_name

# --- Render Selected Page ---
page_to_render = api_options[st.session_state.current_page]
page_to_render()

st.markdown("""
---
This application is developed by **[Gian Paolo Santopaolo](https://genmind.ch)**. 

Feel free to explore the codebase and contribute on GitHub: 
**[https://github.com/gsantopaolo/sentinel-AI/](https://github.com/gsantopaolo/sentinel-AI/)**

This project is licensed under the **MIT License**.

If you like this project, please consider starring it on GitHub!
""")