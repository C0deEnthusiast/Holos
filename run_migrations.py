"""
Holos Migration Runner — v2
Runs SQL migration files against Supabase via direct Postgres connection.

Usage:
    python run_migrations.py                  # run all pending
    python run_migrations.py --dry-run        # print SQL only
    python run_migrations.py --file 001       # run specific file
"""
import os
import sys
import glob
import argparse
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# Supabase Direct Postgres URL
# Format: postgresql://postgres:[SERVICE_ROLE_KEY]@db.[PROJECT_REF].supabase.co:5432/postgres
# The project ref is the subdomain of your SUPABASE_URL
def get_db_url() -> str | None:
    supabase_url = os.getenv("SUPABASE_URL", "")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    db_url = os.getenv("DATABASE_URL", "")

    if db_url:
        return db_url

    if supabase_url and service_key:
        # Extract project ref: https://zzyqoerfvarvpsdkapjg.supabase.co → zzyqoerfvarvpsdkapjg
        project_ref = supabase_url.replace("https://", "").split(".")[0]
        return f"postgresql://postgres.{project_ref}:{service_key}@aws-0-us-east-1.pooler.supabase.com:6543/postgres"

    return None


def run_migrations(dry_run: bool = False, file_filter: str | None = None) -> None:
    sql_files = sorted(glob.glob(str(MIGRATIONS_DIR / "*.sql")))

    if file_filter:
        sql_files = [f for f in sql_files if file_filter in Path(f).name]

    if not sql_files:
        print("No migration files found.")
        return

    db_url = get_db_url()

    if dry_run:
        print("=== DRY RUN — SQL that would be executed ===\n")
        for path in sql_files:
            print(f"\n--- {Path(path).name} ---")
            print(Path(path).read_text(encoding='utf-8'))
        return

    if not db_url:
        _print_manual_instructions(sql_files)
        return

    try:
        import psycopg2  # type: ignore[import]
        print(f"Connecting to Supabase Postgres...")
        conn = psycopg2.connect(db_url, connect_timeout=10)
        conn.autocommit = True
        cur = conn.cursor()

        for path in sql_files:
            name = Path(path).name
            sql = Path(path).read_text(encoding='utf-8')
            print(f"\n▶ Running {name}...", end=" ")
            try:
                cur.execute(sql)
                print("✅ OK")
            except Exception as e:
                print(f"❌ ERROR: {e}")
                if input("Continue? [y/N]: ").lower() != "y":
                    break

        cur.close()
        conn.close()
        print("\n✅ Migrations complete.")

    except ImportError:
        print("psycopg2 not installed. Installing...")
        os.system(f"{sys.executable} -m pip install psycopg2-binary")
        print("Please re-run: python run_migrations.py")
    except Exception as e:
        print(f"Connection failed: {e}")
        print("\nFalling back to manual instructions...\n")
        _print_manual_instructions(sql_files)


def _print_manual_instructions(sql_files: list[str]) -> None:
    print("=" * 60)
    print("MANUAL MIGRATION — Supabase SQL Editor")
    print("=" * 60)
    print("\n1. Open: https://supabase.com/dashboard/project/zzyqoerfvarvpsdkapjg/sql/new")
    print("2. Paste and run each SQL block below in order:\n")

    for path in sql_files:
        name = Path(path).name
        sql = Path(path).read_text(encoding='utf-8')
        print("\n" + "-" * 60)
        print(f"-- FILE: {name}")
        print("-" * 60)
        print(sql)

    print("\n" + "=" * 60)
    print("After running all SQL blocks, your schema will be up to date.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Holos Migration Runner")
    parser.add_argument("--dry-run", action="store_true", help="Print SQL without executing")
    parser.add_argument("--file", help="Run only migrations matching this string")
    args = parser.parse_args()

    run_migrations(dry_run=args.dry_run, file_filter=args.file)
