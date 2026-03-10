# Mechatrainer

Cloud GPU Provider API Client - Supports RunPod.io and Vast.ai for managing GPU instances, enabling seamless control of cloud training infrastructure.

## Features

- **Multi-Provider Support**: Unified interface for RunPod and Vast.ai
- **Pod/Instance Management**: Create, start, stop, restart, and delete GPU instances
- **Provider Abstraction**: Easy switching between cloud providers
- **Comprehensive Testing**: Unit and integration tests for reliable operation
- **CLI Interface**: Command-line tool for quick operations

## Supported Providers

- **RunPod.io**: Secure cloud GPU pods
- **Vast.ai**: Affordable GPU marketplace

## Setup

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Create a `.env` file with your API keys:**
   ```bash
   # RunPod API Key
   RUNPOD_API_KEY=your_runpod_api_key_here

   # Vast.ai API Key
   VAST_API_KEY=your_vastai_api_key_here
   ```

## Usage

### Command Line Interface

**List pods/instances:**
```bash
# RunPod
python main.py --provider runpod list

# Vast.ai
python main.py --provider vastai list
```

**Create a pod/instance:**
```bash
# RunPod
python main.py --provider runpod create \
    --name my-training-pod \
    --profile axolotl \
    --gpu "NVIDIA L40S" \
    --gpu-count 1

# Vast.ai (requires offer ID from https://cloud.vast.ai/)
python main.py --provider vastai create \
    --name my-training-instance \
    --profile axolotl \
    --offer-id 12345
```

### Python API

**RunPod:**
```python
from providers.runpod import API
from dotenv import load_dotenv
import os

load_dotenv()
client = API(api_key=os.getenv("RUNPOD_API_KEY"))

# List pods
pods = client.list_pods()

# Create a pod
pod = client.create_pod(
    name="my-pod",
    image_name="pytorch/pytorch:latest",
    gpu_type_ids=["NVIDIA L40S"],
    cloud_type="SECURE",
    gpu_count=1,
    container_disk_in_gb=20
)

# Control pods
client.start_pod(pod_id="your-pod-id")
client.stop_pod(pod_id="your-pod-id")
client.delete_pod(pod_id="your-pod-id")
```

**Vast.ai:**
```python
from providers.vastai import API
from dotenv import load_dotenv
import os

load_dotenv()
client = API(api_key=os.getenv("VAST_API_KEY"))

# List instances
instances = client.list_instances()

# Search for GPU offers
offers = client.search_offers()

# Create an instance
instance = client.create_instance(
    offer_id="12345",
    image="pytorch/pytorch:latest",
    command="sleep infinity",
    disk_gb=20,
    label="my-instance"
)

# Control instances
client.start_instance(instance_id="your-instance-id")
client.stop_instance(instance_id="your-instance-id")
client.delete_instance(instance_id="your-instance-id")
```

## Project Structure

```
mechatrainer/
├── main.py                         # CLI interface
├── providers/
│   ├── __init__.py                 # Provider registry
│   ├── runpod.py                   # RunPod API client
│   └── vastai.py                   # Vast.ai API client
├── tests/
│   ├── test_runpod.py              # RunPod unit tests
│   ├── test_vastai.py              # Vast.ai unit tests
│   ├── test_runpod_integration.py  # RunPod integration tests
│   ├── test_vastai_integration.py  # Vast.ai integration tests
│   └── README.md                   # Testing documentation
├── requirements.txt
├── pytest.ini
└── README.md
```

## Testing

**Run all unit tests (no API keys required):**
```bash
pytest -m "not integration"
```

**Run integration tests (requires API keys):**
```bash
# All integration tests
pytest -m integration

# Only read-only tests (safe, no resource creation)
pytest -m "integration and not slow"

# Specific provider
pytest -m integration tests/test_runpod_integration.py
pytest -m integration tests/test_vastai_integration.py
```

See [tests/README.md](tests/README.md) for detailed testing documentation.

## Profiles

Pre-configured profiles for common use cases:

### Axolotl Profile
Fine-tuning LLMs with Axolotl framework:
- **Image**: `axolotlai/axolotl-base:main-base-py3.11-cu128-2.7.1`
- **Default GPU**: NVIDIA L40S
- **Container Disk**: 20 GB
- **Start Command**: Activates conda environment and launches Axolotl

## API Keys

### RunPod
1. Sign up at [RunPod.io](https://runpod.io)
2. Navigate to Settings → API Keys
3. Create a new API key
4. Add to `.env` as `RUNPOD_API_KEY`

### Vast.ai
1. Sign up at [Vast.ai](https://vast.ai)
2. Navigate to Account → API Keys
3. Create a new API key
4. Add to `.env` as `VAST_API_KEY`

## Contributing

Contributions are welcome! Please ensure:
1. All tests pass: `pytest`
2. Code follows existing style
3. Add tests for new features
4. Update documentation

## License

MIT License - See LICENSE file for details

## Support

For issues and questions:
- GitHub Issues: [Report a bug](https://github.com/your-org/mechatrainer/issues)
- Documentation: See `tests/README.md` for testing guide
