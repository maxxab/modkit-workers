"""Offline tests. Every launch, I/O readiness and clock is synthetic."""

import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).parent


def test_00_controller_exists():
    assert (HERE / "controller.py").is_file(), "bounded controller is not implemented"


@pytest.fixture
def c(monkeypatch):
    path = HERE / "controller.py"
    assert path.is_file(), "bounded controller is not implemented"
    spec = importlib.util.spec_from_file_location("w01_location_controller", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(
        module.subprocess,
        "Popen",
        lambda *a, **kw: pytest.fail("offline tests must never launch a process"),
    )
    monkeypatch.setattr(
        module.System,
        "popen",
        staticmethod(lambda *a, **kw: pytest.fail("offline launch forbidden")),
    )
    return module


def negative_output():
    lines = [f"command|{name}|" for name in ("python3", "python", "pip3")]
    lines += [
        f"path|{path}|no|no|no"
        for path in (
            "/usr/bin/python3",
            "/usr/local/bin/python3",
            "/usr/bin/python",
            "/usr/local/bin/python",
            "/usr/lib/python3/dist-packages/psycopg",
            "/usr/lib/python3/dist-packages/psycopg_binary",
        )
    ]
    lines += [
        f"package-directory|/usr/local/lib/python{version}/site-packages/{package}|no"
        for version in ("3.11", "3.12", "3.13", "3.14")
        for package in ("psycopg", "psycopg_binary")
    ]
    return ("\n".join(lines) + "\n").encode()


@pytest.fixture
def proposal():
    return json.loads(
        (HERE.parent / "w01-runtime-location-proposal-20261107/proposal.json").read_bytes()
    )


def good_result(stdout):
    return {
        "status": "COMPLETE",
        "returncode": 0,
        "stdout": stdout,
        "stderr": b"",
        "timed_out": False,
        "overflow": False,
        "client_reaped": True,
        "launch_uncertain": False,
    }


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FakeSystem:
    """No real descriptors, timers, children, signals or target actions."""

    def __init__(
        self,
        chunks=(),
        *,
        never_exit=False,
        launch_error=False,
        read_error=False,
        kill_error=False,
        wait_error=False,
        launch_delay=0,
    ):
        self.clock = Clock()
        self.chunks = list(chunks)
        self.never_exit = never_exit
        self.launch_error = launch_error
        self.read_error = read_error
        self.kill_error = kill_error
        self.wait_error = wait_error
        self.launch_delay = launch_delay
        self.kwargs = None
        self.killed = 0
        self.waited = 0
        self.closed = []
        self.registered = {}
        self.proc = SimpleNamespace(
            stdout=SimpleNamespace(fileno=lambda: 10, close=lambda: self.closed.append(10)),
            stderr=SimpleNamespace(fileno=lambda: 11, close=lambda: self.closed.append(11)),
            poll=lambda: None if self.never_exit or self.chunks else 0,
            kill=self.kill,
            wait=self.wait,
        )

    def popen(self, argv, **kwargs):
        self.kwargs = kwargs
        self.argv = argv
        self.clock.now += self.launch_delay
        if self.launch_error:
            raise OSError("synthetic spawn uncertainty")
        return self.proc

    def selector(self):
        return self

    def register(self, pipe, events, data):
        self.registered[pipe.fileno()] = SimpleNamespace(fileobj=pipe, data=data)

    def unregister(self, pipe):
        self.registered.pop(pipe.fileno())

    def select(self, timeout):
        self.clock.now += min(timeout, 0.1)
        if self.chunks:
            fd, _ = self.chunks[0]
            return [(self.registered[fd], 1)]
        if self.never_exit:
            return []
        return [(key, 1) for key in list(self.registered.values())]

    def read(self, fd, count):
        if self.read_error:
            raise OSError("synthetic pipe failure")
        if self.chunks:
            got_fd, chunk = self.chunks[0]
            assert fd == got_fd
            data, tail = chunk[:count], chunk[count:]
            if tail:
                self.chunks[0] = (fd, tail)
            else:
                self.chunks.pop(0)
            return data
        return b""

    def close(self):
        pass

    def set_blocking(self, fd, flag):
        assert flag is False

    def kill(self):
        self.killed += 1
        if self.kill_error:
            raise OSError("synthetic kill uncertainty")
        self.never_exit = False

    def wait(self, timeout):
        self.waited += 1
        assert 0 <= timeout <= 0.25
        if self.wait_error:
            raise TimeoutError("synthetic reap uncertainty")
        return 0


def test_frozen_source_pins(c):
    p, pins = c.load_frozen()
    assert p["target_container_id"] == c.TARGET
    assert (
        pins["proposal_manifest_sha256"]
        == "6f55397f3042bc333ad1d8354e2b42f772ecaa3bba875e327978ca7853fe1a61"
    )
    assert len(p["commands_in_order"]) == 3


def test_strict_negative_and_unexpected_positive(c):
    result = c.parse_locations(negative_output())
    assert result["classification"] == "NO_ROUTE_FOUND_IN_CHECKED_SET"
    data = negative_output().replace(b"command|python3|", b"command|python3|/unexpected/python3")
    result = c.parse_locations(data)
    assert result["classification"] == "VISIBLE_LOCATION_ONLY_NOT_QUALIFIED"
    assert result["commands"]["python3"] == "/unexpected/python3"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b[:-1],
        lambda b: b + b"extra\n",
        lambda b: b.replace(b"|no", b"|maybe", 1),
        lambda b: b.replace(b"python3", b"python2", 1),
        lambda b: b.replace(b"|no|no|no", b"|no|yes|no", 1),
        lambda b: b.replace(b"command|python3|", b"command|python3|relative"),
        lambda b: b.replace(b"command|python3|", b"command|python3|/a\x00"),
        lambda b: b.replace(b"\n", b"\r\n"),
        lambda b: b"\xff" + b,
    ],
)
def test_malformed_locations_fail(c, mutate):
    with pytest.raises(c.Rejected):
        c.parse_locations(mutate(negative_output()))


@pytest.mark.parametrize("bad", [b'{"x":1,"x":1}', b'{"x":NaN}', b"{} trailing"])
def test_strict_json(c, bad):
    with pytest.raises(c.Rejected):
        c.strict_json(bad)


def test_profile_types_and_extra_fields(c, proposal):
    expected = proposal["expected_container_profile"]
    c.validate_profile(json.dumps(expected).encode(), expected)
    for mutate in (
        lambda p: p.update(running=1),
        lambda p: p.update(extra=1),
        lambda p: p["HostConfig"].update(NanoCpus=500000000.0),
    ):
        bad = copy.deepcopy(expected)
        mutate(bad)
        with pytest.raises(c.Rejected):
            c.validate_profile(json.dumps(bad).encode(), expected)


def test_sequence_exact_argv_and_bounded_negative(c, proposal):
    calls = []
    profile = json.dumps(proposal["expected_container_profile"]).encode()
    outputs = [profile, negative_output(), profile]

    def run(command, deadline):
        calls.append(copy.deepcopy(command))
        assert deadline == 25
        return good_result(outputs[len(calls) - 1])

    result = c.run_sequence(proposal, run, clock=lambda: 0, record=lambda *a: None)
    assert calls == proposal["commands_in_order"]
    assert result["status"] == "COMPLETE_BOUNDED_OBSERVATION"
    assert result["container_profile_matches"] is True
    assert result["finding"]["classification"] == "NO_ROUTE_FOUND_IN_CHECKED_SET"
    assert result["native_route_qualified"] is False


@pytest.mark.parametrize("phase", [0, 1, 2])
@pytest.mark.parametrize(
    "failure", ["stderr", "exit", "timeout", "overflow", "unreaped", "malformed", "exception"]
)
def test_fail_closed_without_retry_or_aftermath(c, proposal, phase, failure):
    calls = []
    profile = json.dumps(proposal["expected_container_profile"]).encode()

    def run(command, deadline):
        index = len(calls)
        calls.append(command["name"])
        result = good_result(negative_output() if index == 1 else profile)
        if index == phase:
            if failure == "exception":
                raise OSError("synthetic host failure")
            if failure == "stderr":
                result["stderr"] = b"warning"
            if failure == "exit":
                result["returncode"] = 1
            if failure == "timeout":
                result["timed_out"] = True
            if failure == "overflow":
                result["overflow"] = True
            if failure == "unreaped":
                result["client_reaped"] = False
            if failure == "malformed":
                result["stdout"] = b"broken"
        return result

    result = c.run_sequence(proposal, run, clock=lambda: 0, record=lambda *a: None)
    assert result["status"] == "FAILED_CLOSED"
    assert len(calls) == phase + 1
    assert result["container_profile_matches"] is False
    assert result["native_route_qualified"] is False
    assert result["exclusive_release_requires_owner_review"] is (phase >= 1)
    assert "finding" not in result


def test_overall_deadline_prevents_launch(c, proposal):
    clock = Clock()
    calls = []

    def run(command, deadline):
        calls.append(command["name"])
        clock.now = 26
        return good_result(json.dumps(proposal["expected_container_profile"]).encode())

    result = c.run_sequence(proposal, run, clock=clock, record=lambda *a: None)
    assert result["status"] == "FAILED_CLOSED"
    assert len(calls) == 1


def test_record_failure_prevents_process_launch(c, proposal):
    calls = []

    def record(*args):
        raise OSError("disk full")

    result = c.run_sequence(proposal, lambda *a: calls.append(a), clock=lambda: 0, record=record)
    assert result["status"] == "FAILED_CLOSED"
    assert calls == []


def test_runner_complete_and_exact_stream_limit(c, proposal):
    system = FakeSystem([(10, b"x" * 4096), (11, b"")])
    result = c.run_process(proposal["commands_in_order"][0], 25, system=system)
    assert result["status"] == "COMPLETE"
    assert result["stdout"] == b"x" * 4096
    assert result["client_reaped"] is True
    assert system.killed == 0
    assert system.argv == proposal["commands_in_order"][0]["argv"]
    assert system.kwargs["shell"] is False
    assert system.kwargs["start_new_session"] is False
    assert system.kwargs["stdin"] == c.subprocess.DEVNULL
    assert system.kwargs["env"] == {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
    }


@pytest.mark.parametrize("fd", [10, 11])
def test_runner_overflow_caps_memory_and_kills(c, proposal, fd):
    system = FakeSystem([(fd, b"x" * 5000)], never_exit=True)
    result = c.run_process(proposal["commands_in_order"][0], 25, system=system)
    assert result["overflow"] is True
    assert len(result["stdout"]) <= 4096 and len(result["stderr"]) <= 4096
    assert system.killed == 1
    assert result["status"] == "FAILED_CLOSED"


@pytest.mark.parametrize(
    "kind",
    [
        "no_output",
        "pipe_inherited",
        "launch_delay",
        "launch_error",
        "read_error",
        "kill_error",
        "wait_error",
    ],
)
def test_runner_timeout_and_uncertainty(c, proposal, kind):
    kwargs = {"never_exit": True}
    if kind == "launch_delay":
        kwargs["launch_delay"] = 8
    if kind in {"launch_error", "read_error", "kill_error", "wait_error"}:
        kwargs[kind] = True
    system = FakeSystem([(10, b"x")] if kind == "read_error" else [], **kwargs)
    result = c.run_process(proposal["commands_in_order"][1], 25, system=system)
    assert result["status"] == "FAILED_CLOSED"
    assert len(result["stdout"]) <= 4096
    if kind == "launch_error":
        assert result["launch_uncertain"] is True
    if kind in {"kill_error", "wait_error"}:
        assert result["client_reaped"] is False


def test_gate_rejects_missing_and_stale_authority(c):
    with pytest.raises(c.Rejected):
        c.validate_authority({}, {}, {}, 100)
    expected = {
        "artifact_manifest_sha256": "a" * 64,
        "invocation_sha256": "b" * 64,
        "proposal_manifest_sha256": c.PROPOSAL_MANIFEST_SHA,
        "accepted_events_runtime_sha256": c.RUNTIME_SHA,
        "target_container_id": c.TARGET,
    }
    acceptance = dict(
        expected,
        status="ACCEPTED_EXACT_SOURCE_AND_INVOCATION",
        reviewer="independent",
        acceptance_id="review-1",
    )
    lease = dict(
        expected,
        status="EXCLUSIVE_WINDOW_GRANTED",
        owner="events",
        acceptance_id="review-1",
        lease_id="window-1",
        valid_from_unix=99,
        valid_until_unix=130,
        latest_accepted_runtime_sha256=c.RUNTIME_SHA,
        no_other_target_work=True,
    )
    c.validate_authority(acceptance, lease, expected, 100)
    for key, value in [
        ("valid_until_unix", 120),
        ("latest_accepted_runtime_sha256", "f" * 64),
        ("no_other_target_work", 1),
        ("acceptance_id", "other"),
        ("target_container_id", "other"),
        ("valid_from_unix", 101),
    ]:
        bad = dict(lease, **{key: value})
        with pytest.raises(c.Rejected):
            c.validate_authority(acceptance, bad, expected, 100)


def test_directory_is_valid_metadata_not_an_interpreter_claim(c):
    data = negative_output().replace(b"|no|no|no", b"|yes|yes|yes", 1)
    result = c.parse_locations(data)
    assert result["classification"] == "VISIBLE_LOCATION_ONLY_NOT_QUALIFIED"
    assert result["paths"]["/usr/bin/python3"]["directory"] == "yes"


def test_uncertain_launch_requires_host_group_termination(c, proposal):
    calls = []

    def run(command, deadline):
        calls.append(command["name"])
        result = good_result(b"")
        result["launch_uncertain"] = True
        result["client_reaped"] = False
        return result

    result = c.run_sequence(proposal, run, clock=lambda: 0, record=lambda *a: None)
    assert result["host_group_kill_required"] is True
    assert calls == ["before-container"]


def test_completion_authority_needs_only_unexpired_current_window(c):
    expected = {"target_container_id": c.TARGET}
    acceptance = dict(
        expected, status="ACCEPTED_EXACT_SOURCE_AND_INVOCATION", acceptance_id="r", reviewer="r"
    )
    lease = dict(
        expected,
        status="EXCLUSIVE_WINDOW_GRANTED",
        acceptance_id="r",
        owner="e",
        lease_id="l",
        valid_from_unix=100,
        valid_until_unix=127,
        latest_accepted_runtime_sha256=c.RUNTIME_SHA,
        no_other_target_work=True,
    )
    c.validate_authority(acceptance, lease, expected, 105, minimum_remaining=0)
    with pytest.raises(c.Rejected):
        c.validate_authority(acceptance, lease, expected, 128, minimum_remaining=0)


def test_exited_client_with_lingering_pipe_times_out(c, proposal):
    system = FakeSystem()
    system.select = lambda timeout: setattr(system.clock, "now", system.clock.now + timeout) or []
    result = c.run_process(proposal["commands_in_order"][1], 25, system=system)
    assert result["status"] == "FAILED_CLOSED"
    assert result["timed_out"] is True


def test_nonregular_and_oversize_reads_rejected(c, tmp_path):
    with pytest.raises(c.Rejected):
        c.read_bounded(tmp_path)
    f = tmp_path / "data"
    f.write_bytes(b"1234")
    with pytest.raises(c.Rejected):
        c.read_bounded(f, 3)
    link = tmp_path / "link"
    link.symlink_to(f)
    with pytest.raises(OSError):
        c.read_bounded(link)


def test_pin_mismatch_rejected(c, tmp_path):
    f = tmp_path / "data"
    f.write_bytes(b"test")
    with pytest.raises(c.Rejected):
        c.pinned(f, "0" * 64)
    with pytest.raises(c.Rejected):
        c.pinned(f, c.digest(b"test"), 5)


def test_runner_exception_keeps_host_cleanup_uncertain(c, proposal):
    def run(*args):
        raise OSError("unconfirmed launch")

    result = c.run_sequence(proposal, run, clock=lambda: 0, record=lambda *a: None)
    assert result["host_group_kill_required"] is True


def test_existing_attempt_is_never_modified(c, monkeypatch):
    import contextlib

    invocation = {
        "controller_arguments": ["--execute-reviewed-once"],
        "acceptance_file": "/not-used/a",
        "lease_file": "/not-used/l",
        "evidence_directory": "/not-used/existing",
    }
    monkeypatch.setattr(c.sys, "argv", ["controller.py", "--execute-reviewed-once"])
    monkeypatch.setattr(c, "alarm", lambda *a: contextlib.nullcontext())
    monkeypatch.setattr(c, "load_packet", lambda: (invocation, {}))
    monkeypatch.setattr(c, "validate_launcher", lambda *a: None)
    monkeypatch.setattr(c, "load_frozen", lambda: ({}, {}))
    monkeypatch.setattr(c, "read_bounded", lambda *a: b"{}")
    monkeypatch.setattr(c, "validate_authority", lambda *a: None)

    def exists(*a, **kw):
        raise FileExistsError("already consumed")

    monkeypatch.setattr(c.Path, "mkdir", exists)
    writes = []
    kills = []
    monkeypatch.setattr(c, "write_json", lambda *a: writes.append(a))
    monkeypatch.setattr(c.os, "killpg", lambda *a: kills.append(a))
    assert c.main() == 1
    assert writes == []
    assert kills == []


def test_no_argument_entry_cannot_execute(c, monkeypatch, capsys):
    monkeypatch.setattr(c.sys, "argv", ["controller.py"])
    assert c.main() == 2
    assert "SOURCE_ONLY" in capsys.readouterr().out
