
import requests
import json

BASE_URL = "http://127.0.0.1:8000"

def test_endpoint(method, endpoint, data=None):
    """
    Tests a given endpoint of the API.

    Args:
        method (str): The HTTP method to use (e.g., "GET", "POST").
        endpoint (str): The API endpoint to test (e.g., "/news").
        data (dict, optional): The data to send with the request. Defaults to None.
    """
    try:
        response = requests.request(method, BASE_URL + endpoint, json=data)
        print(f"Response from {method} {endpoint}:")
        print(f"Status Code: {response.status_code}")
        try:
            print(f"Response JSON: {response.json()}")
        except json.JSONDecodeError:
            print(f"Response Text: {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    # Test all endpoints
    print("--- Testing POST /ingest ---")
    test_endpoint("POST", "/ingest")

    print("\n--- Testing GET /retrieve?batch_id=123 ---")
    test_endpoint("GET", "/retrieve?batch_id=123")

    print("\n--- Testing GET /news ---")
    test_endpoint("GET", "/news")

    print("\n--- Testing GET /news/filtered ---")
    test_endpoint("GET", "/news/filtered")

    print("\n--- Testing GET /news/ranked ---")
    test_endpoint("GET", "/news/ranked")

    print("\n--- Testing POST /news/rerank ---")
    test_endpoint("POST", "/news/rerank")

    print("\n--- Testing GET /sources ---")
    test_endpoint("GET", "/sources")

    print("\n--- Testing POST /sources ---")
    test_endpoint("POST", "/sources")

    print("\n--- Testing PUT /sources/1 ---")
    test_endpoint("PUT", "/sources/1")

    print("\n--- Testing DELETE /sources/1 ---")
    test_endpoint("DELETE", "/sources/1")

    
