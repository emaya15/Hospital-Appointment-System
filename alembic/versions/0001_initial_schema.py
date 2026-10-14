"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-12
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

NOW = sa.text("CURRENT_TIMESTAMP")
STATUS = sa.String(length=20)


def _timestamps():
    return [
        sa.Column("created_at", sa.DateTime(), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=NOW, nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(150), nullable=False),
        sa.Column("phone", sa.String(10), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked", sa.Boolean(), server_default=sa.false(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_refresh_tokens_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_tokens_token_hash")),
    )
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"])

    op.create_table(
        "patients",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("gender", sa.String(20), nullable=True),
        sa.Column("address", sa.String(255), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_patients_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_patients")),
        sa.UniqueConstraint("user_id", name=op.f("uq_patients_user_id")),
    )

    op.create_table(
        "departments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_departments")),
        sa.UniqueConstraint("name", name=op.f("uq_departments_name")),
    )

    op.create_table(
        "doctors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("department_id", sa.Integer(), nullable=False),
        sa.Column("specialization", sa.String(100), nullable=False),
        sa.Column("qualification", sa.String(200), nullable=False),
        sa.Column("experience_years", sa.Integer(), nullable=False),
        sa.Column("consultation_fee", sa.Numeric(10, 2), nullable=False),
        sa.Column("slot_duration_minutes", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("experience_years >= 0", name=op.f("ck_doctors_experience_non_negative")),
        sa.CheckConstraint("consultation_fee > 0", name=op.f("ck_doctors_fee_positive")),
        sa.CheckConstraint(
            "slot_duration_minutes IN (10, 15, 20, 30)", name=op.f("ck_doctors_slot_duration_allowed")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_doctors_user_id_users")),
        sa.ForeignKeyConstraint(
            ["department_id"], ["departments.id"], name=op.f("fk_doctors_department_id_departments")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_doctors")),
        sa.UniqueConstraint("user_id", name=op.f("uq_doctors_user_id")),
    )
    op.create_index(op.f("ix_doctors_department_id"), "doctors", ["department_id"])

    op.create_table(
        "doctor_schedules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("doctor_id", sa.Integer(), nullable=False),
        sa.Column("day_of_week", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("break_start", sa.Time(), nullable=True),
        sa.Column("break_end", sa.Time(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["doctor_id"], ["doctors.id"], name=op.f("fk_doctor_schedules_doctor_id_doctors")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_doctor_schedules")),
    )
    op.create_index("ix_doctor_schedules_doctor_day", "doctor_schedules", ["doctor_id", "day_of_week"])

    op.create_table(
        "doctor_leaves",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("doctor_id", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(255), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["doctor_id"], ["doctors.id"], name=op.f("fk_doctor_leaves_doctor_id_doctors")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_doctor_leaves")),
    )
    op.create_index(
        "ix_doctor_leaves_doctor_dates", "doctor_leaves", ["doctor_id", "start_date", "end_date"]
    )

    op.create_table(
        "appointments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("appointment_number", sa.String(30), nullable=False),
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("doctor_id", sa.Integer(), nullable=False),
        sa.Column("appointment_date", sa.Date(), nullable=False),
        sa.Column("appointment_time", sa.Time(), nullable=False),
        sa.Column("token_number", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("status", STATUS, nullable=False),
        sa.Column("consultation_fee", sa.Numeric(10, 2), nullable=False),
        sa.Column("reschedule_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("reminder_sent", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("slot_active", sa.Integer(), nullable=True),
        sa.Column("cancellation_reason", sa.String(255), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], name=op.f("fk_appointments_patient_id_patients")),
        sa.ForeignKeyConstraint(["doctor_id"], ["doctors.id"], name=op.f("fk_appointments_doctor_id_doctors")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_appointments")),
        sa.UniqueConstraint("appointment_number", name=op.f("uq_appointments_appointment_number")),
        sa.UniqueConstraint(
            "doctor_id", "appointment_date", "appointment_time", "slot_active", name="uq_doctor_slot"
        ),
        sa.UniqueConstraint(
            "patient_id", "doctor_id", "appointment_date", "slot_active", name="uq_patient_doctor_day"
        ),
        sa.UniqueConstraint(
            "patient_id", "appointment_date", "appointment_time", "slot_active", name="uq_patient_slot"
        ),
    )
    op.create_index("ix_appointments_doctor_date", "appointments", ["doctor_id", "appointment_date"])
    op.create_index("ix_appointments_patient_date", "appointments", ["patient_id", "appointment_date"])
    op.create_index("ix_appointments_status_date", "appointments", ["status", "appointment_date"])

    op.create_table(
        "appointment_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("appointment_id", sa.Integer(), nullable=False),
        sa.Column("old_status", STATUS, nullable=True),
        sa.Column("new_status", STATUS, nullable=False),
        sa.Column("changed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.String(255), nullable=True),
        sa.Column("changed_at", sa.DateTime(), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["appointment_id"], ["appointments.id"], name=op.f("fk_appointment_history_appointment_id_appointments")
        ),
        sa.ForeignKeyConstraint(
            ["changed_by_user_id"], ["users.id"], name=op.f("fk_appointment_history_changed_by_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_appointment_history")),
    )
    op.create_index(op.f("ix_appointment_history_appointment_id"), "appointment_history", ["appointment_id"])

    op.create_table(
        "consultations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("appointment_id", sa.Integer(), nullable=False),
        sa.Column("symptoms", sa.Text(), nullable=False),
        sa.Column("diagnosis", sa.Text(), nullable=False),
        sa.Column("advice", sa.Text(), nullable=True),
        sa.Column("follow_up_date", sa.Date(), nullable=True),
        sa.Column("follow_up_reminder_sent", sa.Boolean(), server_default=sa.false(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["appointment_id"], ["appointments.id"], name=op.f("fk_consultations_appointment_id_appointments")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consultations")),
        sa.UniqueConstraint("appointment_id", name=op.f("uq_consultations_appointment_id")),
    )

    op.create_table(
        "prescription_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("consultation_id", sa.Integer(), nullable=False),
        sa.Column("medicine", sa.String(150), nullable=False),
        sa.Column("dosage", sa.String(100), nullable=False),
        sa.Column("duration", sa.String(100), nullable=False),
        sa.ForeignKeyConstraint(
            ["consultation_id"], ["consultations.id"], name=op.f("fk_prescription_items_consultation_id_consultations")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prescription_items")),
    )
    op.create_index(op.f("ix_prescription_items_consultation_id"), "prescription_items", ["consultation_id"])

    op.create_table(
        "uploaded_files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("appointment_id", sa.Integer(), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("stored_filename", sa.String(100), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["appointment_id"], ["appointments.id"], name=op.f("fk_uploaded_files_appointment_id_appointments")
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_user_id"], ["users.id"], name=op.f("fk_uploaded_files_uploaded_by_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_uploaded_files")),
        sa.UniqueConstraint("stored_filename", name=op.f("uq_uploaded_files_stored_filename")),
    )
    op.create_index(op.f("ix_uploaded_files_appointment_id"), "uploaded_files", ["appointment_id"])

    op.create_table(
        "ratings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("appointment_id", sa.Integer(), nullable=False),
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("doctor_id", sa.Integer(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("review", sa.String(1000), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name=op.f("ck_ratings_rating_range")),
        sa.ForeignKeyConstraint(
            ["appointment_id"], ["appointments.id"], name=op.f("fk_ratings_appointment_id_appointments")
        ),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], name=op.f("fk_ratings_patient_id_patients")),
        sa.ForeignKeyConstraint(["doctor_id"], ["doctors.id"], name=op.f("fk_ratings_doctor_id_doctors")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ratings")),
        sa.UniqueConstraint("appointment_id", name=op.f("uq_ratings_appointment_id")),
    )
    op.create_index(op.f("ix_ratings_doctor_id"), "ratings", ["doctor_id"])


def downgrade() -> None:
    for table in (
        "ratings",
        "uploaded_files",
        "prescription_items",
        "consultations",
        "appointment_history",
        "appointments",
        "doctor_leaves",
        "doctor_schedules",
        "doctors",
        "departments",
        "patients",
        "refresh_tokens",
        "users",
    ):
        op.drop_table(table)
