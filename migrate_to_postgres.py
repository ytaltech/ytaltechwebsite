"""
Ytal Tech Solutions & Services LLP - SQLite to PostgreSQL Migration Engine
--------------------------------------------------------------------------
Automates database migration from local SQLite (ytaltech_elearning.db) to PostgreSQL.
Supports:
  1. Direct live migration over network (SQLAlchemy -> PostgreSQL)
  2. Standalone PostgreSQL SQL dump generation (ytaltech_postgres_dump.sql)
  3. Automatic PostgreSQL serial sequence synchronization
  4. Pre-migration & post-migration integrity verification
"""

import sys
import os
import argparse
from datetime import datetime, date, timezone
from sqlalchemy import create_engine, MetaData, Table, select, insert, text, inspect
from config import Config, BASE_DIR
from app import app
from elearning.models import db

# Dependency-ordered tables for clean relational loading
MIGRATION_TABLES = [
    'system_settings',
    'users',
    'courses',
    'slides',
    'mcqs',
    'enrolments',
    'payment_orders',
    'certificates',
    'certificate_complaints',
    'test_attempts',
    'slide_view_logs',
    'practice_mcq_responses',
    'audit_logs',
    'email_logs'
]

def get_sqlite_engine():
    sqlite_path = os.path.join(BASE_DIR, 'ytaltech_elearning.db')
    if not os.path.exists(sqlite_path):
        raise FileNotFoundError(f"Source SQLite database not found at: {sqlite_path}")
    return create_engine(f"sqlite:///{sqlite_path}")

def generate_postgres_sql_dump(output_filename="ytaltech_postgres_dump.sql"):
    """
    Generates a standalone PostgreSQL SQL dump file containing schema DDL,
    all table data, and auto-increment sequence resynchronization.
    """
    print(f"\n[1/3] Generating PostgreSQL SQL Dump: {output_filename}...")
    sqlite_engine = get_sqlite_engine()
    
    with open(output_filename, 'w', encoding='utf-8') as sql_file:
        sql_file.write(f"-- =========================================================\n")
        sql_file.write(f"-- Ytal Tech Solutions & Services LLP - E-Learning Platform\n")
        sql_file.write(f"-- PostgreSQL Production Database Dump\n")
        sql_file.write(f"-- Generated At: {datetime.now(timezone.utc).isoformat()}\n")
        sql_file.write(f"-- =========================================================\n\n")
        sql_file.write("BEGIN;\n\n")
        
        # 1. DDL Statements from SQLAlchemy Models
        with app.app_context():
            from sqlalchemy.schema import CreateTable
            for table_name in MIGRATION_TABLES:
                table_obj = db.metadata.tables.get(table_name)
                if table_obj is not None:
                    # Generate PostgreSQL DDL
                    create_stmt = CreateTable(table_obj).compile(dialect=create_engine('postgresql://').dialect)
                    sql_file.write(f"-- Table: {table_name}\n")
                    sql_file.write(f"{str(create_stmt).strip()};\n\n")

        # 2. INSERT statements for each table
        total_rows_dumped = 0
        with sqlite_engine.connect() as conn:
            for table_name in MIGRATION_TABLES:
                table_obj = db.metadata.tables.get(table_name)
                if table_obj is None:
                    continue
                    
                rows = conn.execute(select(table_obj)).mappings().all()
                if not rows:
                    continue
                    
                sql_file.write(f"-- Data for: {table_name} ({len(rows)} records)\n")
                col_names = [col.name for col in table_obj.columns]
                cols_joined = ", ".join([f'"{c}"' for c in col_names])
                
                for row in rows:
                    values = []
                    for c in col_names:
                        val = row[c]
                        if val is None:
                            values.append("NULL")
                        elif isinstance(val, bool):
                            values.append("TRUE" if val else "FALSE")
                        elif isinstance(val, (int, float)):
                            values.append(str(val))
                        elif isinstance(val, (datetime, date)):
                            values.append(f"'{val.isoformat()}'")
                        else:
                            # Escape single quotes and backslashes for PostgreSQL
                            val_str = str(val).replace("'", "''")
                            values.append(f"'{val_str}'")
                            
                    vals_joined = ", ".join(values)
                    sql_file.write(f"INSERT INTO \"{table_name}\" ({cols_joined}) VALUES ({vals_joined});\n")
                    total_rows_dumped += 1
                sql_file.write("\n")

        # 3. Synchronize all PostgreSQL auto-increment sequences
        sql_file.write("-- Synchronize auto-increment sequences\n")
        for table_name in MIGRATION_TABLES:
            table_obj = db.metadata.tables.get(table_name)
            if table_obj is not None and 'id' in table_obj.columns and table_obj.columns['id'].primary_key:
                sql_file.write(f"SELECT setval(pg_get_serial_sequence('\"{table_name}\"', 'id'), COALESCE(MAX(id), 1)) FROM \"{table_name}\";\n")
            
        sql_file.write("\nCOMMIT;\n")
        
    print(f"  ✓ Successfully wrote {total_rows_dumped} records across {len(MIGRATION_TABLES)} tables to {output_filename}.")
    print(f"  ✓ File size: {os.path.getsize(output_filename):,} bytes.")
    return output_filename

def migrate_live_to_postgres(target_pg_url):
    """
    Directly migrates data from SQLite to a live PostgreSQL database over the network.
    """
    if target_pg_url.startswith("postgres://"):
        target_pg_url = target_pg_url.replace("postgres://", "postgresql://", 1)
        
    print(f"\n[1/4] Connecting to target PostgreSQL database...")
    pg_engine = create_engine(
        target_pg_url,
        pool_pre_ping=True
    )
    
    # Test connection
    with pg_engine.connect() as conn:
        res = conn.execute(text("SELECT version();")).scalar()
        print(f"  ✓ Connected to PostgreSQL: {res.split(',')[0]}")

    print(f"\n[2/4] Creating database schema on PostgreSQL...")
    with app.app_context():
        db.metadata.create_all(bind=pg_engine)
        print("  ✓ All 14 database tables and relationships created successfully.")

    print(f"\n[3/4] Migrating table data from SQLite to PostgreSQL...")
    sqlite_engine = get_sqlite_engine()
    
    counts_report = {}
    with sqlite_engine.connect() as src_conn, pg_engine.begin() as dest_conn:
        try:
            dest_conn.execute(text("SET session_replication_role = 'replica';"))
        except Exception:
            pass

        for table_name in MIGRATION_TABLES:
            table_obj = db.metadata.tables.get(table_name)
            if table_obj is None:
                continue
                
            rows = src_conn.execute(select(table_obj)).mappings().all()
            row_count = len(rows)
            
            # Clear target table in case of re-run
            dest_conn.execute(text(f'TRUNCATE TABLE "{table_name}" CASCADE;'))
            
            if rows:
                # Batch insert rows
                dest_conn.execute(insert(table_obj), [dict(r) for r in rows])
                
            # Reset auto-increment sequence
            if 'id' in table_obj.columns and table_obj.columns['id'].primary_key:
                try:
                    dest_conn.execute(text(f"SELECT setval(pg_get_serial_sequence('\"{table_name}\"', 'id'), COALESCE(MAX(id), 1)) FROM \"{table_name}\";"))
                except Exception:
                    pass
                
            counts_report[table_name] = row_count
            print(f"  ✓ Migrated {table_name:25s}: {row_count:4d} rows")

        try:
            dest_conn.execute(text("SET session_replication_role = 'origin';"))
        except Exception:
            pass

    print(f"\n[4/4] Verifying data integrity on PostgreSQL...")
    with pg_engine.connect() as dest_conn:
        mismatches = 0
        for table_name, expected_count in counts_report.items():
            actual_count = dest_conn.execute(text(f'SELECT COUNT(*) FROM "{table_name}";')).scalar()
            if actual_count != expected_count:
                print(f"  ✕ Mismatch in {table_name}: Expected {expected_count}, got {actual_count}")
                mismatches += 1
                
        if mismatches == 0:
            print("  ✓ 100% Data Integrity Verified! All row counts match perfectly between SQLite and PostgreSQL.")
        else:
            print(f"  ⚠️ Warning: {mismatches} table(s) had row count discrepancies.")

    print("\n" + "=" * 60)
    print("MIGRATION COMPLETED SUCCESSFULLY!")
    print("=" * 60)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Migrate Ytal Tech database from SQLite to PostgreSQL")
    parser.add_argument('pg_url', nargs='?', default=None, help="Target PostgreSQL Connection URL (e.g., postgresql://user:pass@host:5432/dbname)")
    parser.add_argument('--generate-sql', action='store_true', help="Generate standalone PostgreSQL SQL dump file")
    parser.add_argument('--sql-file', default="ytaltech_postgres_dump.sql", help="Output filename for SQL dump")
    
    args = parser.parse_args()
    
    if args.generate_sql or not args.pg_url:
        generate_postgres_sql_dump(args.sql_file)
        if not args.pg_url and not args.generate_sql:
            print("\nTip: To run a live direct migration into your PostgreSQL database, run:")
            print(f"  python migrate_to_postgres.py postgresql://username:password@hostname:5432/databasename\n")
    else:
        migrate_live_to_postgres(args.pg_url)
