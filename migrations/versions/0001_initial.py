"""Create the fleet and bookings."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
    )
    op.create_table(
        "bookings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ship_id", sa.Integer(), sa.ForeignKey("ships.id"), nullable=False),
        sa.Column("pilot_name", sa.String(200), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("end_time > start_time", name="positive_duration"),
        sa.CheckConstraint("length(trim(pilot_name)) > 0", name="nonempty_pilot"),
    )
    op.create_index("ix_bookings_ship_start", "bookings", ["ship_id", "start_time"])


def downgrade():
    op.drop_table("bookings")
    op.drop_table("ships")
