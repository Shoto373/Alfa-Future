"""Prepare a server-local PostgreSQL password without changing an existing DB.

Docker Compose itself reads .env, so quoted values and interpolation follow the
same rules as the actual deployment. Secrets never go to stdout or CLI args.
"""
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile


PROBE = """services:
  envcheck:
    image: postgres:17.6
    environment:
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-}
"""


def run(args, **kwargs) -> str:
    result = subprocess.run(args, capture_output=True, text=True, **kwargs)
    if result.returncode:
        # Compose output can contain resolved env values; do not log it.
        raise RuntimeError("Docker configuration check failed; run docker compose config --quiet on the server")
    return result.stdout


def compose_config(root: Path, environment: dict, *, probe: bool) -> dict:
    args = ["docker", "compose", "--project-directory", str(root), "--env-file", str(root / ".env"),
            "-f", "-" if probe else str(root / "docker-compose.yml"), "config", "--format", "json"]
    return json.loads(run(args, env=environment, input=PROBE if probe else None))


def prepare(root: Path) -> bool:
    root = root.resolve()
    path = root / ".env"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT, 0o600)
    os.close(fd)
    path.chmod(0o600)
    environment = dict(os.environ)
    # An exported empty variable must not hide a value persisted in .env.
    if not environment.get("POSTGRES_PASSWORD"):
        environment.pop("POSTGRES_PASSWORD", None)
    current = compose_config(root, environment, probe=True)
    if current["services"]["envcheck"]["environment"]["POSTGRES_PASSWORD"]:
        return False

    # Resolve the actual project/volume name before allowing first-time setup.
    inspection_env = environment | {"POSTGRES_PASSWORD": "configuration-inspection-only"}
    configuration = compose_config(root, inspection_env, probe=False)
    volume = configuration["volumes"]["postgres_data"]["name"]
    existing = run(["docker", "volume", "ls", "--format", "{{.Name}}"], env=environment).splitlines()
    if volume in existing:
        raise RuntimeError("PostgreSQL volume already exists but POSTGRES_PASSWORD is missing. "
                           "Restore the existing password in the server .env; no password was generated")

    original = path.read_bytes()
    separator = b"\n" if original and not original.endswith(b"\n") else b""
    password = secrets.token_hex(32)
    fd, temporary = tempfile.mkstemp(prefix=".env-", dir=root)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(original + separator + f"POSTGRES_PASSWORD={password}\n".encode("ascii"))
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return True


if __name__ == "__main__":
    try:
        created = prepare(Path(__file__).resolve().parent.parent)
    except (RuntimeError, OSError, KeyError, ValueError) as exc:
        # Only our fixed messages are logged; parsed config/secrets are not.
        message = str(exc) if isinstance(exc, RuntimeError) else "Could not prepare the server .env"
        raise SystemExit(f"!! {message}")
    print("==> Created PostgreSQL password in server .env (mode 600)" if created
          else "==> PostgreSQL password already configured; keeping it")
