"""Integration tests for PRIME Intellect API.

These tests interact with the real PRIME Intellect API and require:
- PRIMEINTELLECT_API_KEY environment variable to be set
- Real API credentials
- May incur costs

Run with: pytest -m integration tests/test_primeintellect_integration.py
"""

import os
import time
import pytest
from dotenv import load_dotenv
from providers.primeintellect import API

# Load environment variables
load_dotenv()


@pytest.fixture(scope="module")
def api_client():
    """Create a PRIME Intellect API client with real credentials."""
    api_key = os.getenv("PRIMEINTELLECT_API_KEY")
    if not api_key:
        pytest.skip("PRIMEINTELLECT_API_KEY not set in environment")
    return API(api_key=api_key)


@pytest.mark.integration
class TestPrimeIntellectIntegration:
    """Integration tests for PRIME Intellect API."""

    def test_list_and_get_pods(self, api_client):
        """
        Integration test 1: List all pods and get details if any exist.

        Steps:
        1. List all pods
        2. If at least one pod exists, get its details
        """
        print("\n--- PRIME Intellect Integration Test 1: List and Get ---")

        # Step 1: List all pods
        print("Step 1: Listing all pods...")
        response = api_client.list_pods()

        # PRIME Intellect returns a dict with 'data' key
        pods = response.get("data", []) if isinstance(response, dict) else response
        print(f"Found {len(pods)} pod(s)")

        assert isinstance(pods, list), "list_pods should return a list in 'data' field"

        # Step 2: If at least one pod exists, get its details
        if len(pods) > 0:
            pod_id = pods[0].get("id")
            print(f"Step 2: Getting details for pod {pod_id}...")

            pod_details = api_client.get_pod(pod_id)

            assert pod_details is not None, "get_pod should return pod details"
            assert pod_details.get("id") == pod_id, "Pod ID should match"
            print(f"Successfully retrieved pod details for {pod_id}")
            print(f"Pod name: {pod_details.get('name')}")
            print(f"Pod status: {pod_details.get('status')}")
        else:
            print("No pods found to test get_pod operation")

        print("✓ Integration test 1 completed successfully\n")

    @pytest.mark.integration
    def test_check_gpu_availability(self, api_client):
        """
        Integration test 2: Check GPU availability.

        Steps:
        1. Check GPU availability without filters
        2. Check GPU availability with filters
        """
        print("\n--- PRIME Intellect Integration Test 2: GPU Availability ---")

        # Step 1: Check GPU availability without filters
        print("Step 1: Checking GPU availability (no filters)...")
        response = api_client.check_gpu_availability()

        assert response is not None, "check_gpu_availability should return a response"
        assert "items" in response, "Response should contain 'items' field"

        items = response.get("items", [])
        total_count = response.get("totalCount", len(items))
        print(f"Found {total_count} GPU option(s)")

        if len(items) > 0:
            first_item = items[0]
            print(f"First available GPU: {first_item.get('gpuType')} ({first_item.get('gpuCount')} GPU(s))")
            print(f"  Provider: {first_item.get('provider')}")
            print(f"  Region: {first_item.get('region')}")
            print(f"  Security: {first_item.get('security')}")
            if first_item.get("prices"):
                print(f"  Price: ${first_item['prices'].get('onDemand', 'N/A')}/hr")

        # Step 2: Check GPU availability with filters
        print("\nStep 2: Checking GPU availability (with filters)...")
        filtered_response = api_client.check_gpu_availability(
            security="secure_cloud",
            page_size=10
        )

        assert filtered_response is not None, "Filtered check should return a response"
        filtered_items = filtered_response.get("items", [])
        print(f"Found {len(filtered_items)} secure cloud GPU option(s)")

        print("✓ Integration test 2 completed successfully\n")

    @pytest.mark.integration
    def test_check_disk_availability(self, api_client):
        """
        Integration test 3: Check disk availability.

        Steps:
        1. Check disk availability
        """
        print("\n--- PRIME Intellect Integration Test 3: Disk Availability ---")

        # Step 1: Check disk availability
        print("Step 1: Checking disk availability...")
        response = api_client.check_disk_availability()

        assert response is not None, "check_disk_availability should return a response"
        assert "items" in response, "Response should contain 'items' field"

        items = response.get("items", [])
        total_count = response.get("totalCount", len(items))
        print(f"Found {total_count} disk option(s)")

        if len(items) > 0:
            first_item = items[0]
            print(f"First available disk option:")
            print(f"  Provider: {first_item.get('provider')}")
            print(f"  Data Center: {first_item.get('dataCenter')}")
            print(f"  Region: {first_item.get('region')}")
            print(f"  Security: {first_item.get('security')}")
            if first_item.get("spec"):
                spec = first_item["spec"]
                print(f"  Min/Max: {spec.get('minCount', 'N/A')}-{spec.get('maxCount', 'N/A')} GB")
                print(f"  Price: ${spec.get('pricePerUnit', 'N/A')}/GB/hr")

        print("✓ Integration test 3 completed successfully\n")

    @pytest.mark.integration
    def test_get_pod_status(self, api_client):
        """
        Integration test 4: Get pod status for existing pods.

        Steps:
        1. List all pods
        2. If pods exist, get their status
        """
        print("\n--- PRIME Intellect Integration Test 4: Pod Status ---")

        # Step 1: List all pods
        print("Step 1: Listing all pods...")
        response = api_client.list_pods()
        pods = response.get("data", []) if isinstance(response, dict) else response

        if len(pods) == 0:
            print("No pods found to test get_pod_status operation")
            pytest.skip("No pods available to test status")

        # Step 2: Get status for existing pods
        pod_ids = [pod.get("id") for pod in pods[:5]]  # Get status for up to 5 pods
        print(f"Step 2: Getting status for {len(pod_ids)} pod(s)...")

        status_response = api_client.get_pod_status(pod_ids)

        assert status_response is not None, "get_pod_status should return a response"
        print(f"Retrieved status for pods")

        if isinstance(status_response, list):
            for status in status_response:
                print(f"  Pod {status.get('podId')}: {status.get('status')}")
        else:
            print(f"Status response: {status_response}")

        print("✓ Integration test 4 completed successfully\n")

    @pytest.mark.integration
    @pytest.mark.slow
    def test_pod_lifecycle(self, api_client):
        """
        Integration test 5: Full pod lifecycle.

        Dynamically finds the cheapest available GPU and runs a full lifecycle:
        1. Find cheapest available GPU
        2. Create a pod
        3. Get the pod details
        4. Delete the pod (cleanup)
        """
        print("\n--- PRIME Intellect Integration Test 5: Full Pod Lifecycle ---")

        # Step 1: Find the cheapest available GPU
        print("Step 1: Searching for cheapest available GPU...")
        availability_response = api_client.check_gpu_availability(
            security="secure_cloud",
            gpu_count=1,
            page_size=100
        )

        items = availability_response.get("items", [])

        # Filter for GPUs with good stock and valid prices
        available_gpus = [
            item for item in items
            if item.get("stockStatus") in ["Available", "High", "Medium"]
            and item.get("prices", {}).get("onDemand") is not None
        ]

        if not available_gpus:
            pytest.skip("No available GPUs found with good stock status")

        # Sort by price and select the cheapest
        available_gpus.sort(key=lambda x: x["prices"]["onDemand"])
        gpu = available_gpus[0]

        price = gpu["prices"]["onDemand"]
        print(f"Selected: {gpu['gpuType']} @ ${price:.2f}/hr ({gpu['provider']}, {gpu['dataCenter']})")

        # Configuration for test pod
        test_pod_name = f"test-pod-{int(time.time())}"
        pod_id = None

        try:
            # Step 2: Create a pod
            print(f"Step 2: Creating pod '{test_pod_name}'...")
            create_response = api_client.create_pod(
                name=test_pod_name,
                cloud_id=gpu["cloudId"],
                gpu_type=gpu["gpuType"],
                provider_type=gpu["provider"],
                gpu_count=1,
                image="ubuntu_22_cuda_12",
                socket=gpu.get("socket"),
                security=gpu.get("security", "secure_cloud"),
                data_center_id=gpu.get("dataCenter"),
                country=gpu.get("country"),
            )

            assert create_response is not None, "create_pod should return a response"
            pod_id = create_response.get("id")
            assert pod_id is not None, "Created pod should have an ID"
            print(f"✓ Pod created with ID: {pod_id}")

            # Wait for pod to initialize
            time.sleep(5)

            # Step 3: Get the pod details
            print(f"Step 3: Getting pod details for {pod_id}...")
            pod_details = api_client.get_pod(pod_id)

            assert pod_details is not None, "get_pod should return pod details"
            assert pod_details.get("id") == pod_id, "Pod ID should match"
            print(f"✓ Pod details: {pod_details.get('name')}, status: {pod_details.get('status')}")

        finally:
            # Step 4: Delete the pod (always execute this in finally block)
            if pod_id:
                print(f"Step 4: Deleting pod {pod_id}...")
                # Wait a bit before deleting (pod may still be provisioning)
                time.sleep(5)
                try:
                    api_client.delete_pod(pod_id)
                    print(f"✓ Pod deleted successfully")
                except Exception as e:
                    print(f"Warning: Failed to delete pod {pod_id}: {e}")
                    print("You may need to manually delete this pod to avoid charges")

        print("✓ Integration test 5 completed successfully\n")
