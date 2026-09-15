import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DataType(str, enum.Enum):
    FLOAT = "float"
    INT = "int"
    BOOL = "bool"
    STRING = "string"


class Quality(str, enum.Enum):
    GOOD = "good"
    UNCERTAIN = "uncertain"
    BAD = "bad"


class Role(str, enum.Enum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class AlarmCondition(str, enum.Enum):
    HIGH = "high"
    HIGH_HIGH = "high_high"
    LOW = "low"
    LOW_LOW = "low_low"
    DIGITAL_TRUE = "digital_true"
    DIGITAL_FALSE = "digital_false"
    BAD_QUALITY = "bad_quality"


class AlarmState(str, enum.Enum):
    ACTIVE = "active"
    ACKED = "acked"
    CLEARED = "cleared"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.VIEWER)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Tag(Base):
    """A single historized point: one PLC register, OPC UA node, MQTT topic, etc."""

    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(500), default=None)
    connection_name: Mapped[str] = mapped_column(String(128), index=True)
    address: Mapped[str] = mapped_column(String(255))
    data_type: Mapped[DataType] = mapped_column(Enum(DataType), default=DataType.FLOAT)
    engineering_units: Mapped[str | None] = mapped_column(String(32), default=None)
    min_value: Mapped[float | None] = mapped_column(Float, default=None)
    max_value: Mapped[float | None] = mapped_column(Float, default=None)
    deadband_percent: Mapped[float | None] = mapped_column(Float, default=None)
    poll_interval_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    archive_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    alarms: Mapped[list["AlarmDefinition"]] = relationship(back_populates="tag", cascade="all, delete-orphan")


class TagValue(Base):
    """Historized sample. High-volume table — a Timescale hypertable when running on Postgres."""

    __tablename__ = "tag_values"

    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    value_float: Mapped[float | None] = mapped_column(Float, default=None)
    value_string: Mapped[str | None] = mapped_column(String(255), default=None)
    value_bool: Mapped[bool | None] = mapped_column(Boolean, default=None)
    quality: Mapped[Quality] = mapped_column(Enum(Quality), default=Quality.GOOD)

    __table_args__ = (Index("ix_tag_values_tag_ts", "tag_id", "ts"),)


class AlarmDefinition(Base):
    __tablename__ = "alarm_definitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    condition: Mapped[AlarmCondition] = mapped_column(Enum(AlarmCondition))
    setpoint: Mapped[float | None] = mapped_column(Float, default=None)
    priority: Mapped[int] = mapped_column(Integer, default=5)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    message: Mapped[str | None] = mapped_column(String(500), default=None)

    tag: Mapped["Tag"] = relationship(back_populates="alarms")


class AlarmEvent(Base):
    """State-change history for alarms (activate / ack / clear) — the alarm & event journal."""

    __tablename__ = "alarm_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alarm_id: Mapped[int] = mapped_column(ForeignKey("alarm_definitions.id", ondelete="CASCADE"), index=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    state: Mapped[AlarmState] = mapped_column(Enum(AlarmState))
    value: Mapped[float | None] = mapped_column(Float, default=None)
    message: Mapped[str | None] = mapped_column(Text, default=None)
    acked_by: Mapped[str | None] = mapped_column(String(64), default=None)


class ConnectionStatusLog(Base):
    """Connector up/down events, for the connections health panel."""

    __tablename__ = "connection_status_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connection_name: Mapped[str] = mapped_column(String(128), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str | None] = mapped_column(String(500), default=None)


class AppSetting(Base):
    """Runtime-editable settings (Settings page) — distinct from app/config.py's
    Settings, which are process-startup env vars. Values are stored as text and
    typed/validated by app/core/settings_registry.py; this table only ever holds
    settings that a live, running process can actually apply without a restart."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
