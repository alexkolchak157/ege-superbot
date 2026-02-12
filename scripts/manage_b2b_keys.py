#!/usr/bin/env python3
"""
Утилита для управления B2B API-ключами.

Использование:
  python scripts/manage_b2b_keys.py create --name "Школа Плюс" --school-id 1
  python scripts/manage_b2b_keys.py create --name "Test Key" --limit 500
  python scripts/manage_b2b_keys.py list
  python scripts/manage_b2b_keys.py deactivate --key-id 3
  python scripts/manage_b2b_keys.py create-school --name "Онлайн-школа Плюс" --email admin@school.ru
"""

import argparse
import asyncio
import hashlib
import secrets
import sys
import os

# Добавляем корень проекта в PYTHONPATH
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aiosqlite
from core.config import DATABASE_FILE


def generate_api_key() -> str:
    """Генерирует безопасный API-ключ: egb2b_XXXX...XXXX (48 символов)."""
    return f"egb2b_{secrets.token_hex(24)}"


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


async def create_school(name: str, email: str = None, contact_name: str = None):
    """Создаёт запись школы."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        cursor = await db.execute(
            """
            INSERT INTO schools (name, contact_email, contact_name)
            VALUES (?, ?, ?)
            """,
            (name, email, contact_name),
        )
        school_id = cursor.lastrowid
        await db.commit()
        print(f"School created: id={school_id}, name='{name}'")
        return school_id


async def create_key(
    name: str,
    school_id: int = None,
    rate_limit: int = 60,
    monthly_limit: int = 1000,
):
    """Создаёт новый API-ключ."""
    raw_key = generate_api_key()
    key_h = hash_key(raw_key)
    prefix = raw_key[:12]

    async with aiosqlite.connect(DATABASE_FILE) as db:
        cursor = await db.execute(
            """
            INSERT INTO b2b_api_keys
                (key_hash, key_prefix, school_id, name,
                 rate_limit_per_minute, monthly_check_limit)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (key_h, prefix, school_id, name, rate_limit, monthly_limit),
        )
        key_id = cursor.lastrowid
        await db.commit()

    print("=" * 60)
    print(f"API Key created successfully!")
    print(f"  ID:            {key_id}")
    print(f"  Name:          {name}")
    print(f"  School ID:     {school_id or '(none)'}")
    print(f"  Rate limit:    {rate_limit} req/min")
    print(f"  Monthly limit: {monthly_limit} checks")
    print()
    print(f"  API KEY: {raw_key}")
    print()
    print("  IMPORTANT: Save this key now! It cannot be retrieved later.")
    print("=" * 60)


async def list_keys():
    """Показывает все API-ключи."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT k.*, s.name as school_name
            FROM b2b_api_keys k
            LEFT JOIN schools s ON k.school_id = s.id
            ORDER BY k.created_at DESC
            """
        )
        rows = await cursor.fetchall()

    if not rows:
        print("No API keys found.")
        return

    print(f"{'ID':>4} | {'Prefix':<14} | {'Name':<25} | {'School':<20} | "
          f"{'Used':>6} | {'Limit':>6} | {'Active':>6}")
    print("-" * 100)

    for r in rows:
        print(
            f"{r['id']:>4} | {r['key_prefix']:<14} | {r['name']:<25} | "
            f"{(r['school_name'] or '-'):<20} | "
            f"{r['checks_used_this_month']:>6} | {r['monthly_check_limit']:>6} | "
            f"{'Yes' if r['is_active'] else 'No':>6}"
        )


async def list_schools():
    """Показывает все школы."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM schools ORDER BY id")
        rows = await cursor.fetchall()

    if not rows:
        print("No schools found.")
        return

    print(f"{'ID':>4} | {'Name':<30} | {'Email':<25} | {'Active':>6}")
    print("-" * 75)
    for r in rows:
        print(
            f"{r['id']:>4} | {r['name']:<30} | "
            f"{(r['contact_email'] or '-'):<25} | "
            f"{'Yes' if r['is_active'] else 'No':>6}"
        )


async def deactivate_key(key_id: int):
    """Деактивирует API-ключ."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute(
            "UPDATE b2b_api_keys SET is_active = FALSE WHERE id = ?",
            (key_id,),
        )
        await db.commit()
    print(f"API key {key_id} deactivated.")


async def show_stats(key_id: int = None):
    """Показывает статистику проверок."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        db.row_factory = aiosqlite.Row

        if key_id:
            cursor = await db.execute(
                """
                SELECT task_type, status, COUNT(*) as cnt,
                       AVG(processing_time_ms) as avg_time
                FROM b2b_check_log
                WHERE api_key_id = ?
                GROUP BY task_type, status
                """,
                (key_id,),
            )
        else:
            cursor = await db.execute(
                """
                SELECT task_type, status, COUNT(*) as cnt,
                       AVG(processing_time_ms) as avg_time
                FROM b2b_check_log
                GROUP BY task_type, status
                """
            )

        rows = await cursor.fetchall()

    if not rows:
        print("No checks found.")
        return

    print(f"{'Task Type':<12} | {'Status':<12} | {'Count':>6} | {'Avg Time (ms)':>14}")
    print("-" * 55)
    for r in rows:
        avg_time = f"{r['avg_time']:.0f}" if r['avg_time'] else "-"
        print(f"{r['task_type']:<12} | {r['status']:<12} | {r['cnt']:>6} | {avg_time:>14}")


def main():
    parser = argparse.ArgumentParser(description="B2B API Key Management")
    subparsers = parser.add_subparsers(dest="command")

    # create key
    p_create = subparsers.add_parser("create", help="Create new API key")
    p_create.add_argument("--name", required=True, help="Key name/description")
    p_create.add_argument("--school-id", type=int, default=None, help="School ID")
    p_create.add_argument("--rate-limit", type=int, default=60, help="Requests per minute")
    p_create.add_argument("--limit", type=int, default=1000, help="Monthly check limit")

    # create school
    p_school = subparsers.add_parser("create-school", help="Create new school")
    p_school.add_argument("--name", required=True, help="School name")
    p_school.add_argument("--email", default=None, help="Contact email")
    p_school.add_argument("--contact", default=None, help="Contact person name")

    # list
    subparsers.add_parser("list", help="List all API keys")
    subparsers.add_parser("list-schools", help="List all schools")

    # deactivate
    p_deact = subparsers.add_parser("deactivate", help="Deactivate an API key")
    p_deact.add_argument("--key-id", type=int, required=True, help="Key ID to deactivate")

    # stats
    p_stats = subparsers.add_parser("stats", help="Show check statistics")
    p_stats.add_argument("--key-id", type=int, default=None, help="Filter by key ID")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == "create":
        asyncio.run(create_key(args.name, args.school_id, args.rate_limit, args.limit))
    elif args.command == "create-school":
        asyncio.run(create_school(args.name, args.email, args.contact))
    elif args.command == "list":
        asyncio.run(list_keys())
    elif args.command == "list-schools":
        asyncio.run(list_schools())
    elif args.command == "deactivate":
        asyncio.run(deactivate_key(args.key_id))
    elif args.command == "stats":
        asyncio.run(show_stats(args.key_id))


if __name__ == "__main__":
    main()
