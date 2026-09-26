import os
import subprocess
import sys
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker


@pytest.fixture(scope="session")
def db_engine(tmp_path_factory):
    uri = os.environ.get("TEST_DATABASE_URL")
    server = None
    if uri is None:
        import pgserver

        server = pgserver.get_server(tmp_path_factory.mktemp("postgres"), cleanup_mode="delete")
        uri = server.get_uri()
    url = make_url(uri).set(drivername="postgresql+psycopg")
    admin = create_engine(url)
    schema = "test_" + uuid4().hex
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    isolated_url = url.update_query_dict({"options": f"-csearch_path={schema}"})
    engine = create_engine(isolated_url, isolation_level="READ COMMITTED")
    try:
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            check=True,
            env={**os.environ, "DATABASE_URL": isolated_url.render_as_string(hide_password=False)},
        )
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
        # Retain the pgserver handle until all connections close; it cleans up at exit.
        del server


@pytest.fixture()
def sessions(db_engine):
    from app.models import Ship

    with db_engine.begin() as conn:
        conn.execute(text("TRUNCATE bookings, ships RESTART IDENTITY CASCADE"))
    factory = sessionmaker(db_engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add_all([Ship(id=1, name="USS Wanderer"), Ship(id=2, name="Nostromo")])
    return factory


@pytest.fixture()
def client(sessions):
    from app.database import get_session
    from app.main import app

    def override():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
