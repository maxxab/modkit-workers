"""Fresh Actions-only Workers composition checks, never a deployment runner.

The credentials below are public, disposable fixture values. No existing account,
connection string, native authorization packet, or secret is accepted.
"""

import importlib.metadata
import json
import os
import sys
from pathlib import Path

DATABASE = "modkit_workers_ci"
PASSWORD = "modkit-ci-public-fixture-only"
LOGIN_ROLES = {
    "modkit_ci_bootstrap": None,
    "modkit_ci_owner_login": "modkit_owner",
    "modkit_ci_runtime_login": "modkit_runtime",
    "modkit_ci_reconciler_login": "modkit_reconciler",
    "modkit_ci_operator_login": "modkit_operator",
}
WORKER_SIGNATURES = {
    "modkit_workers.w01(uuid,text,bytea,bytea,bytea,bytea,bytea,int4,bytea,bytea,bytea,bytea,bytea,bytea,bytea,bytea,text,int4,timestamptz,timestamptz,text,bytea,bytea,bytea,bytea,timestamptz,bytea,text,bytea)": 1,
    "modkit_workers.w02(uuid)": 3,
    "modkit_workers.w03(bytea,timestamptz,uuid,int4)": 3,
    "modkit_workers.w03(bytea,timestamptz,uuid,int4,int8)": 3,
    "modkit_workers.w04(uuid,text,bytea,bytea,bytea,bytea,bytea)": 3,
    "modkit_workers.w05(bytea,bytea[],int4[],int4,float8,uuid,int4)": 1,
    "modkit_workers.w05(bytea,bytea[],int4[],int4,float8,uuid,int4,int8)": 1,
}


def require_ci_environment(env):
    expected = {
        "GITHUB_ACTIONS": "true",
        "RUNNER_ENVIRONMENT": "github-hosted",
        "GITHUB_REPOSITORY": "maxxab/modkit-workers",
        "MODKIT_POSTGRES_TEST": "workers-composition-v1",
    }
    if any(env.get(key) != value for key, value in expected.items()):
        raise ValueError("explicit synthetic GitHub CI context required")
    if any(key.startswith("PG") for key in env):
        raise ValueError("existing PostgreSQL environment must not be inherited")


def connection_options(login):
    if login not in LOGIN_ROLES:
        raise ValueError("unknown fixture login")
    return {
        "host": "127.0.0.1",
        "hostaddr": "127.0.0.1",
        "port": 5432,
        "dbname": DATABASE,
        "user": login,
        "password": PASSWORD,
        "connect_timeout": 5,
        "passfile": "/dev/null",
        "sslmode": "disable",
        "options": "-c statement_timeout=10000 -c lock_timeout=2000 -c idle_in_transaction_session_timeout=15000 -c timezone=UTC",
        "autocommit": True,
    }


def validate_target(row, roles, schemas, objects):
    if not (
        len(row) == 4
        and type(row[0]) is int
        and 170000 <= row[0] < 180000
        and row[1:] == (DATABASE, "modkit_ci_bootstrap", "modkit_ci_bootstrap")
        and roles == ["modkit_ci_bootstrap"]
        and schemas == []
        and objects == []
    ):
        raise ValueError("fresh synthetic PostgreSQL 17 target required")


def bootstrap(psycopg):
    with psycopg.connect(**connection_options("modkit_ci_bootstrap")) as connection:
        row = connection.execute(
            "SELECT current_setting('server_version_num')::int, current_database(), session_user, current_user"
        ).fetchone()
        roles = [
            r[0]
            for r in connection.execute(
                "SELECT rolname FROM pg_roles WHERE rolname !~ '^pg_' ORDER BY rolname"
            )
        ]
        schemas = [
            r[0]
            for r in connection.execute(
                "SELECT nspname FROM pg_namespace WHERE nspname !~ '^pg_' AND nspname NOT IN ('public','information_schema') ORDER BY nspname"
            )
        ]
        objects = connection.execute(
            "SELECT 'relation',relname::text FROM pg_class WHERE relnamespace='public'::regnamespace "
            "UNION ALL SELECT 'function',proname::text FROM pg_proc WHERE pronamespace='public'::regnamespace "
            "UNION ALL SELECT 'type',typname::text FROM pg_type WHERE typnamespace='public'::regnamespace "
            "ORDER BY 1,2"
        ).fetchall()
        validate_target(row, roles, schemas, objects)
        with connection.transaction():
            connection.execute("REVOKE ALL ON DATABASE modkit_workers_ci FROM PUBLIC")
            for login, role in LOGIN_ROLES.items():
                if role is None:
                    continue
                connection.execute(
                    psycopg.sql.SQL(
                        "CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
                    ).format(psycopg.sql.Identifier(role))
                )
                connection.execute(
                    psycopg.sql.SQL(
                        "CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
                    ).format(psycopg.sql.Identifier(login), psycopg.sql.Literal(PASSWORD))
                )
                connection.execute(
                    psycopg.sql.SQL("GRANT {} TO {} WITH INHERIT FALSE, SET TRUE").format(
                        psycopg.sql.Identifier(role), psycopg.sql.Identifier(login)
                    )
                )
                connection.execute(
                    psycopg.sql.SQL("GRANT CONNECT ON DATABASE modkit_workers_ci TO {}").format(
                        psycopg.sql.Identifier(login)
                    )
                )
            connection.execute("GRANT CREATE ON DATABASE modkit_workers_ci TO modkit_owner")
    print("PASS fresh PostgreSQL 17 fixture bootstrap; privileged connection closed")


def selected_role(connection, psycopg, login):
    role = LOGIN_ROLES[login]
    connection.execute(psycopg.sql.SQL("SET LOCAL ROLE {}").format(psycopg.sql.Identifier(role)))
    assert connection.execute("SELECT session_user, current_user").fetchone() == (login, role)
    flags = connection.execute(
        "SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=session_user"
    ).fetchone()
    assert flags == (False,) * 5


def validate_pair(event, worker, expected_digest):
    if not (
        event.component == "events"
        and event.version == 1
        and worker.component == "workers"
        and worker.version == 1
        and isinstance(expected_digest, str)
        and len(expected_digest) == 64
        and event.migration_digest == expected_digest
        and len(worker.depends_on) == 1
        and worker.depends_on[0].component == "events"
        and worker.depends_on[0].version == event.version
        and worker.depends_on[0].migration_digest == expected_digest
    ):
        raise ValueError("exact Events dependency required")


def receipt_values(migration):
    return (
        migration.component,
        migration.version,
        bytes.fromhex(migration.migration_digest),
        migration.catalog_contract_id,
        migration.scope_format_id,
        migration.intent_format_id,
    )


def install_component(connection, psycopg, migration, statements, receipt):
    selected_role(connection, psycopg, "modkit_ci_owner_login")
    for statement in statements:
        connection.execute(statement, prepare=False)
    values = receipt_values(migration)
    before = connection.execute("SELECT clock_timestamp()").fetchone()[0]
    with psycopg.RawCursor(connection) as cursor:
        cursor.execute(receipt, values)
    row = connection.execute(
        "SELECT component,version,migration_digest,catalog_contract_id,scope_format_id,intent_format_id,applied_at FROM modkit_events.schema_versions WHERE component=%s",
        (migration.component,),
    ).fetchone()
    after = connection.execute("SELECT clock_timestamp()").fetchone()[0]
    assert row[:6] == values and before <= row[6] <= after
    return values


def observer_state(psycopg):
    with psycopg.connect(**connection_options("modkit_ci_owner_login")) as observer:
        with observer.transaction():
            selected_role(observer, psycopg, "modkit_ci_owner_login")
            schemas = observer.execute(
                "SELECT to_regnamespace('modkit_events') IS NOT NULL, to_regnamespace('modkit_workers') IS NOT NULL"
            ).fetchone()
            rows = []
            if schemas[0]:
                rows = observer.execute(
                    "SELECT component,version,migration_digest,catalog_contract_id,scope_format_id,intent_format_id FROM modkit_events.schema_versions ORDER BY component"
                ).fetchall()
            return schemas, rows


def refuse_without_events(connection, psycopg, initial):
    assert observer_state(psycopg) == ((False, False), [])
    try:
        with connection.transaction():
            selected_role(connection, psycopg, "modkit_ci_owner_login")
            assert (
                connection.execute(
                    "SELECT rolcanlogin,rolsuper,rolbypassrls,rolcreaterole,rolcreatedb,rolreplication FROM pg_roles WHERE rolname=current_user"
                ).fetchone()
                == (False,) * 6
            )
            assert connection.execute(
                "SELECT has_database_privilege(current_user,current_database(),'CREATE')"
            ).fetchone() == (True,)
            connection.execute(initial, prepare=False)
            raise AssertionError("Workers unexpectedly installed without Events")
    except psycopg.Error as error:
        assert (
            error.sqlstate == "PZ011"
            and error.diag.message_primary == "invalid structural owner or namespace"
        )
    assert observer_state(psycopg) == ((False, False), [])
    print("PASS missing Events dependency refused under verified owner and acknowledged rollback")


def worker_inventory(connection):
    expected = {}
    for signature, roles in WORKER_SIGNATURES.items():
        oid = connection.execute("SELECT to_regprocedure(%s)::oid", (signature,)).fetchone()[0]
        assert oid is not None
        expected[oid] = roles
    actual = connection.execute(
        "SELECT oid,prosecdef,prorettype='record'::regtype,prokind,pg_get_userbyid(proowner),proconfig FROM pg_proc WHERE pronamespace='modkit_workers'::regnamespace"
    ).fetchall()
    assert len(expected) == 7 and {row[0] for row in actual} == set(expected)
    for row in actual:
        assert row[1:] == (True, True, "f", "modkit_owner", ["search_path=pg_catalog, pg_temp"])
    return expected


class RollbackProbe(Exception):
    """Deliberate, acknowledged rollback, never an uncertain-error retry."""


def denied(connection, psycopg, statement):
    try:
        with connection.transaction():
            connection.execute(statement)
            raise AssertionError("forbidden operation unexpectedly succeeded")
    except psycopg.Error as error:
        assert error.sqlstate == "42501", error.sqlstate


def check_readiness_receipts(connection, event_values, worker_values):
    for profile, expected in (
        ("events", [event_values]),
        ("workers", [event_values, worker_values]),
    ):
        assert (
            connection.execute("SELECT * FROM modkit_events.e33(%s)", (profile,)).fetchall()
            == expected
        )


def restricted_checks(psycopg, event_values, worker_values):
    for login, role in LOGIN_ROLES.items():
        if role not in {"modkit_runtime", "modkit_reconciler", "modkit_operator"}:
            continue
        with psycopg.connect(**connection_options(login)) as connection:
            with connection.transaction():
                selected_role(connection, psycopg, login)
                inventory = worker_inventory(connection)
                for oid, role_count in inventory.items():
                    allowed = role_count == 3 or role == "modkit_runtime"
                    assert connection.execute(
                        "SELECT has_function_privilege(current_user,%s,'EXECUTE')", (oid,)
                    ).fetchone() == (allowed,)
                check_readiness_receipts(connection, event_values, worker_values)
                assert (
                    connection.execute(
                        "SELECT * FROM modkit_workers.w02('00000000-0000-0000-0000-000000000001'::uuid)"
                    ).fetchall()
                    == []
                )
                assert connection.execute(
                    "SELECT has_schema_privilege(current_user,'modkit_workers','USAGE'),has_schema_privilege(current_user,'modkit_workers','CREATE')"
                ).fetchone() == (True, False)
                assert connection.execute(
                    "SELECT count(*) FROM pg_class WHERE relnamespace IN ('modkit_events'::regnamespace,'modkit_workers'::regnamespace) AND relkind='r' AND (has_table_privilege(current_user,oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') OR has_any_column_privilege(current_user,oid,'SELECT,INSERT,UPDATE,REFERENCES'))"
                ).fetchone() == (0,)
                for query in (
                    "SELECT * FROM modkit_events.schema_versions",
                    "INSERT INTO modkit_events.schema_versions DEFAULT VALUES",
                    "SELECT work_id FROM modkit_events.work",
                    "CREATE TABLE modkit_workers.ci_forbidden(value integer)",
                    "SELECT modkit_events._utf8_valid(''::bytea,1,false)",
                    "SET ROLE modkit_owner",
                    "SET ROLE modkit_ci_bootstrap",
                ):
                    denied(connection, psycopg, query)
                if role != "modkit_runtime":
                    denied(
                        connection,
                        psycopg,
                        "SELECT * FROM modkit_workers.w01(" + ",".join(["NULL"] * 29) + ")",
                    )
        print("PASS Workers restricted-role signature matrix/read/deny checks:", role)


def main():
    require_ci_environment(os.environ)
    if (
        len(sys.argv) != 1
        or not sys.flags.isolated
        or sys.flags.optimize
        or sys.platform != "linux"
        or tuple(sys.version_info[:3]) != (3, 13, 5)
    ):
        raise ValueError("isolated non-optimized Linux Python 3.13.5 without arguments required")
    import modkit_events
    import psycopg
    from modkit_events.persistence import migrations as events

    import modkit_workers
    from modkit_workers.persistence import migrations as workers

    prefix = Path(sys.prefix).resolve()
    assert sys.prefix != sys.base_prefix
    for module, name, version in (
        (modkit_events, "modkit-events", "0.2.0"),
        (modkit_workers, "modkit-workers", "0.1.0"),
    ):
        assert Path(module.__file__).resolve().is_relative_to(prefix)
        assert importlib.metadata.version(name) == version
    assert psycopg.__version__ == "3.3.8"
    (event,), (worker,) = events.manifest(), workers.manifest()
    expected = json.loads(Path("ci_dependency.json").read_text())
    validate_pair(event, worker, expected["migration_digest"])
    event_sql = [events.read_sql(event, resource) for resource in event.resources]
    worker_sql = [workers.read_sql(worker, resource) for resource in worker.resources]
    for migration in (event, worker):
        assert [resource.path.rsplit("/", 1)[1] for resource in migration.resources] == [
            "0001_initial.sql",
            "grants_runtime.sql",
        ]
    receipt = events.read_owner_receipt(event)
    bootstrap(psycopg)
    with psycopg.connect(**connection_options("modkit_ci_owner_login")) as connection:
        refuse_without_events(connection, psycopg, worker_sql[0])
        with connection.transaction():
            event_values = install_component(connection, psycopg, event, event_sql, receipt)
        baseline = ((True, False), [event_values])
        assert observer_state(psycopg) == baseline
        try:
            with connection.transaction():
                install_component(connection, psycopg, worker, worker_sql, receipt)
                worker_inventory(connection)
                raise RollbackProbe
        except RollbackProbe:
            pass
        assert observer_state(psycopg) == baseline
        print(
            "PASS Workers complete installation/grants/receipt rolled back with Events receipt preserved"
        )
        with connection.transaction():
            worker_values = install_component(connection, psycopg, worker, worker_sql, receipt)
            worker_inventory(connection)
            assert observer_state(psycopg) == baseline
            try:
                with connection.transaction():
                    with psycopg.RawCursor(connection) as cursor:
                        cursor.execute(receipt, worker_values)
                    raise AssertionError("duplicate Workers receipt unexpectedly succeeded")
            except psycopg.errors.UniqueViolation:
                pass
            assert connection.execute(
                "SELECT count(*) FROM modkit_events.schema_versions"
            ).fetchone() == (2,)
        assert observer_state(psycopg) == ((True, True), [event_values, worker_values])
    restricted_checks(psycopg, event_values, worker_values)
    print(
        "PASS synthetic installed Workers-over-Events composition; migration:",
        worker.migration_digest,
    )
    print(
        "Not managed native transport, job runtime, recovery/fault, deployment or release qualification."
    )


if __name__ == "__main__":
    main()
