from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class CheckHistory(Base):
    __tablename__ = "check_history"
    __table_args__ = (
        CheckConstraint(
            "status IN ('up', 'issues', 'down')",
            name="ck_check_history_status",
        ),
        Index(
            "check_history_target_time_idx",
            "target",
            "checked_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target: Mapped[str] = mapped_column(String(253), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    latency: Mapped[float | None] = mapped_column(Float)
    status_code: Mapped[int | None] = mapped_column(Integer)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    error: Mapped[str | None] = mapped_column(Text)


class OutageReportRecord(Base):
    __tablename__ = "outage_reports"
    __table_args__ = (
        Index(
            "outage_reports_target_time_idx",
            "target",
            "created_at",
        ),
        Index(
            "outage_reports_rate_limit_idx",
            "target",
            "reporter_hash",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target: Mapped[str] = mapped_column(String(253), nullable=False)
    reporter_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
