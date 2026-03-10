"""
Cloud GPU Provider API Client
Supports RunPod.io and Vast.ai for managing pods/instances, serverless endpoints, and network volumes.
"""

import os
import argparse
import requests
from dotenv import load_dotenv

from providers import get_preset, format_details, get_api_class


if __name__ == "__main__":
    # Load environment variables from .env file
    load_dotenv()

    # Create a parent parser with the provider argument (for use after subcommand)
    # Use default=argparse.SUPPRESS so it doesn't override main parser's value
    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parser.add_argument("--provider", choices=["runpod", "vastai"],
                               help="Cloud provider to use", default=argparse.SUPPRESS)

    # Main parser (allows --provider before subcommand)
    parser = argparse.ArgumentParser(description="Cloud GPU Provider API utility (RunPod or Vast.ai)")
    parser.add_argument("--provider", choices=["runpod", "vastai"],
                        help="Cloud provider to use", default=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="command", required=True)

    # list subcommand - also accepts --provider after the subcommand
    subparsers.add_parser("list", help="List pods/instances", parents=[parent_parser])

    # create subcommand - also accepts --provider after the subcommand
    create_parser = subparsers.add_parser("create", help="Create a pod/instance", parents=[parent_parser])
    create_parser.add_argument("--profile", default="axolotl", help="Preset profile (e.g., axolotl)")
    create_parser.add_argument("--name", required=True, help="Pod/instance name")
    create_parser.add_argument("--image", default=None, help="Docker image name (overrides profile)")
    create_parser.add_argument("--gpu", dest="gpu_type", default=None, help="GPU type id (overrides profile, not used for vastai)")
    create_parser.add_argument("--offer-id", default=None, help="Vast.ai offer ID (required for vastai)")
    create_parser.add_argument("--gpu-count", type=int, default=1, help="GPU count (runpod only)")
    create_parser.add_argument("--volume", type=int, default=0, help="Volume size in GB (runpod only)")
    create_parser.add_argument("--container-disk", type=int, default=10, help="Container disk size in GB")
    create_parser.add_argument("--min-vcpu", type=int, default=1, help="Min vCPU per GPU (runpod only)")
    create_parser.add_argument("--min-ram", type=int, default=1, help="Min RAM per GPU in GB (runpod only)")
    create_parser.add_argument("--start-cmd", default=None, help="Docker start command (string, overrides profile)")

    args = parser.parse_args()

    # Validate that provider was specified (either before or after subcommand)
    if not hasattr(args, 'provider'):
        parser.error("the following arguments are required: --provider")

    # Get API key from .env file based on provider
    api_key_env = "RUNPOD_API_KEY" if args.provider == "runpod" else "VAST_API_KEY"
    api_key = os.getenv(api_key_env)
    if not api_key:
        print(f"Error: {api_key_env} not found in .env file or environment variables.")
        exit(1)
    
    # Get API class from provider and instantiate
    API = get_api_class(args.provider)
    if not API:
        print(f"Error: Unknown provider '{args.provider}'")
        exit(1)
    client = API(api_key=api_key)

    try:
        if args.command == "list":
            if args.provider == "runpod":
                pods = client.list_pods()
                for i, pod in enumerate(pods):
                    print(f"Pod {i}:")
                    print(format_details(pod, provider="runpod"))
            else:  # vastai
                instances = client.list_instances()
                # Vast.ai returns a dict with 'instances' key or a list
                if isinstance(instances, dict) and "instances" in instances:
                    instances_list = instances["instances"]
                elif isinstance(instances, list):
                    instances_list = instances
                else:
                    instances_list = [instances] if instances else []
                
                for i, instance in enumerate(instances_list):
                    print(f"Instance {i}:")
                    print(format_details(instance, provider="vastai"))

        elif args.command == "create":
            preset = get_preset(args.profile, provider=args.provider)
            image = args.image or preset.get("image") or "python:3.9"
            docker_start_command = args.start_cmd or preset.get("start_cmd")
            
            if args.provider == "runpod":
                gpu_type = args.gpu_type or preset.get("gpu_type") or "NVIDIA L40S"
                new_pod = client.create_pod(
                    name=args.name,
                    image_name=image,
                    gpu_type_ids=[gpu_type],
                    cloud_type="SECURE",
                    gpu_count=args.gpu_count,
                    volume_in_gb=args.volume,
                    container_disk_in_gb=args.container_disk,
                    min_vcpu_per_gpu=args.min_vcpu,
                    min_ram_per_gpu=args.min_ram,
                    docker_start_command=docker_start_command,
                )
                print("Created pod:")
                print(format_details(new_pod, provider="runpod"))
            else:  # vastai
                offer_id = args.offer_id or preset.get("offer_id")
                if not offer_id:
                    gpu_search = preset.get("gpu_search")
                    if gpu_search:
                        print(f"Error: --offer-id is required for Vast.ai.")
                        print(f"Suggested search criteria from preset: {gpu_search}")
                        print("Use 'vastai_api.py' search_offers() or provide --offer-id manually.")
                    else:
                        print("Error: --offer-id is required for Vast.ai. Use search to find offers first.")
                    exit(1)
                
                new_instance = client.create_instance(
                    offer_id=offer_id,
                    image=image,
                    command=docker_start_command or "sleep infinity",
                    disk_gb=args.container_disk,
                    env=None,
                )
                print("Created instance:")
                print(format_details(new_instance, provider="vastai"))

    except ValueError as e:
        print(f"Error: {e}")
    except requests.exceptions.HTTPError as e:
        print(f"API Error: {e}")
        if hasattr(e, 'response') and hasattr(e.response, 'text'):
            print(f"Response: {e.response.text}")
