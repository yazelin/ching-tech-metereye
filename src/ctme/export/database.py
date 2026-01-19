"""Database exporter using SQLAlchemy."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

SQLALCHEMY_AVAILABLE = False
try:
    from sqlalchemy import (
        Column,
        DateTime,
        Float,
        Index,
        Integer,
        String,
        create_engine,
        text,
    )
    from sqlalchemy.orm import Session, declarative_base, sessionmaker

    SQLALCHEMY_AVAILABLE = True
except ImportError:
    pass

from ctme.export.base import BaseExporter
from ctme.models import DatabaseExportConfig, IndicatorReading, Reading

logger = logging.getLogger(__name__)

if SQLALCHEMY_AVAILABLE:
    from sqlalchemy import Boolean

    Base = declarative_base()

    class ReadingRecord(Base):
        """SQLAlchemy model for readings."""

        __tablename__ = "readings"

        id = Column(Integer, primary_key=True, autoincrement=True)
        camera_id = Column(String(64), nullable=False, index=True)
        meter_id = Column(String(64), nullable=False, index=True)
        value = Column(Float, nullable=True)
        raw_text = Column(String(32), nullable=False)
        timestamp = Column(DateTime, nullable=False, index=True)
        confidence = Column(Float, nullable=False, default=1.0)

        __table_args__ = (
            Index("idx_camera_meter_time", "camera_id", "meter_id", "timestamp"),
        )

    class IndicatorReadingRecord(Base):
        """SQLAlchemy model for indicator readings."""

        __tablename__ = "indicator_readings"

        id = Column(Integer, primary_key=True, autoincrement=True)
        camera_id = Column(String(64), nullable=False, index=True)
        indicator_id = Column(String(64), nullable=False, index=True)
        state = Column(Boolean, nullable=False)  # True = ON, False = OFF
        brightness = Column(Float, nullable=False)
        timestamp = Column(DateTime, nullable=False, index=True)

        __table_args__ = (
            Index("idx_camera_indicator_time", "camera_id", "indicator_id", "timestamp"),
        )


class DatabaseExporter(BaseExporter):
    """Export readings to SQLite or PostgreSQL database."""

    def __init__(self, config: DatabaseExportConfig):
        """Initialize database exporter.

        Args:
            config: Database export configuration
        """
        super().__init__("Database")
        self.config = config
        self._enabled = config.enabled
        self._engine = None
        self._session_factory = None
        self._last_cleanup: datetime | None = None

        if not SQLALCHEMY_AVAILABLE:
            logger.warning(
                "SQLAlchemy not installed. Install with: pip install sqlalchemy"
            )
            self._enabled = False

    def _get_connection_string(self) -> str:
        """Get database connection string."""
        if self.config.connection_string:
            return self.config.connection_string

        if self.config.type == "sqlite":
            return f"sqlite:///{self.config.path}"
        elif self.config.type == "postgresql":
            return self.config.connection_string
        else:
            raise ValueError(f"Unsupported database type: {self.config.type}")

    def start(self) -> None:
        """Initialize database connection and create tables."""
        super().start()

        if not SQLALCHEMY_AVAILABLE or not self._enabled:
            return

        try:
            connection_string = self._get_connection_string()
            self._engine = create_engine(connection_string, echo=False)

            # Create tables
            Base.metadata.create_all(self._engine)

            self._session_factory = sessionmaker(bind=self._engine)

            logger.info(f"Database connected: {self.config.type}")

        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            self._enabled = False

    def stop(self) -> None:
        """Close database connection."""
        super().stop()

        if self._engine:
            self._engine.dispose()
            self._engine = None

    def _cleanup_old_records(self, session: Any) -> None:
        """Delete records older than retention period.

        Args:
            session: Database session
        """
        if self.config.retention_days <= 0:
            return

        # Only run cleanup once per hour
        now = datetime.now()
        if self._last_cleanup and (now - self._last_cleanup).total_seconds() < 3600:
            return

        try:
            cutoff = now - timedelta(days=self.config.retention_days)

            # Clean up meter readings
            deleted_readings = (
                session.query(ReadingRecord)
                .filter(ReadingRecord.timestamp < cutoff)
                .delete()
            )

            # Clean up indicator readings
            deleted_indicators = (
                session.query(IndicatorReadingRecord)
                .filter(IndicatorReadingRecord.timestamp < cutoff)
                .delete()
            )

            total_deleted = deleted_readings + deleted_indicators
            if total_deleted > 0:
                session.commit()
                logger.info(f"Cleaned up {total_deleted} old records ({deleted_readings} readings, {deleted_indicators} indicators)")

            self._last_cleanup = now

        except Exception as e:
            logger.error(f"Cleanup failed: {e}")
            session.rollback()

    def export(self, reading: Reading) -> bool:
        """Export a single reading to database.

        Args:
            reading: Reading to export

        Returns:
            True if export succeeded
        """
        if not self._enabled or not self._session_factory:
            return True

        try:
            session = self._session_factory()
            try:
                record = ReadingRecord(
                    camera_id=reading.camera_id,
                    meter_id=reading.meter_id,
                    value=reading.value,
                    raw_text=reading.raw_text,
                    timestamp=reading.timestamp,
                    confidence=reading.confidence,
                )
                session.add(record)
                session.commit()

                # Periodic cleanup
                self._cleanup_old_records(session)

                return True

            finally:
                session.close()

        except Exception as e:
            logger.error(f"Database export failed: {e}")
            return False

    def export_batch(self, readings: list[Reading]) -> bool:
        """Export a batch of readings to database.

        Args:
            readings: List of readings to export

        Returns:
            True if export succeeded
        """
        if not self._enabled or not self._session_factory:
            return True

        if not readings:
            return True

        try:
            session = self._session_factory()
            try:
                records = [
                    ReadingRecord(
                        camera_id=r.camera_id,
                        meter_id=r.meter_id,
                        value=r.value,
                        raw_text=r.raw_text,
                        timestamp=r.timestamp,
                        confidence=r.confidence,
                    )
                    for r in readings
                ]
                session.add_all(records)
                session.commit()

                # Periodic cleanup
                self._cleanup_old_records(session)

                return True

            finally:
                session.close()

        except Exception as e:
            logger.error(f"Database batch export failed: {e}")
            return False

    def query_history(
        self,
        camera_id: str | None = None,
        meter_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
    ) -> list[Reading]:
        """Query historical readings.

        Args:
            camera_id: Filter by camera ID
            meter_id: Filter by meter ID
            start_time: Start of time range
            end_time: End of time range
            limit: Maximum number of records

        Returns:
            List of readings
        """
        if not self._enabled or not self._session_factory:
            return []

        try:
            session = self._session_factory()
            try:
                query = session.query(ReadingRecord)

                if camera_id:
                    query = query.filter(ReadingRecord.camera_id == camera_id)
                if meter_id:
                    query = query.filter(ReadingRecord.meter_id == meter_id)
                if start_time:
                    query = query.filter(ReadingRecord.timestamp >= start_time)
                if end_time:
                    query = query.filter(ReadingRecord.timestamp <= end_time)

                query = query.order_by(ReadingRecord.timestamp.desc()).limit(limit)

                records = query.all()

                return [
                    Reading(
                        camera_id=r.camera_id,
                        meter_id=r.meter_id,
                        value=r.value,
                        raw_text=r.raw_text,
                        timestamp=r.timestamp,
                        confidence=r.confidence,
                    )
                    for r in records
                ]

            finally:
                session.close()

        except Exception as e:
            logger.error(f"Database query failed: {e}")
            return []

    def export_indicator(self, reading: IndicatorReading) -> bool:
        """Export a single indicator reading to database.

        Args:
            reading: Indicator reading to export

        Returns:
            True if export succeeded
        """
        if not self._enabled or not self._session_factory:
            return True

        try:
            session = self._session_factory()
            try:
                record = IndicatorReadingRecord(
                    camera_id=reading.camera_id,
                    indicator_id=reading.indicator_id,
                    state=reading.state,
                    brightness=reading.brightness,
                    timestamp=reading.timestamp,
                )
                session.add(record)
                session.commit()

                # Periodic cleanup
                self._cleanup_old_records(session)

                return True

            finally:
                session.close()

        except Exception as e:
            logger.error(f"Database indicator export failed: {e}")
            return False

    def export_indicator_batch(self, readings: list[IndicatorReading]) -> bool:
        """Export a batch of indicator readings to database.

        Args:
            readings: List of indicator readings to export

        Returns:
            True if export succeeded
        """
        if not self._enabled or not self._session_factory:
            return True

        if not readings:
            return True

        try:
            session = self._session_factory()
            try:
                records = [
                    IndicatorReadingRecord(
                        camera_id=r.camera_id,
                        indicator_id=r.indicator_id,
                        state=r.state,
                        brightness=r.brightness,
                        timestamp=r.timestamp,
                    )
                    for r in readings
                ]
                session.add_all(records)
                session.commit()

                # Periodic cleanup
                self._cleanup_old_records(session)

                return True

            finally:
                session.close()

        except Exception as e:
            logger.error(f"Database indicator batch export failed: {e}")
            return False

    def query_indicator_history(
        self,
        camera_id: str | None = None,
        indicator_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
    ) -> list[IndicatorReading]:
        """Query historical indicator readings.

        Args:
            camera_id: Filter by camera ID
            indicator_id: Filter by indicator ID
            start_time: Start of time range
            end_time: End of time range
            limit: Maximum number of records

        Returns:
            List of indicator readings
        """
        if not self._enabled or not self._session_factory:
            return []

        try:
            session = self._session_factory()
            try:
                query = session.query(IndicatorReadingRecord)

                if camera_id:
                    query = query.filter(IndicatorReadingRecord.camera_id == camera_id)
                if indicator_id:
                    query = query.filter(IndicatorReadingRecord.indicator_id == indicator_id)
                if start_time:
                    query = query.filter(IndicatorReadingRecord.timestamp >= start_time)
                if end_time:
                    query = query.filter(IndicatorReadingRecord.timestamp <= end_time)

                query = query.order_by(IndicatorReadingRecord.timestamp.desc()).limit(limit)

                records = query.all()

                return [
                    IndicatorReading(
                        camera_id=r.camera_id,
                        indicator_id=r.indicator_id,
                        state=r.state,
                        brightness=r.brightness,
                        timestamp=r.timestamp,
                    )
                    for r in records
                ]

            finally:
                session.close()

        except Exception as e:
            logger.error(f"Database indicator query failed: {e}")
            return []
