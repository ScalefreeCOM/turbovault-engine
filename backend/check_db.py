import sqlite3
import os

db_path = 'db.sqlite3'
if not os.path.exists(db_path):
    print(f"Error: {db_path} not found in {os.getcwd()}")
else:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("--- ALL TABLES IN DATABASE ---")
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
    tables = [r[0] for r in cursor.fetchall()]
    for table in tables:
        print(f"  - {table}")
        
    print("\n--- ENGINE MIGRATIONS APPLIED (FROM django_migrations) ---")
    try:
        cursor.execute("SELECT name FROM django_migrations WHERE app='engine' ORDER BY name;")
        migrations = [r[0] for r in cursor.fetchall()]
        if not migrations:
            print("  (None found for app 'engine')")
        for name in migrations:
            print(f"  - {name}")
    except sqlite3.OperationalError as e:
        print(f"  Error reading migrations: {e}")
        
    conn.close()
