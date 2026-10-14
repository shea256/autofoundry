"""Build a portable skill ZIP pinned to this repository's committed Python API."""

from __future__ import annotations

import argparse
import subprocess
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / ".agents" / "skills" / "autofoundry"


def package_skill(skill: Path, output: Path, revision: str) -> None:
    """Archive only distributable skill files; no workspace/config/credential files."""
    required = [skill / "SKILL.md", skill / "LICENSE"]
    for path in required:
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"Missing regular skill file: {path.name}")
    paths = required + [skill / "references" / "api.md", skill / "agents" / "openai.yaml"]
    if any((skill / name).is_symlink() for name in ("references", "agents")):
        raise ValueError("Skill archives must not follow symlinked directories")
    if any(path.is_symlink() for path in paths):
        raise ValueError("Skill archives must not follow symlinks")
    if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision):
        raise ValueError("An exact Git commit is required")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:

        def write(name: str, data: bytes):
            info = zipfile.ZipInfo(f"autofoundry/{name}", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)

        for path in paths:
            write(path.relative_to(skill).as_posix(), path.read_bytes())
        write(
            "references/revision.md",
            (
                "# Matching library revision\n\n"
                f"This skill was packaged from commit `{revision}`. "
                "Install its Python API with:\n\n"
                "```bash\nuv pip install 'autofoundry[modal] @ "
                f"git+https://github.com/shea256/autofoundry.git@{revision}'\n```\n"
                "\nThe archive installs no dependencies and grants no execution authorization.\n"
            ).encode(),
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="New ZIP path, preferably outside the repository")
    args = parser.parse_args()
    status = subprocess.check_output(
        [
            "git",
            "status",
            "--porcelain",
            "--",
            "src/autofoundry",
            ".agents/skills/autofoundry",
            "pyproject.toml",
            "uv.lock",
        ],
        cwd=REPO,
        text=True,
    )
    if status:
        parser.error(
            "Commit library/skill/dependency changes first so the archive pins matching code"
        )
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    package_skill(SKILL, args.output, revision)
    print(f"Created {args.output} (library revision {revision})")


if __name__ == "__main__":
    main()
