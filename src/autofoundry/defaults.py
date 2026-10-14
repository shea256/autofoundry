"""Provider defaults shared by terminal and programmatic interfaces."""

from autofoundry.models import ProviderName

# Provider-native default images — latest CUDA available per platform
PROVIDER_IMAGES: dict[ProviderName, str] = {
    ProviderName.RUNPOD: "runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404",
    ProviderName.VASTAI: "runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404",
    ProviderName.PRIMEINTELLECT: "cuda_12_4_pytorch_2_4",
    ProviderName.LAMBDALABS: "",  # Lambda uses pre-configured Ubuntu images, not Docker
}
