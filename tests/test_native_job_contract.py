"""Public native job boundaries remain import neutral and observational."""

import copy
import importlib
import importlib.util

import pytest


def module():
    assert importlib.util.find_spec("modkit_workers.native_job") is not None, (
        "native source contracts missing"
    )
    return importlib.import_module("modkit_workers.native_job")


def test_work_and_root_are_opaque_not_public_authority_constructors():
    m = module()
    for cls in (m.JobWork, m.DbLocalRoot):
        with pytest.raises(TypeError):
            cls()


def test_work_has_no_payload_and_disallows_copy():
    m = module()
    owner = object()
    w = m._issue_work(owner)
    assert not hasattr(w, "payload") and not hasattr(w, "fence")
    with pytest.raises(TypeError):
        copy.copy(w)
    with pytest.raises(TypeError):
        copy.deepcopy(w)
    assert m._owns_work(w, owner) and not m._owns_work(w, object())


def test_root_view_expires_without_mutating_observational_context():
    m = module()
    connection = object()
    root = m._issue_root(connection, 42)
    assert root.connection is connection and root.root_xid == 42
    m._expire_root(root)
    with pytest.raises(RuntimeError):
        _ = root.connection
    with pytest.raises(RuntimeError):
        _ = root.root_xid


def test_profile_assertion_is_once_pure_and_requires_none():
    m = module()
    calls = []

    class App:
        def validate_profile(self, request):
            calls.append(request)

    request = object()
    m._validate_application_profile(App(), request)
    assert calls == [request]

    class Bad:
        def validate_profile(self, request):
            return True

    with pytest.raises(ValueError):
        m._validate_application_profile(Bad(), request)


def test_profile_async_generator_and_exception_are_sanitized():
    m = module()

    class Async:
        async def validate_profile(self, request):
            return None

    class Generator:
        def validate_profile(self, request):
            yield "secret"

    class Failing:
        def validate_profile(self, request):
            raise RuntimeError("secret")

    for app in (Async(), Generator(), Failing()):
        with pytest.raises(ValueError) as caught:
            m._validate_application_profile(app, object())
        assert "secret" not in str(caught.value)
        assert caught.value.__context__ is None


def test_application_binding_authorizes_then_handler_then_projection_and_expires():
    m = module()
    from modkit_workers import _native_job_lifecycle as life

    lease = life._MaterialLease(
        capacity=1073741824, payload_limit=1048576, result_limit=1048576, depth_limit=32
    )
    lease.reserve()
    trace = []
    roots = []

    class Binding:
        def __enter__(self):
            trace.append("authorize")
            return self

        def result(self):
            trace.append("project")
            return b"done"

        def __exit__(self, *exc):
            trace.append("unbind")

    class App:
        def bind(self, root, context):
            roots.append(root)
            return Binding()

    def handler(context):
        trace.append("handler")

    outcome = m._invoke_application(App(), handler, object(), 42, object(), lease)
    assert outcome == (True, b"done")
    assert trace == ["authorize", "handler", "project", "unbind"]
    with pytest.raises(RuntimeError):
        _ = roots[0].connection


def test_business_error_cannot_be_suppressed_into_success_or_retain_exception():
    m = module()
    from modkit_workers import _native_job_lifecycle as life

    lease = life._MaterialLease(
        capacity=1073741824, payload_limit=1048576, result_limit=1048576, depth_limit=32
    )
    lease.reserve()

    class Binding:
        def __enter__(self):
            return self

        def result(self):
            raise AssertionError("must not project after failed handler")

        def __exit__(self, *exc):
            return True

    class App:
        def bind(self, root, context):
            return Binding()

    def handler(context):
        raise RuntimeError("sensitive application data")

    assert m._invoke_application(App(), handler, object(), 42, object(), lease) == (False, None)


def test_handler_return_value_is_not_durable_result():
    m = module()
    from modkit_workers import _native_job_lifecycle as life

    lease = life._MaterialLease(
        capacity=1073741824, payload_limit=1048576, result_limit=1048576, depth_limit=32
    )
    lease.reserve()

    class Binding:
        def __enter__(self):
            return self

        def result(self):
            return b"done"

        def __exit__(self, *exc):
            pass

    class App:
        def bind(self, root, context):
            return Binding()

    assert m._invoke_application(
        App(), lambda context: b"not a result", object(), 42, object(), lease
    ) == (False, None)


def test_application_baseexception_unbinds_before_unresolved_propagation():
    m = module()
    from modkit_workers import _native_job_lifecycle as life

    lease = life._MaterialLease(
        capacity=1073741824, payload_limit=1048576, result_limit=1048576, depth_limit=32
    )
    lease.reserve()
    exits = []

    class Binding:
        def __enter__(self):
            return self

        def result(self):
            return b"done"

        def __exit__(self, *exc):
            exits.append(exc[0])
            return True

    class App:
        def bind(self, root, context):
            return Binding()

    def cancelled(context):
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        m._invoke_application(App(), cancelled, object(), 42, object(), lease)
    assert exits == [KeyboardInterrupt]


def test_async_result_is_closed_and_never_becomes_success():
    m = module()
    from modkit_workers import _native_job_lifecycle as life

    lease = life._MaterialLease(
        capacity=1073741824, payload_limit=1048576, result_limit=1048576, depth_limit=32
    )
    lease.reserve()

    async def result():
        return b"not synchronous"

    coroutine = result()

    class Binding:
        def __enter__(self):
            return self

        def result(self):
            return coroutine

        def __exit__(self, *exc):
            return False

    class App:
        def bind(self, root, context):
            return Binding()

    assert m._invoke_application(App(), lambda context: None, object(), 42, object(), lease) == (
        False,
        None,
    )
    try:
        assert coroutine.cr_frame is None
    finally:
        coroutine.close()


def invalid_binding_result(kind, trace):
    if kind == "coroutine":

        async def operation():
            trace.append("async operation")

        return operation()
    if kind == "generator":

        def operation():
            trace.append("generator operation")
            yield None

        return operation()
    if kind == "awaitable":

        class Pending:
            def __await__(self):
                trace.append("awaitable operation")
                yield None

            def result(self):
                raise AssertionError("pending binding must not be used")

        return Pending()
    return 1


@pytest.mark.parametrize("stage", ["enter", "exit"])
@pytest.mark.parametrize("kind", ["coroutine", "generator", "awaitable", "invalid"])
def test_nonsynchronous_binding_rejects_before_handler_or_success(stage, kind):
    m = module()
    from modkit_workers import _native_job_lifecycle as life

    lease = life._MaterialLease(
        capacity=1073741824, payload_limit=1048576, result_limit=1048576, depth_limit=32
    )
    lease.reserve()
    trace, roots = [], []
    invalid = invalid_binding_result(kind, trace)

    class Binding:
        def __enter__(self):
            return invalid if stage == "enter" else self

        def result(self):
            return b"done"

        def __exit__(self, *exc):
            trace.append("exit")
            return invalid if stage == "exit" else None

    class App:
        def bind(self, root, context):
            roots.append(root)
            return Binding()

    try:
        assert m._invoke_application(
            App(), lambda context: trace.append("handler"), object(), 42, object(), lease
        ) == (False, None)
        assert trace == (["exit"] if stage == "enter" else ["handler", "exit"])
        if kind == "coroutine":
            assert invalid.cr_frame is None
        elif kind == "generator":
            assert invalid.gi_frame is None
        with pytest.raises(RuntimeError):
            _ = roots[0].connection
    finally:
        if kind in ("coroutine", "generator"):
            invalid.close()


@pytest.mark.parametrize("kind", ["coroutine", "generator"])
def test_nonsynchronous_unbind_is_disposed_after_handler_failure(kind):
    m = module()
    from modkit_workers import _native_job_lifecycle as life

    lease = life._MaterialLease(
        capacity=1073741824, payload_limit=1048576, result_limit=1048576, depth_limit=32
    )
    lease.reserve()
    trace = []
    invalid = invalid_binding_result(kind, trace)

    class Binding:
        def __enter__(self):
            return self

        def result(self):
            raise AssertionError("failed handler must not project a result")

        def __exit__(self, *exc):
            trace.append(exc[0])
            return invalid

    class App:
        def bind(self, root, context):
            return Binding()

    def failed(context):
        raise RuntimeError("application failure")

    try:
        assert m._invoke_application(App(), failed, object(), 42, object(), lease) == (False, None)
        assert trace == [RuntimeError]
        assert (invalid.cr_frame if kind == "coroutine" else invalid.gi_frame) is None
    finally:
        invalid.close()


@pytest.mark.parametrize("exit_result", [None, False, True])
def test_synchronous_binding_accepts_boolean_or_none_exit_result(exit_result):
    m = module()
    from modkit_workers import _native_job_lifecycle as life

    lease = life._MaterialLease(
        capacity=1073741824, payload_limit=1048576, result_limit=1048576, depth_limit=32
    )
    lease.reserve()

    class Binding:
        def __enter__(self):
            return self

        def result(self):
            return b"done"

        def __exit__(self, *exc):
            return exit_result

    class App:
        def bind(self, root, context):
            return Binding()

    assert m._invoke_application(App(), lambda context: None, object(), 42, object(), lease) == (
        True,
        b"done",
    )


@pytest.mark.parametrize("interruption", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("cleanup", ["exception", "coroutine"])
def test_binding_cleanup_failure_does_not_turn_interruption_into_business_failure(
    interruption, cleanup
):
    m = module()
    from modkit_workers import _native_job_lifecycle as life

    lease = life._MaterialLease(
        capacity=1073741824, payload_limit=1048576, result_limit=1048576, depth_limit=32
    )
    lease.reserve()
    error = interruption("synthetic interruption")
    trace, roots = [], []
    invalid = invalid_binding_result("coroutine", trace)

    class Binding:
        def __enter__(self):
            return self

        def result(self):
            raise AssertionError("interrupted handler must not project a result")

        def __exit__(self, *exc):
            trace.append(exc[1])
            if cleanup == "exception":
                raise RuntimeError("synthetic cleanup failure")
            return invalid

    class App:
        def bind(self, root, context):
            roots.append(root)
            return Binding()

    def interrupted(context):
        raise error

    try:
        with pytest.raises(interruption) as caught:
            m._invoke_application(App(), interrupted, object(), 42, object(), lease)
        assert caught.value is error
        assert trace == [error]
        if cleanup == "coroutine":
            assert invalid.cr_frame is None
        with pytest.raises(RuntimeError):
            _ = roots[0].connection
    finally:
        invalid.close()
