"""Run locally with bundled PostgreSQL; no Docker or system PostgreSQL required."""

import argparse
import hashlib
import os
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=Path, help="Import an existing seed JSON before starting")
    args = parser.parse_args()
    import pgserver
    from sqlalchemy.engine import make_url

    # Keep a handle alive for the lifetime of the API; stop Postgres when it exits.
    # pgserver's socket command cannot handle spaces in its data path.
    project_key = hashlib.sha256(str(Path.cwd().resolve()).encode()).hexdigest()[:12]
    data_path = Path.home() / ".spaceport" / project_key
    data_path.parent.mkdir(parents=True, exist_ok=True)
    server = pgserver.get_server(data_path, cleanup_mode="stop")
    url = make_url(server.get_uri()).set(drivername="postgresql+psycopg")
    env = {**os.environ, "DATABASE_URL": url.render_as_string(hide_password=False)}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], env=env, check=True)
    if args.seed:
        subprocess.run([sys.executable, "-m", "app.seed", str(args.seed)], env=env, check=True)
    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
            ],
            env=env,
            check=True,
        )
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
