"""Tests for the provisioner module."""

from pathlib import Path

from autofoundry.provisioner import _read_ssh_public_key


class TestReadSshPublicKey:
    def test_reads_pub_key_file(self, tmp_path: Path) -> None:
        key_path = tmp_path / "id_rsa"
        pub_path = tmp_path / "id_rsa.pub"
        key_path.write_text("private key")
        pub_path.write_text("ssh-rsa AAAA... user@host\n")

        result = _read_ssh_public_key(str(key_path))
        assert result == "ssh-rsa AAAA... user@host"

    def test_returns_empty_when_no_pub_key(self, tmp_path: Path) -> None:
        key_path = tmp_path / "id_rsa"
        key_path.write_text("private key")

        result = _read_ssh_public_key(str(key_path))
        assert result == ""
