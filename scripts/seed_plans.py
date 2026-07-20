"""Seed the four canonical plans (free / starter / pro / enterprise).

Idempotent: existing plans are updated in place by slug, not duplicated.
Use ``--dry-run`` to print the planned upserts without committing.

    python scripts/seed_plans.py            # apply
    python scripts/seed_plans.py --dry-run  # preview
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

from sqlalchemy import select

from apps.api.app.db import Plan, get_sessionmaker, init_db_if_needed


PLANS: list[dict[str, Any]] = [
    {
        "slug": "free",
        "name": "Free",
        "description": "Get started — basic registry lookups, no risk analysis.",
        "price_monthly_cents": 0,
        "price_yearly_cents": 0,
        "currency": "usd",
        "features": {
            "risk_analysis": False,
            "pdf_extraction": False,
            "bulk_export": False,
            "api_access": False,
        },
        "limits": {
            "searches_per_day": 10,
            "company_lookups_per_day": 5,
            "risk_analyses_per_month": 0,
            "financial_lookups_per_month": 5,
        },
        "is_active": True,
    },
    {
        "slug": "starter",
        "name": "Starter",
        "description": "For individual analysts and small teams.",
        "price_monthly_cents": 1900,
        "price_yearly_cents": 19000,
        "currency": "usd",
        "features": {
            "risk_analysis": True,
            "pdf_extraction": True,
            "bulk_export": False,
            "api_access": False,
        },
        "limits": {
            "searches_per_day": 100,
            "company_lookups_per_day": 50,
            "risk_analyses_per_month": 10,
            "financial_lookups_per_month": 50,
        },
        "is_active": True,
    },
    {
        "slug": "pro",
        "name": "Pro",
        "description": "Production credit workflows with API access and bulk export.",
        "price_monthly_cents": 7900,
        "price_yearly_cents": 79000,
        "currency": "usd",
        "features": {
            "risk_analysis": True,
            "pdf_extraction": True,
            "bulk_export": True,
            "api_access": True,
        },
        "limits": {
            "searches_per_day": 500,
            "company_lookups_per_day": 200,
            "risk_analyses_per_month": 100,
            "financial_lookups_per_month": 200,
        },
        "is_active": True,
    },
    {
        "slug": "enterprise",
        "name": "Enterprise",
        "description": "High-volume credit intelligence with priority support.",
        "price_monthly_cents": 49900,
        "price_yearly_cents": 499000,
        "currency": "usd",
        "features": {
            "risk_analysis": True,
            "pdf_extraction": True,
            "bulk_export": True,
            "api_access": True,
        },
        "limits": {
            "searches_per_day": 10_000,
            "company_lookups_per_day": 5_000,
            "risk_analyses_per_month": 5_000,
            "financial_lookups_per_month": 10_000,
        },
        "is_active": True,
    },
]


async def _seed(dry_run: bool) -> int:
    if not dry_run:
        await init_db_if_needed()

    sm = get_sessionmaker()
    created = updated = 0
    async with sm() as session:
        for spec in PLANS:
            existing = (
                await session.execute(select(Plan).where(Plan.slug == spec["slug"]))
            ).scalar_one_or_none() if not dry_run else None

            if existing is None and not dry_run:
                session.add(Plan(**spec))
                created += 1
                print(
                    f"  CREATE plan slug={spec['slug']} "
                    f"monthly=${spec['price_monthly_cents'] / 100:.2f} "
                    f"yearly=${spec['price_yearly_cents'] / 100:.2f}"
                )
            elif existing is None and dry_run:
                created += 1
                print(
                    f"  (dry-run) CREATE plan slug={spec['slug']} "
                    f"monthly=${spec['price_monthly_cents'] / 100:.2f} "
                    f"yearly=${spec['price_yearly_cents'] / 100:.2f}"
                )
            else:
                for k, v in spec.items():
                    setattr(existing, k, v)
                updated += 1
                print(
                    f"  UPDATE plan slug={spec['slug']} "
                    f"monthly=${spec['price_monthly_cents'] / 100:.2f}"
                )

        if dry_run:
            print(
                f"\nDry-run summary: would create={created}, would update={updated}"
            )
            return 0
        await session.commit()

    print(f"\nDone: created={created}, updated={updated}, total={len(PLANS)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print planned ops, do not commit.")
    args = parser.parse_args()
    return asyncio.run(_seed(args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
