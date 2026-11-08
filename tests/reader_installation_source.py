"""Native reader installation regression; caller supplies an isolated connection.

No DSN, driver import, automatic connection, commit, or production permission change.
The caller must provide the dedicated modkit_w01_owner and modkit_runtime fixture roles.
"""

FUNCTIONS = (
    "modkit_workers.w02(uuid)",
    "modkit_workers.w04(uuid,text,bytea,bytea,bytea,bytea,bytea)",
)


def snapshot(connection):
    """Full definitions and privilege rows for the two fixture readers."""
    functions = connection.execute(
        "SELECT p.oid, p.proacl::text, pg_catalog.pg_get_functiondef(p.oid) "
        "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace "
        "WHERE n.nspname='modkit_workers' AND p.proname IN ('w02','w04') ORDER BY p.oid"
    ).fetchall()
    defaults = connection.execute("SELECT * FROM pg_catalog.pg_default_acl ORDER BY oid").fetchall()
    return functions, defaults


def check_default_acl_rejected(connection, reader_sql):
    """Unsafe installer defaults must raise PZ011, with all test DDL rolled back."""
    assert connection.autocommit is True
    before = snapshot(connection)
    rejected = False
    try:
        connection.execute("BEGIN ISOLATION LEVEL READ COMMITTED")
        connection.execute("SET LOCAL ROLE modkit_w01_owner")
        for identity in FUNCTIONS:
            connection.execute("DROP FUNCTION " + identity)
        connection.execute("ALTER DEFAULT PRIVILEGES GRANT EXECUTE ON FUNCTIONS TO modkit_runtime")
        try:
            connection.execute(reader_sql, prepare=False)
        except Exception as error:
            if getattr(error, "sqlstate", None) != "PZ011":
                raise
            rejected = True
    finally:
        connection.rollback()
    assert snapshot(connection) == before, "Installation regression leaked DDL or privileges"
    assert rejected, "Reader installation accepted an unexpected non-owner default EXECUTE grant"
