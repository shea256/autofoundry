"""Docker image builder — pre-bake dependencies into a custom image."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from autofoundry.theme import console, print_error, print_header, print_status, print_success

# Default base image (matches PROVIDER_IMAGES in provisioner.py)
DEFAULT_BASE_IMAGE = "runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404"


def generate_dockerfile(
    setup_script: Path,
    base_image: str = DEFAULT_BASE_IMAGE,
) -> str:
    """Generate a Dockerfile that runs a setup script on top of a base image."""
    return f"""\
FROM --platform=linux/amd64 {base_image}

# Copy and run setup script to pre-install dependencies
COPY {setup_script.name} /tmp/setup.sh
RUN chmod +x /tmp/setup.sh && /tmp/setup.sh

WORKDIR /workspace
"""


def build_image(
    setup_script: Path,
    image_tag: str,
    base_image: str = DEFAULT_BASE_IMAGE,
) -> bool:
    """Build a Docker image from a setup script.

    Args:
        setup_script: Path to a shell script that installs dependencies.
        image_tag: Full image tag (e.g., 'user/autoresearch:latest').
        base_image: Base Docker image to build on top of.

    Returns:
        True if the build succeeded.
    """
    print_header("IMAGE FABRICATION SEQUENCE")
    console.print()
    print_status("Setup script", str(setup_script))
    print_status("Base image", base_image)
    print_status("Target image", image_tag)
    console.print()

    # Check Docker is available
    try:
        subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print_error("Docker is not installed or not running.")
        return False

    dockerfile_content = generate_dockerfile(setup_script, base_image)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)

        # Write Dockerfile
        (tmppath / "Dockerfile").write_text(dockerfile_content)

        # Copy setup script into build context
        (tmppath / setup_script.name).write_bytes(setup_script.read_bytes())

        console.print("  [af.muted]Building image (this may take a while)...[/af.muted]")
        console.print()

        proc = subprocess.Popen(
            ["docker", "build", "--platform", "linux/amd64", "-t", image_tag, "."],
            cwd=tmpdir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        for line in proc.stdout:
            line = line.rstrip("\n")
            if line:
                console.print(f"  [af.muted]{line}[/af.muted]")

        proc.wait()

        if proc.returncode != 0:
            print_error(f"Docker build failed (exit {proc.returncode})")
            return False

    console.print()
    print_success(f"Image built: {image_tag}")
    return True


def push_image(image_tag: str) -> bool:
    """Push a Docker image to the registry.

    Args:
        image_tag: Full image tag to push.

    Returns:
        True if the push succeeded.
    """
    console.print()
    console.print("  [af.muted]Pushing image to registry...[/af.muted]")
    console.print()

    proc = subprocess.Popen(
        ["docker", "push", image_tag],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    for line in proc.stdout:
        line = line.rstrip("\n")
        if line:
            console.print(f"  [af.muted]{line}[/af.muted]")

    proc.wait()

    if proc.returncode != 0:
        print_error(f"Docker push failed (exit {proc.returncode})")
        print_error("Make sure you're logged in: docker login")
        return False

    console.print()
    print_success(f"Image pushed: {image_tag}")
    return True


def build_and_push(
    setup_script: Path,
    image_tag: str,
    base_image: str = DEFAULT_BASE_IMAGE,
) -> bool:
    """Build a Docker image and push it to the registry.

    Returns:
        True if both build and push succeeded.
    """
    if not build_image(setup_script, image_tag, base_image):
        return False
    return push_image(image_tag)
