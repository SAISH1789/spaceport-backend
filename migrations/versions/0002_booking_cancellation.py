"""Preserve cancelled bookings while releasing their reserved time."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "bookings", sa.Column("status", sa.String(20), nullable=False, server_default="confirmed")
    )
    op.add_column("bookings", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "valid_booking_status", "bookings", "status IN ('confirmed', 'cancelled')"
    )
    op.create_check_constraint(
        "consistent_cancellation",
        "bookings",
        "(status = 'confirmed' AND cancelled_at IS NULL) OR "
        "(status = 'cancelled' AND cancelled_at IS NOT NULL)",
    )


def downgrade():
    # Removing these fields would reactivate cancelled records and can create overlaps.
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS(SELECT 1 FROM bookings WHERE status = 'cancelled')")
    ):
        raise RuntimeError("Cannot remove cancellation status while cancelled bookings exist")
    op.drop_constraint("consistent_cancellation", "bookings", type_="check")
    op.drop_constraint("valid_booking_status", "bookings", type_="check")
    op.drop_column("bookings", "cancelled_at")
    op.drop_column("bookings", "status")
