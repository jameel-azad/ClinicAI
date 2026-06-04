"""add google_calendar_id to doctors

Revision ID: 001
Revises:
Create Date: 2026-06-04
"""
from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("doctors", sa.Column("google_calendar_id", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("doctors", "google_calendar_id")
