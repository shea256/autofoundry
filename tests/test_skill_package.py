"""Portable distribution should include skill references, never local configuration."""

import importlib.util
import zipfile
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "package_skill",
    Path(__file__).parents[1] / "scripts" / "package_skill.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_portable_archive_excludes_secrets_and_pins_api(tmp_path):
    source = Path(__file__).parents[1] / ".agents" / "skills" / "autofoundry"
    import shutil

    skill = tmp_path / "skill"
    shutil.copytree(source, skill)
    (skill / ".env").write_text("not-for-distribution")
    (skill / "agents" / "credentials.yaml").write_text("not-for-distribution")
    output = tmp_path / "skill.zip"
    module.package_skill(skill, output, "a" * 40)
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        assert "autofoundry/SKILL.md" in names
        assert "autofoundry/references/api.md" in names
        assert "autofoundry/agents/openai.yaml" in names
        assert "autofoundry/LICENSE" in names
        assert all("not-for-distribution" not in archive.read(name).decode() for name in names)
        assert "@" + "a" * 40 in archive.read("autofoundry/references/revision.md").decode()
    second = tmp_path / "second.zip"
    module.package_skill(skill, second, "a" * 40)
    assert second.read_bytes() == output.read_bytes()
    with pytest.raises(FileExistsError):
        module.package_skill(skill, output, "a" * 40)


def test_package_refuses_symlinked_files(tmp_path):
    (tmp_path / "SKILL.md").symlink_to(Path(__file__))
    (tmp_path / "LICENSE").write_text("license")
    with pytest.raises(ValueError, match="regular skill file"):
        module.package_skill(tmp_path, tmp_path / "skill.zip", "a" * 40)
