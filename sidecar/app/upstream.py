def connect(settings, db_key: str = "hub", statement_timeout_ms: int = 5000):
    if db_key == "dspace":
        dbname = settings.upstream_dspace_dbname
        user = settings.upstream_dspace_user
        password = settings.upstream_dspace_password
    else:
        dbname = settings.upstream_hub_dbname
        user = settings.upstream_hub_user
        password = settings.upstream_hub_password
    if not all([settings.upstream_db_host, dbname, user, password]):
        raise RuntimeError("UPSTREAM_* incomplete")
    import psycopg2

    conn = psycopg2.connect(
        host=settings.upstream_db_host,
        port=settings.upstream_db_port,
        dbname=dbname,
        user=user,
        password=password,
        connect_timeout=settings.upstream_connect_timeout,
    )
    conn.autocommit = True
    # ponytail: PgBouncer (6432) rejects startup `options=`; SET on the session instead
    ms = int(statement_timeout_ms)
    ms = 1000 if ms < 1000 else 120000 if ms > 120000 else ms
    with conn.cursor() as cur:
        cur.execute("SET default_transaction_read_only = on")
        cur.execute(f"SET statement_timeout = {ms}")
    return conn
