"""add doctor_name to medical_records

Revision ID: 002
Revises: 001
Create Date: 2026-06-09
"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("medical_records", sa.Column("doctor_name", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("medical_records", "doctor_name")
