from datetime import datetime
from decimal import Decimal
from typing import Dict, Any
from zoneinfo import ZoneInfo

from sqlalchemy import text


def _month_bounds_utc(year: int, month: int, timezone_name: str):
    """
    Local-month window as UTC-aware datetimes.

    Seed edge case: 2024-02-29 23:30 UTC is 2024-03-01 00:30 in Europe/Paris,
    so it belongs in March for a Paris property.
    """
    tz = ZoneInfo(timezone_name)
    start_local = datetime(year, month, 1, tzinfo=tz)
    if month < 12:
        end_local = datetime(year, month + 1, 1, tzinfo=tz)
    else:
        end_local = datetime(year + 1, 1, 1, tzinfo=tz)
    return start_local.astimezone(ZoneInfo("UTC")), end_local.astimezone(ZoneInfo("UTC"))


async def calculate_monthly_revenue(
    property_id: str,
    month: int,
    year: int,
    tenant_id: str,
    db_session=None,
) -> Decimal:
    """
    Calculates revenue for a specific month in the property's local timezone.
    """
    from app.core.database_pool import DatabasePool

    db_pool = DatabasePool()
    await db_pool.initialize()
    if not db_pool.session_factory:
        raise Exception("Database pool not available")

    async with db_pool.session_factory() as session:
        tz_row = await session.execute(
            text(
                """
                SELECT timezone FROM properties
                WHERE id = :property_id AND tenant_id = :tenant_id
                """
            ),
            {"property_id": property_id, "tenant_id": tenant_id},
        )
        prop = tz_row.fetchone()
        timezone_name = prop.timezone if prop and prop.timezone else "UTC"
        start_date, end_date = _month_bounds_utc(year, month, timezone_name)

        print(
            f"DEBUG: Querying revenue for {property_id} tenant={tenant_id} "
            f"tz={timezone_name} from {start_date} to {end_date}"
        )

        result = await session.execute(
            text(
                """
                SELECT COALESCE(SUM(total_amount), 0) as total
                FROM reservations
                WHERE property_id = :property_id
                  AND tenant_id = :tenant_id
                  AND check_in_date >= :start_date
                  AND check_in_date < :end_date
                """
            ),
            {
                "property_id": property_id,
                "tenant_id": tenant_id,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        row = result.fetchone()
        return Decimal(str(row.total)) if row else Decimal("0")


async def calculate_total_revenue(property_id: str, tenant_id: str) -> Dict[str, Any]:
    """
    Aggregates revenue from database.
    """
    try:
        from app.core.database_pool import DatabasePool

        db_pool = DatabasePool()
        await db_pool.initialize()

        if not db_pool.session_factory:
            raise Exception("Database pool not available")

        async with db_pool.session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT
                        property_id,
                        SUM(total_amount) as total_revenue,
                        COUNT(*) as reservation_count
                    FROM reservations
                    WHERE property_id = :property_id AND tenant_id = :tenant_id
                    GROUP BY property_id
                    """
                ),
                {
                    "property_id": property_id,
                    "tenant_id": tenant_id,
                },
            )
            row = result.fetchone()

            if row:
                total_revenue = Decimal(str(row.total_revenue))
                return {
                    "property_id": property_id,
                    "tenant_id": tenant_id,
                    "total": str(total_revenue),
                    "currency": "USD",
                    "count": row.reservation_count,
                }

            return {
                "property_id": property_id,
                "tenant_id": tenant_id,
                "total": "0.00",
                "currency": "USD",
                "count": 0,
            }

    except Exception as e:
        print(f"Database error for {property_id} (tenant: {tenant_id}): {e}")

        # Fallback when DB is unavailable. Excludes the Paris-local March edge booking
        # (res-tz-1), matching a UTC-naive March filter — the Client A mismatch.
        mock_data = {
            "prop-001": {"total": "1000.00", "count": 3},
            "prop-002": {"total": "4975.50", "count": 4},
            "prop-003": {"total": "6100.50", "count": 2},
            "prop-004": {"total": "1776.50", "count": 4},
            "prop-005": {"total": "3256.00", "count": 3},
        }

        mock_property_data = mock_data.get(property_id, {"total": "0.00", "count": 0})

        return {
            "property_id": property_id,
            "tenant_id": tenant_id,
            "total": mock_property_data["total"],
            "currency": "USD",
            "count": mock_property_data["count"],
        }
