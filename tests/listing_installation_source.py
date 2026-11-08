"""W03 private installation regressions; caller supplies the isolated connection."""

IDENTITY = "modkit_workers.w03(bytea,timestamptz,uuid,int4)"


def snapshot(connection):
    functions = connection.execute(
        "SELECT p.oid,p.proacl::text,pg_catalog.pg_get_functiondef(p.oid) "
        "FROM pg_catalog.pg_proc p WHERE p.oid=to_regprocedure(%s)",
        (IDENTITY,),
    ).fetchall()
    index = connection.execute(
        "SELECT i.*,c.relowner,pg_catalog.pg_get_indexdef(i.indexrelid) "
        "FROM pg_catalog.pg_index i JOIN pg_catalog.pg_class c ON c.oid=i.indexrelid "
        "WHERE i.indexrelid=to_regclass('modkit_events.work_jobs_created_page')"
    ).fetchall()
    defaults = connection.execute("SELECT * FROM pg_catalog.pg_default_acl ORDER BY oid").fetchall()
    return functions, index, defaults


def rejected(connection, listing_sql, setup):
    """Every DDL negative is rollback-only, never applied to a shared installation."""
    before = snapshot(connection)
    error = None
    cleanup = None
    applying = False
    try:
        connection.execute("BEGIN ISOLATION LEVEL READ COMMITTED")
        connection.execute("SET LOCAL ROLE modkit_w01_owner")
        connection.execute("DROP FUNCTION " + IDENTITY)
        for command in setup:
            connection.execute(command)
        applying = True
        connection.execute(listing_sql, prepare=False)
    except BaseException as caught:
        error = caught
    finally:
        try:
            connection.rollback()
        except BaseException as caught:
            cleanup = caught
    if cleanup is not None:
        errors = ([error] if error is not None else []) + [cleanup]
        raise BaseExceptionGroup("Installation regression cleanup failed", errors)
    assert snapshot(connection) == before, "Installation negative leaked DDL or privileges"
    assert error is not None, "Invalid installation was accepted"
    if (
        not applying
        or not isinstance(error, Exception)
        or getattr(error, "sqlstate", None) != "PZ011"
    ):
        raise error


def check_installation(connection, listing_sql):
    assert connection.autocommit is True
    rejected(
        connection,
        listing_sql,
        ["ALTER DEFAULT PRIVILEGES GRANT EXECUTE ON FUNCTIONS TO modkit_runtime"],
    )
    prefix = "CREATE INDEX work_jobs_created_page ON modkit_events.work "
    predicate = """ WHERE kind COLLATE pg_catalog."C" = 'job' COLLATE pg_catalog."C" """
    for definition in (
        None,
        prefix + "(created_at,namespace,work_id)" + predicate,
        prefix + "(namespace,created_at DESC,work_id)" + predicate,
        prefix + "(namespace,created_at,work_id)",  # Missing job predicate.
        prefix + "(namespace,created_at,work_id) WHERE kind='inbox'",
        prefix + "(namespace,created_at,work_id) INCLUDE (state)" + predicate,
    ):
        setup = ["DROP INDEX modkit_events.work_jobs_created_page"]
        if definition is not None:
            setup.append(definition)
        rejected(connection, listing_sql, setup)
