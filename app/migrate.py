"""Tiny, safe auto-migrations for columns create_all can't add.

`Base.metadata.create_all` creates new TABLES but never adds new COLUMNS to a
table that already exists. When we add a column to an existing model, we add a
one-line guarded ALTER here. Each runs only if the column is missing, so it's
safe to run on every deploy and never touches existing data.

Keep these minimal — for anything bigger, use Alembic.
"""
from sqlalchemy import text, inspect

from app.database import engine


def _column_exists(conn, table, column):
    insp = inspect(conn)
    try:
        cols = [c["name"] for c in insp.get_columns(table)]
    except Exception:
        return True  # table missing → create_all handles it; skip the ALTER
    return column in cols


def _add_column(conn, table, column, ddl_type):
    if not _column_exists(conn, table, column):
        conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {ddl_type}'))
        print(f"[migrate] added {table}.{column}")


def run_migrations():
    try:
        with engine.begin() as conn:
            # users.photo — admin profile photo (added after first deploy)
            _add_column(conn, "users", "photo", "VARCHAR(255)")
            # wallet_transactions: our txn id + method + PayU ref (detailed history)
            _add_column(conn, "wallet_transactions", "ref", "VARCHAR(40)")
            _add_column(conn, "wallet_transactions", "method", "VARCHAR(20)")
            _add_column(conn, "wallet_transactions", "payu_ref", "VARCHAR(64)")
            # messages: WhatsApp-style deletion flags
            _add_column(conn, "messages", "deleted_for_all", "BOOLEAN DEFAULT FALSE")
            _add_column(conn, "messages", "deleted_for", "TEXT")
    except Exception as e:
        print(f"[migrate] skipped: {e}")
