import base64
import uuid

from typer.testing import CliRunner

from app.cli import cli_app

runner = CliRunner()


def test_cli_gen_master_key():
    """Test gen-master-key command produces 32-byte base64 key with expected format."""
    res = runner.invoke(cli_app, ["gen-master-key"])
    assert res.exit_code == 0
    output = res.stdout.strip()
    assert ":" in output
    kid, b64_key = output.split(":", 1)
    assert kid.startswith("key_")
    key_bytes = base64.b64decode(b64_key)
    assert len(key_bytes) == 32

    # Custom key id
    res_custom = runner.invoke(cli_app, ["gen-master-key", "--id", "custom_key_id"])
    assert res_custom.exit_code == 0
    assert res_custom.stdout.startswith("custom_key_id:")


def test_cli_migrate_check():
    """Test migrate-check command verifies DB is at head."""
    res = runner.invoke(cli_app, ["migrate-check"])
    assert res.exit_code == 0
    assert "up to date" in res.stdout.lower() or "head revision" in res.stdout.lower()


def test_cli_create_user_weak_password_rejected():
    """Test create-user rejects password shorter than 12 chars."""
    res = runner.invoke(
        cli_app,
        [
            "create-user",
            "--email",
            "weak@corp.com",
            "--password",
            "short",
            "--org-name",
            "Short Org",
        ],
    )
    assert res.exit_code == 1
    assert "at least 12 characters" in (res.stderr or res.stdout).lower()


def test_cli_create_user_success():
    """Test create-user creates organization, user, and membership."""
    unique = uuid.uuid4().hex[:8]
    email = f"user_{unique}@corp.com"
    res = runner.invoke(
        cli_app,
        [
            "create-user",
            "--email",
            email,
            "--password",
            "ValidPass1234!",
            "--org-name",
            f"Test Org {unique}",
            "--role",
            "admin",
        ],
    )
    assert res.exit_code == 0
    assert "created successfully" in res.stdout.lower()
    assert email in res.stdout


def test_cli_seed_dev():
    """Test seed-dev runs cleanly."""
    res = runner.invoke(cli_app, ["seed-dev"])
    assert res.exit_code == 0
    assert "acme" in res.stdout.lower() or "seeded" in res.stdout.lower()


def test_cli_rotate_master_key():
    """Test rotate-master-key runs without crashing."""
    res = runner.invoke(cli_app, ["rotate-master-key", "--new-key-id", "key_dev_01"])
    assert res.exit_code == 0
    assert "rotation complete" in res.stdout.lower()


def test_cli_expire_now():
    """Test expire-now runs cleanly."""
    res = runner.invoke(cli_app, ["expire-now"])
    assert res.exit_code == 0
    assert "expiry check completed" in res.stdout.lower()
