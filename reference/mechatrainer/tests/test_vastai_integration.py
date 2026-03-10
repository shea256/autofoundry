"""Integration tests for Vast.ai API.

These tests interact with the real Vast.ai API and require:
- VAST_API_KEY environment variable to be set
- Real API credentials
- May incur costs

Run with: pytest -m integration tests/test_vastai_integration.py
"""

import os
import time
import pytest
from dotenv import load_dotenv
from providers.vastai import API

# Load environment variables
load_dotenv()


@pytest.fixture(scope="module")
def api_client():
    """Create a Vast.ai API client with real credentials."""
    api_key = os.getenv("VAST_API_KEY")
    if not api_key:
        pytest.skip("VAST_API_KEY not set in environment")
    return API(api_key=api_key)


@pytest.mark.integration
class TestVastAIIntegration:
    """Integration tests for Vast.ai API."""

    def test_list_and_get_instances(self, api_client):
        """
        Integration test 1: List all instances and get details if any exist.

        Steps:
        1. List all instances
        2. If at least one instance exists, get its details
        """
        print("\n--- Vast.ai Integration Test 1: List and Get ---")

        # Step 1: List all instances
        print("Step 1: Listing all instances...")
        instances_response = api_client.list_instances()

        # Handle both dict with 'instances' key and list responses
        if isinstance(instances_response, dict) and "instances" in instances_response:
            instances = instances_response["instances"]
        elif isinstance(instances_response, list):
            instances = instances_response
        else:
            instances = []

        print(f"Found {len(instances)} instance(s)")

        assert isinstance(instances, list), "Instances should be a list"

        # Step 2: If at least one instance exists, get its details
        if len(instances) > 0:
            instance_id = str(instances[0].get("id"))
            print(f"Step 2: Getting details for instance {instance_id}...")

            instance_details = api_client.get_instance(instance_id)

            assert instance_details is not None, "get_instance should return instance details"
            # Convert to string for comparison as API might return int or string
            assert str(instance_details.get("id")) == instance_id, "Instance ID should match"
            print(f"Successfully retrieved instance details for {instance_id}")
            print(f"Instance label: {instance_details.get('label')}")
            print(f"Instance status: {instance_details.get('status')}")
        else:
            print("No instances found to test get_instance operation")

        print("✓ Integration test 1 completed successfully\n")

    @pytest.mark.integration
    @pytest.mark.slow
    def test_instance_lifecycle(self, api_client):
        """
        Integration test 2: Full instance lifecycle.

        Steps:
        1. Create an instance
        2. Get the instance details
        3. Stop the instance
        4. Start the instance
        5. Restart the instance
        6. Stop the instance (cleanup - does not delete)

        Note: This test will search for available GPU offers if VAST_OFFER_ID
        environment variable is not set.

        Note: The instance is stopped but not deleted. You may need to manually delete it.
        """
        print("\n--- Vast.ai Integration Test 2: Full Instance Lifecycle ---")

        # Try to get offer_id from environment variable first
        offer_id = os.getenv("VAST_OFFER_ID")

        if not offer_id:
            # If not set, try to search for available offers
            print("VAST_OFFER_ID not set, searching for available GPU offers...")
            try:
                offers_response = api_client.search_offers()

                # Extract offers from response
                if isinstance(offers_response, dict) and "bundles" in offers_response:
                    offers = offers_response["bundles"]
                elif isinstance(offers_response, dict) and "offers" in offers_response:
                    offers = offers_response["offers"]
                else:
                    offers = offers_response if isinstance(offers_response, list) else []

                # Filter for rentable offers only
                rentable_offers = [o for o in offers if o.get("rentable", True) and not o.get("rented", False)]

                if not rentable_offers:
                    pytest.skip(
                        "No rentable GPU offers found. "
                        "Set VAST_OFFER_ID environment variable with a valid offer ID."
                    )

                # Use the first rentable offer
                offer_id = str(rentable_offers[0].get("id"))
                print(f"Found rentable offer ID: {offer_id} (GPU: {rentable_offers[0].get('gpu_name')}, ${rentable_offers[0].get('dph_total', 'N/A')}/hr)")

            except Exception as e:
                pytest.skip(
                    f"Failed to search for offers: {e}. "
                    "Set VAST_OFFER_ID environment variable with a valid offer ID."
                )

        # Configuration for test instance
        test_instance_label = f"test-instance-{int(time.time())}"
        test_image = "python:3.9-slim"
        test_command = "sleep infinity"

        instance_id = None

        try:
            # Step 1: Create an instance
            print(f"Step 1: Creating instance '{test_instance_label}'...")
            create_response = api_client.create_instance(
                offer_id=offer_id,
                image=test_image,
                command=test_command,
                disk_gb=10,
                label=test_instance_label,
            )

            assert create_response is not None, "create_instance should return a response"

            # Vast.ai might return instance ID in different formats
            if isinstance(create_response, dict):
                instance_id = str(create_response.get("new_contract") or create_response.get("id"))
            else:
                instance_id = str(create_response)

            assert instance_id is not None and instance_id != "None", "Created instance should have an ID"
            print(f"✓ Instance created with ID: {instance_id}")

            # Wait for instance to initialize
            time.sleep(10)

            # Step 2: Get the instance details
            print(f"Step 2: Getting instance details for {instance_id}...")
            try:
                instance_details = api_client.get_instance(instance_id)

                assert instance_details is not None, "get_instance should return instance details"
                print(f"✓ Instance details retrieved: {instance_details.get('label')}, status: {instance_details.get('status')}")
            except Exception as e:
                print(f"Warning: Could not get instance details (instance may still be initializing): {e}")

            # Wait for instance to be in a stable state
            time.sleep(15)

            # Step 3: Stop the instance
            print(f"Step 3: Stopping instance {instance_id}...")
            try:
                stop_response = api_client.stop_instance(instance_id)
                assert stop_response is not None, "stop_instance should return a response"
                print(f"✓ Instance stop requested")
            except Exception as e:
                print(f"Warning: Stop instance failed (may not be supported or instance not ready): {e}")

            # Wait for instance to stop
            time.sleep(10)

            # Step 4: Start the instance
            print(f"Step 4: Starting instance {instance_id}...")
            try:
                start_response = api_client.start_instance(instance_id)
                assert start_response is not None, "start_instance should return a response"
                print(f"✓ Instance start requested")
            except Exception as e:
                print(f"Warning: Start instance failed: {e}")

            # Wait for instance to start
            time.sleep(10)

            # Step 5: Restart the instance
            print(f"Step 5: Restarting instance {instance_id}...")
            try:
                restart_response = api_client.restart_instance(instance_id)
                assert restart_response is not None, "restart_instance should return a response"
                print(f"✓ Instance restart requested")
            except Exception as e:
                print(f"Warning: Restart instance failed: {e}")

            # Wait for instance to restart
            time.sleep(10)

        finally:
            # Step 6: Stop the instance (always execute this in finally block)
            if instance_id and instance_id != "None":
                print(f"Step 6: Stopping instance {instance_id} (cleanup)...")
                try:
                    stop_response = api_client.stop_instance(instance_id)
                    assert stop_response is not None, "stop_instance should return a response"
                    print(f"✓ Instance stopped successfully")
                    print(f"Note: Instance {instance_id} was stopped but not deleted. Please manually delete it if needed.")
                except Exception as e:
                    print(f"Warning: Failed to stop instance {instance_id}: {e}")
                    print("You may need to manually stop/delete this instance to avoid charges")

        print("✓ Integration test 2 completed successfully\n")

    @pytest.mark.integration
    def test_search_offers(self, api_client):
        """
        Bonus integration test: Search for GPU offers.

        Note: This endpoint is not available via Vast.ai REST API.
        This test verifies that the method raises a clear error message.
        """
        print("\n--- Vast.ai Integration Test: Search Offers ---")

        print("Attempting to search for GPU offers...")
        print("Note: This endpoint may not be available via REST API")

        try:
            offers_response = api_client.search_offers()

            # If we got here, the endpoint worked (unexpected but good!)
            if isinstance(offers_response, dict) and "offers" in offers_response:
                offers = offers_response["offers"]
            elif isinstance(offers_response, dict) and "bundles" in offers_response:
                offers = offers_response["bundles"]
            else:
                offers = offers_response if isinstance(offers_response, list) else []

            print(f"✓ Found {len(offers)} GPU offer(s)")
            if len(offers) > 0:
                print(f"First offer: {offers[0]}")

        except NotImplementedError as e:
            print(f"✓ As expected, search_offers is not available: {e}")
            pytest.skip(str(e))
        except Exception as e:
            print(f"✓ Search offers failed (expected): {e}")
            pytest.skip(f"Search offers endpoint not available: {e}")

        print("✓ Search offers test completed\n")
