from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_production_dependencies_are_hash_locked_and_used_by_docker():
    base = (ROOT / "requirements/base.txt").read_text()
    lock = (ROOT / "requirements/production.lock").read_text()
    dockerfile = (ROOT / "Dockerfile").read_text()

    assert "cryptography>=50,<51" in base
    assert "--hash=sha256:" in lock
    assert "cryptography==" in lock
    assert "requirements/production.lock" in dockerfile
    assert "--require-hashes" in dockerfile
