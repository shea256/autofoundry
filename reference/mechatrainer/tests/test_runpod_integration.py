"""Integration tests for RunPod API.

These tests interact with the real RunPod API and require:
- RUNPOD_API_KEY environment variable to be set
- Real API credentials
- May incur costs

Run with: pytest -m integration tests/test_runpod_integration.py
"""

import os
import time
import pytest
from dotenv import load_dotenv
from providers.runpod import API

# Load environment variables
load_dotenv()


@pytest.fixture(scope="module")
def api_client():
    """Create a RunPod API client with real credentials."""
    api_key = os.getenv("RUNPOD_API_KEY")
    if not api_key:
        pytest.skip("RUNPOD_API_KEY not set in environment")
    return API(api_key=api_key)


@pytest.mark.integration
class TestRunPodIntegration:
    """Integration tests for RunPod API."""

    def test_list_and_get_pods(self, api_client):
        """
        Integration test 1: List all pods and get details if any exist.

        Steps:
        1. List all pods
        2. If at least one pod exists, get its details
        """
        print("\n--- RunPod Integration Test 1: List and Get ---")

        # Step 1: List all pods
        print("Step 1: Listing all pods...")
        pods = api_client.list_pods()
        print(f"Found {len(pods)} pod(s)")

        assert isinstance(pods, list), "list_pods should return a list"

        # Step 2: If at least one pod exists, get its details
        if len(pods) > 0:
            pod_id = pods[0].get("id")
            print(f"Step 2: Getting details for pod {pod_id}...")

            pod_details = api_client.get_pod(pod_id)

            assert pod_details is not None, "get_pod should return pod details"
            assert pod_details.get("id") == pod_id, "Pod ID should match"
            print(f"Successfully retrieved pod details for {pod_id}")
            print(f"Pod name: {pod_details.get('name')}")
            print(f"Pod status: {pod_details.get('desiredStatus')}")
        else:
            print("No pods found to test get_pod operation")

        print("✓ Integration test 1 completed successfully\n")

    @pytest.mark.integration
    @pytest.mark.slow
    def test_pod_lifecycle(self, api_client):
        """
        Integration test 2: Full pod lifecycle.

        Steps:
        1. Create a pod
        2. Get the pod details
        3. Stop the pod
        4. Start the pod
        5. Restart the pod
        6. Stop the pod (cleanup - does not delete)

        Note: The pod is stopped but not deleted. You may need to manually delete it.
        """
        print("\n--- RunPod Integration Test 2: Full Pod Lifecycle ---")

        # Configuration for test pod
        test_pod_name = f"test-pod-{int(time.time())}"
        test_image = "python:3.9-slim"
        test_gpu_type = "NVIDIA RTX A4000"  # Using a more affordable GPU for testing

        pod_id = None

        try:
            # Step 1: Create a pod
            print(f"Step 1: Creating pod '{test_pod_name}'...")
            create_response = api_client.create_pod(
                name=test_pod_name,
                image_name=test_image,
                gpu_type_ids=[test_gpu_type],
                cloud_type="SECURE",
                gpu_count=1,
                volume_in_gb=0,
                container_disk_in_gb=10,
                min_vcpu_per_gpu=1,
                min_ram_per_gpu=1,
                docker_start_command="sleep infinity",
                support_public_ip=False,
            )

            assert create_response is not None, "create_pod should return a response"
            pod_id = create_response.get("id")
            assert pod_id is not None, "Created pod should have an ID"
            print(f"✓ Pod created with ID: {pod_id}")

            # Wait a bit for pod to initialize
            time.sleep(5)

            # Step 2: Get the pod details
            print(f"Step 2: Getting pod details for {pod_id}...")
            pod_details = api_client.get_pod(pod_id)

            assert pod_details is not None, "get_pod should return pod details"
            assert pod_details.get("id") == pod_id, "Pod ID should match"
            assert pod_details.get("name") == test_pod_name, "Pod name should match"
            print(f"✓ Pod details retrieved: {pod_details.get('name')}, status: {pod_details.get('desiredStatus')}")

            # Wait for pod to be in a stable state
            time.sleep(10)

            # Step 3: Stop the pod
            print(f"Step 3: Stopping pod {pod_id}...")
            stop_response = api_client.stop_pod(pod_id)
            assert stop_response is not None, "stop_pod should return a response"
            print(f"✓ Pod stop requested")

            # Wait for pod to stop
            time.sleep(10)

            # Step 4: Start the pod
            print(f"Step 4: Starting pod {pod_id}...")
            start_response = api_client.start_pod(pod_id)
            assert start_response is not None, "start_pod should return a response"
            print(f"✓ Pod start requested")

            # Wait for pod to start
            time.sleep(10)

            # Step 5: Restart the pod
            print(f"Step 5: Restarting pod {pod_id}...")
            restart_response = api_client.restart_pod(pod_id)
            assert restart_response is not None, "restart_pod should return a response"
            print(f"✓ Pod restart requested")

            # Wait for pod to restart
            time.sleep(10)

        finally:
            # Step 6: Stop the pod (always execute this in finally block)
            if pod_id:
                print(f"Step 6: Stopping pod {pod_id} (cleanup)...")
                try:
                    stop_response = api_client.stop_pod(pod_id)
                    assert stop_response is not None, "stop_pod should return a response"
                    print(f"✓ Pod stopped successfully")
                    print(f"Note: Pod {pod_id} was stopped but not deleted. Please manually delete it if needed.")
                except Exception as e:
                    print(f"Warning: Failed to stop pod {pod_id}: {e}")
                    print("You may need to manually stop/delete this pod to avoid charges")

        print("✓ Integration test 2 completed successfully\n")
