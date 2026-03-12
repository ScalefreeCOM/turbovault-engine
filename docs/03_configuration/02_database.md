---
sidebar_position: 6
sidebar_label: Backend Database Config
title: Backend Database Config
---

# Database Configuration Guide

This guide explains how to configure TurboVault Engine to use external databases like PostgreSQL, MySQL, SQL Server, or Oracle instead of the default SQLite.

## Overview

### Why Use an External Database?

By default, TurboVault Engine uses **SQLite**, which is perfect for:
- Local development and testing
- Single-user scenarios
- Quick prototyping

Consider using an **external database** (PostgreSQL, MySQL, etc.) when you need:
- **Multi-user access** - Multiple team members working simultaneously
- **Production deployment** - Better performance and reliability
- **Data persistence** - Centralized database server
- **Advanced features** - Full-text search, complex queries, better concurrency
- **Integration** - Connecting to existing database infrastructure

### Supported Databases

TurboVault supports all Django-compatible database backends:

| Database | Engine Value | Status | Recommended Driver |
|----------|-------------|--------|-------------------|
| **SQLite** | `sqlite3` | ✅ Default | Built-in (no installation needed) |
| **PostgreSQL** | `postgresql` | ✅ Fully Supported | `psycopg2-binary` |
| **MySQL/MariaDB** | `mysql` | ✅ Fully Supported | `mysqlclient` |
| **SQL Server** | `mssql` | ✅ Supported | `mssql-django` |
| **Oracle** | `oracle` | ✅ Supported | `cx_Oracle` |
| **Snowflake** | `snowflake` | ✅ Supported | `django-snowflake` |

---

## Configuration

### Basic Configuration Structure

Add a `database` section to your `turbovault.yml`:

```yaml
database:
  engine: postgresql          # Database type
  name: turbovault_db        # Database name
  user: turbovault_user      # Database username
  password: your_password    # Database password
  host: localhost            # Database host
  port: 5432                 # Database port (optional)
  options:                   # Additional options (optional)
    sslmode: require
```

### Configuration Fields

| Field | Required | Description | Example |
|-------|----------|-------------|---------|
| `engine` | Yes | Database backend type | `postgresql`, `mysql`, `sqlite3` |
| `name` | Yes | Database name (or file path for SQLite) | `turbovault_db` |
| `user` | For external DBs | Database username | `turbovault_user` |
| `password` | For external DBs | Database password | `secretpassword123` |
| `host` | For external DBs | Database server hostname or IP | `localhost`, `db.example.com` |
| `port` | No | Database port (uses default if omitted) | `5432`, `3306` |
| `options` | No | Database-specific options | `{sslmode: require}` |

> **Note**: SQLite only requires `engine` and `name` (file path). All other databases require `user`, `password`, and `host`.

---

## Database Setup Examples

### PostgreSQL

#### 1. Install PostgreSQL Driver

```bash
pip install psycopg2-binary
```

#### 2. Create Database and User

```sql
-- Connect to PostgreSQL as superuser
psql -U postgres

-- Create database and user
CREATE DATABASE turbovault_db;
CREATE USER turbovault_user WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE turbovault_db TO turbovault_user;

-- PostgreSQL 15+ requires additional grants
\c turbovault_db
GRANT ALL ON SCHEMA public TO turbovault_user;
```

#### 3. Configure turbovault.yml

```yaml
database:
  engine: postgresql
  name: turbovault_db
  user: turbovault_user
  password: your_password
  host: localhost
  port: 5432  # Optional, 5432 is the default
  options:
    sslmode: prefer  # Options: disable, allow, prefer, require
```

#### 4. Initialize Workspace DB

```bash
turbovault workspace init --overwrite
```

---

### MySQL / MariaDB

#### 1. Install MySQL Driver

```bash
pip install mysqlclient
```

**Windows users**: If you encounter build errors, you may need:
```bash
pip install mysqlclient --only-binary :all:
```

#### 2. Create Database and User

```sql
-- Connect to MySQL as root
mysql -u root -p

-- Create database and user
CREATE DATABASE turbovault_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'turbovault_user'@'localhost' IDENTIFIED BY 'your_password';
GRANT ALL PRIVILEGES ON turbovault_db.* TO 'turbovault_user'@'localhost';
FLUSH PRIVILEGES;
```

#### 3. Configure turbovault.yml

```yaml
database:
  engine: mysql
  name: turbovault_db
  user: turbovault_user
  password: your_password
  host: localhost
  port: 3306  # Optional, 3306 is the default
  options:
    charset: utf8mb4
    init_command: "SET sql_mode='STRICT_TRANS_TABLES'"
```

---

### SQL Server

#### 1. Install SQL Server Driver

```bash
pip install mssql-django
```

You'll also need the **ODBC Driver for SQL Server**:
- **Windows**: Download from [Microsoft](https://docs.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server)
- **Linux**: Follow [Microsoft's Linux installation guide](https://docs.microsoft.com/en-us/sql/connect/odbc/linux-mac/installing-the-microsoft-odbc-driver-for-sql-server)
- **macOS**: `brew install msodbcsql17`

#### 2. Create Database and User

```sql
-- Connect to SQL Server
sqlcmd -S localhost -U sa

-- Create database and user
CREATE DATABASE turbovault_db;
GO

CREATE LOGIN turbovault_user WITH PASSWORD = 'YourPassword123!';
GO

USE turbovault_db;
CREATE USER turbovault_user FOR LOGIN turbovault_user;
ALTER ROLE db_owner ADD MEMBER turbovault_user;
GO
```

#### 3. Configure turbovault.yml

```yaml
database:
  engine: mssql
  name: turbovault_db
  user: turbovault_user
  password: YourPassword123!
  host: localhost
  port: 1433  # Optional, 1433 is the default
  options:
    driver: "ODBC Driver 17 for SQL Server"
```

---

### Oracle

#### 1. Install Oracle Driver

```bash
pip install cx_Oracle
```

You'll also need the **Oracle Instant Client**:
- Download from [Oracle](https://www.oracle.com/database/technologies/instant-client.html)
- Follow installation instructions for your OS

#### 2. Create Database and User

```sql
-- Connect as SYSDBA
sqlplus / as sysdba

-- Create user
CREATE USER turbovault_user IDENTIFIED BY your_password;
GRANT CONNECT, RESOURCE, DBA TO turbovault_user;
```

#### 3. Configure turbovault.yml

```yaml
database:
  engine: oracle
  name: xe  # Or your service name / SID
  user: turbovault_user
  password: your_password
  host: localhost
  port: 1521  # Optional, 1521 is the default
```

---

### Snowflake

#### 1. Install Snowflake Driver

```bash
pip install django-snowflake
```

#### 2. Get Snowflake Account Details

You'll need:
- **Account identifier**: Your Snowflake account name (e.g., `xy12345.us-east-1`)
- **Warehouse**: Compute warehouse name
- **Database**: Database name
- **Schema**: Schema name (e.g., `PUBLIC`)

You can create these in Snowflake:

```sql
-- Connect to Snowflake
-- Create database and schema (if not exists)
CREATE DATABASE IF NOT EXISTS turbovault_db;
CREATE SCHEMA IF NOT EXISTS turbovault_db.public;

-- Create user
CREATE USER turbovault_user 
  PASSWORD = 'your_password'
  DEFAULT_WAREHOUSE = COMPUTE_WH
  DEFAULT_NAMESPACE = turbovault_db.public;

-- Grant privileges
GRANT USAGE ON WAREHOUSE COMPUTE_WH TO USER turbovault_user;
GRANT USAGE ON DATABASE turbovault_db TO USER turbovault_user;
GRANT USAGE ON SCHEMA turbovault_db.public TO USER turbovault_user;
GRANT CREATE TABLE ON SCHEMA turbovault_db.public TO USER turbovault_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA turbovault_db.public TO USER turbovault_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON FUTURE TABLES IN SCHEMA turbovault_db.public TO USER turbovault_user;
```

#### 3. Configure turbovault.yml

```yaml
database:
  engine: snowflake
  name: turbovault_db
  user: turbovault_user
  password: your_password
  host: your_account.snowflakecomputing.com
  options:
    account: your_account  # e.g., xy12345.us-east-1
    warehouse: COMPUTE_WH
    database: TURBOVAULT_DB
    schema: PUBLIC
```

**Important Notes:**
- The `name` field is used as the database name
- `host` should be your full Snowflake account URL
- `account`, `warehouse`, `database`, and `schema` should be specified in `options`
- Snowflake identifiers are case-insensitive but typically uppercase

#### 4. Initialize Workspace DB

```bash
turbovault workspace init --overwrite
```

---

### SQLite (Advanced)

SQLite is the default, but you can explicitly configure it:

```yaml
database:
  engine: sqlite3
  name: "./data/custom.db"  # Custom path
```

**Relative paths** are resolved from the project's `backend` directory.

**Absolute paths** can also be used:
```yaml
database:
  engine: sqlite3
  name: "/var/lib/turbovault/db.sqlite3"
```

---

## Security Best Practices

### 1. Environment Variables for Credentials

**Don't commit passwords to version control!** Use environment variables instead.

Create a `.env` file (add to `.gitignore`):
```bash
DB_PASSWORD=your_secret_password
DB_USER=turbovault_user
```

Reference in `turbovault.yml`:
```yaml
database:
  engine: postgresql
  name: turbovault_db
  user: ${DB_USER}
  password: ${DB_PASSWORD}
  host: localhost
```

> **Note**: TurboVault doesn't automatically expand environment variables in YAML. You'll need to use a tool like `envsubst` or load secrets programmatically.

### 2. Separate Configuration Files

Keep production config separate:

```bash
# Development
turbovault.dev.yml

# Production (not committed)
turbovault.prod.yml
```

Use different configs per environment:
```bash
turbovault workspace init --config turbovault.dev.yml
turbovault workspace init --config turbovault.prod.yml
```

### 3. Database User Permissions

**Principle of least privilege**: Don't use superuser/admin accounts.

Create a dedicated user with only required permissions:
- `CREATE TABLE`, `ALTER TABLE`, `DROP TABLE` for migrations
- `SELECT`, `INSERT`, `UPDATE`, `DELETE` for normal operations

---

## Common Issues and Troubleshooting

### Driver Not Installed

**Error:**
```
Database driver not installed for postgresql.
  Install it with: pip install psycopg2-binary
```

**Solution**: Install the required driver for your database engine.

---

### Connection Refused

**Error:**
```
django.db.utils.OperationalError: could not connect to server
```

**Solutions**:
1. **Check database is running**: `systemctl status postgresql` (Linux)
2. **Verify host/port**: Ensure correct host and port in config
3. **Check firewall**: Allow connections on database port
4. **PostgreSQL**: Edit `postgresql.conf` to allow network connections
   ```
   listen_addresses = 'localhost'
   ```
   Edit `pg_hba.conf` to allow user connections

---

### Authentication Failed

**Error:**
```
django.db.utils.OperationalError: FATAL: password authentication failed
```

**Solutions**:
1. **Verify credentials**: Double-check username and password
2. **User doesn't exist**: Create the database user
3. **Wrong authentication method**: Check database authentication settings

---

### Database Does Not Exist

**Error:**
```
django.db.utils.OperationalError: database "turbovault_db" does not exist
```

**Solution**: Create the database first:
```sql
-- PostgreSQL
CREATE DATABASE turbovault_db;

-- MySQL
CREATE DATABASE turbovault_db;
```

---

### Permission Denied

**Error:**
```
django.db.utils.ProgrammingError: permission denied for schema public
```

**Solution** (PostgreSQL 15+):
```sql
\c turbovault_db
GRANT ALL ON SCHEMA public TO turbovault_user;
```

---

## Performance Considerations

### SQLite
- ✅ **Best for**: Development, single-user, small datasets
- ⚠️ **Limitations**: No concurrent writes, limited scalability
- **When to use**: Local testing, demos, quick prototypes

### PostgreSQL
- ✅ **Best for**: Production, multi-user, complex queries
- ✅ **Advantages**: ACID compliant, excellent performance, rich features
- **When to use**: Production deployments, team collaboration

### MySQL/MariaDB
- ✅ **Best for**: Web applications, high read loads
- ✅ **Advantages**: Fast reads, mature ecosystem
- **When to use**: Production deployments, existing MySQL infrastructure

### SQL Server
- ✅ **Best for**: Windows environments, enterprise
- ⚠️ **Note**: Requires ODBC driver installation
- **When to use**: Microsoft-centric infrastructure

### Oracle
- ✅ **Best for**: Enterprise, mission-critical systems
- ⚠️ **Note**: Requires Instant Client and cx_Oracle
- **When to use**: Existing Oracle infrastructure

### Snowflake
- ✅ **Best for**: Cloud data warehouses, large-scale analytics
- ✅ **Advantages**: Auto-scaling, separation of compute and storage, MPP architecture
- ⚠️ **Note**: Cloud-only, usage-based pricing
- **When to use**: Cloud-native deployments, data lake/warehouse scenarios

---

## Migration Between Databases

If you need to switch databases, you'll need to:

1. **Export data** from the old database:
   ```bash
   cd backend
   python manage.py dumpdata > data_backup.json
   ```

2. **Update turbovault.yml** with new database settings

3. **Run migrations** on the new database:
   ```bash
   turbovault workspace init --overwrite
   ```

4. **Import data** (if needed):
   ```bash
   cd backend
   python manage.py loaddata data_backup.json
   ```

---

## Testing Database Configuration

Test your database connection before running migrations:

```bash
# Try to connect
turbovault workspace status
```

If successful, you'll see:
```
✅ Database connection successful
✅ Running migrations...
```

---

## Advanced Configuration

### Connection Pooling (PostgreSQL)

```yaml
database:
  engine: postgresql
  name: turbovault_db
  user: turbovault_user
  password: your_password
  host: localhost
  options:
    connect_timeout: 10
    options: "-c statement_timeout=30000"
```

### SSL/TLS Connections

**PostgreSQL**:
```yaml
database:
  engine: postgresql
  name: turbovault_db
  user: turbovault_user
  password: your_password
  host: db.example.com
  options:
    sslmode: require
    sslrootcert: /path/to/ca.crt
```

**MySQL**:
```yaml
database:
  engine: mysql
  name: turbovault_db
  user: turbovault_user
  password: your_password
  host: db.example.com
  options:
    ssl:
      ca: /path/to/ca.pem
```
