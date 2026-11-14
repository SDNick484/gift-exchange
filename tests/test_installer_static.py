"""The installer is built, not run: these tests check what can be checked without an Alpine host."""
import base64
import io
import os
import re
import subprocess
import tarfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _build():
    subprocess.run(["sh", "installer/build.sh"], cwd=ROOT, check=True, capture_output=True)
    return os.path.join(ROOT, "dist", "setup-exchange.sh")


def _payload_names(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    b64 = text.split("\n__PAYLOAD_BELOW__\n", 1)[1]
    raw = base64.b64decode(b64)
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        return set(tar.getnames())


def test_build_produces_a_valid_installer():
    subprocess.run(["sh", "installer/build.sh"], cwd=ROOT, check=True)
    subprocess.run(["sh", "-n", "dist/setup-exchange.sh"], cwd=ROOT, check=True)


def test_installer_binds_loopback():
    head = _read("installer/setup-head.sh")
    assert "127.0.0.1:" in head and "0.0.0.0" not in head


def test_every_module_and_setting_is_shipped():
    """Each top-level *.py is in the built payload; each env name read in settings.py except DATA_DIR and
    SECRET_KEY appears in .env.example and the installer's settings list."""
    names = _payload_names(_build())
    modules = [f for f in os.listdir(ROOT) if f.endswith(".py")]
    assert "app.py" in modules and "settings.py" in modules
    for module in modules:
        assert f"exchange/{module}" in names, module
    assert "exchange/static/index.html" in names
    assert "exchange/ops/exchange-backup" in names

    settings = _read("settings.py")
    env_names = set(re.findall(r'os\.environ\.get\("([A-Z_]+)"', settings))
    env_names |= set(re.findall(r'_int\("([A-Z_]+)"', settings))
    env_names -= {"DATA_DIR", "SECRET_KEY"}
    assert {"EXCHANGE_PORT", "APP_NAME", "ADMIN_PASSWORD_HASH"} <= env_names
    env_example = _read(".env.example")
    head = _read("installer/setup-head.sh")
    for name in env_names:
        assert re.search(rf"^#?\s*{name}=", env_example, re.M), f"{name} missing from .env.example"
        assert re.search(rf"add_setting \"\$CONF\" {name} ", head), f"{name} missing from the installer's settings"


def test_installer_never_writes_a_secret_key():
    head = _read("installer/setup-head.sh")
    assert not re.search(r"add_setting .*SECRET_KEY", head)
    assert "secret.key" in head  # explained in a comment: the app makes it itself
