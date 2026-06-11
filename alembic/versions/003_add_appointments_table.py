"""add appointments table

Revision ID: 003
Revises: 002
Create Date: 2026-06-11
"""
from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "appointments",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("clinic_id", sa.String(), nullable=False),
        sa.Column("patient_id", sa.String(), nullable=True),
        sa.Column("doctor_id", sa.String(), nullable=True),
        sa.Column("from_number", sa.String(30), nullable=False),
        sa.Column("patient_name", sa.String(255), nullable=True),
        sa.Column("doctor_name", sa.String(255), nullable=False),
        sa.Column("date_str", sa.String(100), nullable=False),
        sa.Column("time_str", sa.String(50), nullable=False),
        sa.Column("appointment_datetime", sa.DateTime(timezone=False), nullable=True),
        sa.Column("symptoms", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("reminder_sent", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"]),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.ForeignKeyConstraint(["doctor_id"], ["doctors.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "clinic_id", "from_number", "doctor_name", "appointment_datetime",
            name="uq_appointment_patient_doctor_time",
        ),
    )
    op.create_index("ix_appointments_clinic_id", "appointments", ["clinic_id"])
    op.create_index("ix_appointments_patient_id", "appointments", ["patient_id"])
    op.create_index("ix_appointments_doctor_id", "appointments", ["doctor_id"])
    op.create_index("ix_appointments_from_number", "appointments", ["from_number"])
    op.create_index("ix_appointments_status", "appointments", ["status"])
    op.create_index("ix_appointments_appointment_datetime", "appointments", ["appointment_datetime"])


def downgrade() -> None:
    op.drop_index("ix_appointments_appointment_datetime", "appointments")
    op.drop_index("ix_appointments_status", "appointments")
    op.drop_index("ix_appointments_from_number", "appointments")
    op.drop_index("ix_appointments_doctor_id", "appointments")
    op.drop_index("ix_appointments_patient_id", "appointments")
    op.drop_index("ix_appointments_clinic_id", "appointments")
    op.drop_table("appointments")
