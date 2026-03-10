# Mechatrainer Tests

This directory contains unit tests and integration tests for the mechatrainer cloud GPU provider API client.

## Test Structure

```
tests/
├── __init__.py
├── test_runpod.py              # Unit tests for RunPod API (mocked)
├── test_vastai.py              # Unit tests for Vast.ai API (mocked)
├── test_runpod_integration.py  # Integration tests for RunPod API (real API calls)
├── test_vastai_integration.py  # Integration tests for Vast.ai API (real API calls)
└── README.md                   # This file
```

## Unit Tests

Unit tests use mocked HTTP requests and do not require API keys or make real API calls.

**Run all unit tests:**
```bash
pytest -m "not integration"
```

**Run unit tests with coverage:**
```bash
pytest -m "not integration" --cov=providers --cov-report=html
```

**Run specific unit test file:**
```bash
pytest tests/test_runpod.py
pytest tests/test_vastai.py
```

### Unit Test Coverage

- **RunPod** (`test_runpod.py`): 10 tests
  - API initialization and validation
  - `list_pods()` - List all pods
  - `get_pod(pod_id)` - Get specific pod details
  - Error handling (404, 500, etc.)
  - Complex data structures

- **Vast.ai** (`test_vastai.py`): 16 tests
  - API initialization and validation
  - `list_instances()` - List all instances
  - `get_instance(instance_id)` - Get specific instance details
  - `search_offers(filters)` - Search for GPU offers
  - Error handling (401, 404, 500, etc.)
  - Complex filter combinations

## Integration Tests

Integration tests make real API calls and require valid API keys. **Warning: These tests may incur costs!**

### Prerequisites

1. Set up environment variables in `.env` file:
   ```bash
   RUNPOD_API_KEY=your_runpod_api_key_here
   VAST_API_KEY=your_vastai_api_key_here
   ```

2. Ensure you have sufficient credits in your accounts

### Running Integration Tests

**Run all integration tests:**
```bash
pytest -m integration
```

**Run only fast integration tests (exclude slow lifecycle tests):**
```bash
pytest -m "integration and not slow"
```

**Run specific provider integration tests:**
```bash
# RunPod only
pytest -m integration tests/test_runpod_integration.py

# Vast.ai only
pytest -m integration tests/test_vastai_integration.py
```

**Run specific integration test:**
```bash
# RunPod list and get test only
pytest tests/test_runpod_integration.py::TestRunPodIntegration::test_list_and_get_pods

# RunPod full lifecycle test only
pytest tests/test_runpod_integration.py::TestRunPodIntegration::test_pod_lifecycle

# Vast.ai list and get test only
pytest tests/test_vastai_integration.py::TestVastAIIntegration::test_list_and_get_instances

# Vast.ai instance lifecycle test only
pytest tests/test_vastai_integration.py::TestVastAIIntegration::test_instance_lifecycle

# Vast.ai search offers test only
pytest tests/test_vastai_integration.py::TestVastAIIntegration::test_search_offers
```

### Integration Test Coverage

#### RunPod Integration Tests

**Test 1: List and Get Operations** (`test_list_and_get_pods`)
- Lists all existing pods
- If pods exist, retrieves details for the first pod
- Read-only, no costs incurred

**Test 2: Full Pod Lifecycle** (`test_pod_lifecycle`) - **CREATES RESOURCES**
1. Creates a test pod
2. Gets the pod details
3. Stops the pod
4. Starts the pod
5. Restarts the pod
6. Stops the pod (cleanup - does not delete)

**Warning:** This test creates actual resources and may incur costs!

**Note:** The pod is stopped but not deleted at the end of the test. You may need to manually delete it to avoid ongoing charges.

#### Vast.ai Integration Tests

**Test 1: List and Get Operations** (`test_list_and_get_instances`)
- Lists all existing instances
- If instances exist, retrieves details for the first instance
- Read-only, no costs incurred

**Test 2: Full Instance Lifecycle** (`test_instance_lifecycle`) - **CREATES RESOURCES**
1. Creates a test instance (requires `VAST_OFFER_ID` environment variable)
2. Gets the instance details
3. Stops the instance
4. Starts the instance
5. Restarts the instance
6. Stops the instance (cleanup - does not delete)

**Warning:** This test creates actual resources and may incur costs!

**Note:** The instance is stopped but not deleted at the end of the test. You may need to manually delete it to avoid ongoing charges.

**Requirements:** This test requires a `VAST_OFFER_ID` environment variable. Find available offers at https://cloud.vast.ai/ or use the Vast.ai CLI.

**Test 3: Search Offers** (`test_search_offers`)
- Searches for available GPU offers
- Read-only, no costs incurred

## Running All Tests

**Run everything (unit + integration):**
```bash
pytest
```

**Run only unit tests:**
```bash
pytest -m "not integration"
```

**Run with verbose output:**
```bash
pytest -v
```

**Run with output capture disabled (see print statements):**
```bash
pytest -s
```

## Continuous Integration

For CI/CD pipelines, you typically want to run only unit tests:

```bash
# Fast unit tests only
pytest -m "not integration"
```

Integration tests should be run separately, perhaps on a schedule or manually, since they:
- Require real API credentials
- May incur costs
- Take longer to execute
- Depend on external service availability

## Troubleshooting

### "RUNPOD_API_KEY not set in environment"
- Make sure you have a `.env` file with `RUNPOD_API_KEY=your_key`
- Or export the environment variable: `export RUNPOD_API_KEY=your_key`

### "VAST_API_KEY not set in environment"
- Make sure you have a `.env` file with `VAST_API_KEY=your_key`
- Or export the environment variable: `export VAST_API_KEY=your_key`

### Tests fail with "404 Not Found"
- For `test_list_and_get_*`: This is expected if you have no existing resources
- For lifecycle tests: This may indicate an issue with resource creation

### Resources not cleaned up
- If a lifecycle test fails before cleanup, you may need to manually delete resources
- Check your RunPod/Vast.ai dashboards and delete any test pods/instances
- Test resources are named with timestamps: `test-pod-1234567890` or `test-instance-1234567890`

## Test Markers

- `@pytest.mark.integration` - Tests that make real API calls
- `@pytest.mark.slow` - Tests that take a long time (lifecycle tests)

## Development

When adding new tests:

1. **Unit tests**: Mock all HTTP requests using `unittest.mock`
2. **Integration tests**: Mark with `@pytest.mark.integration`
3. **Slow tests**: Also mark with `@pytest.mark.slow` if they take >30 seconds
4. **Cleanup**: Always use try/finally blocks to ensure resource cleanup in lifecycle tests
