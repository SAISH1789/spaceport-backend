import os
import subprocess
import sys
from uuid import uuid4

from sqlalchemy import create_engine, text


def test_upgrade_preserves_existing_booking_as_confirmed(db_engine):
    schema = "migration_" + uuid4().hex
    with db_engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    url = db_engine.url.update_query_dict({"options": f"-csearch_path={schema}"})
    engine = create_engine(url)
    env = {**os.environ, "DATABASE_URL": url.render_as_string(hide_password=False)}
    try:
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "0001"], env=env, check=True)
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO ships(id, name) VALUES (1, 'Legacy ship')"))
            conn.execute(
                text(
                    "INSERT INTO bookings(id, ship_id, pilot_name, start_time, end_time) "
                    "VALUES (123, 1, 'Legacy pilot', '2030-09-28T10:00:00-05:00', "
                    "'2030-09-28T11:00:00-05:00')"
                )
            )
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], env=env, check=True)
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT id, pilot_name, status, cancelled_at FROM bookings")
            ).one()
            assert tuple(row) == (123, "Legacy pilot", "confirmed", None)
    finally:
        engine.dispose()
        with db_engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
