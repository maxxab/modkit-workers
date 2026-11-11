"""SOURCE-ONLY candidate. No arguments perform no target action.

The execution form requires a separately accepted exact packet/invocation plus a
fresh matching Events exclusive-window record. Those files are NOT authority on
their own: the coordinator must validate their provenance and current owner state.
"""

import contextlib
import hashlib
import json
import math
import os
import selectors
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROPOSAL = HERE.parent / "w01-runtime-location-proposal-20261107"
PROPOSAL_MANIFEST_SHA = "6f55397f3042bc333ad1d8354e2b42f772ecaa3bba875e327978ca7853fe1a61"
PROPOSAL_SHA = "6862bd5edfe0073ac34ba8f6bdaf76c1a248565053e7fe1b877924efe57a10c8"
RUNTIME_SHA = "18a103aa6e9d67277a71bab61c1f511b8fd01405dad126190e0cfbbab532c52b"
TARGET = "51a93b781c024f29372e44643db26447d4d367fa4a1aa255abd8e665c90270f3"
EVENTS_ROOT = Path(
    "/home/faris/modkit-local-20261106/foundation/continuation-v3/dot-events-review-20261107"
)
MAX_STREAM = 4096
PROCESS_SECONDS = 7
TOTAL_SECONDS = 25
FIXED_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC"}
COMMAND_NAMES = ("python3", "python", "pip3")
PATHS = (
    "/usr/bin/python3",
    "/usr/local/bin/python3",
    "/usr/bin/python",
    "/usr/local/bin/python",
    "/usr/lib/python3/dist-packages/psycopg",
    "/usr/lib/python3/dist-packages/psycopg_binary",
)
PACKAGES = tuple(
    f"/usr/local/lib/python{version}/site-packages/{package}"
    for version in ("3.11", "3.12", "3.13", "3.14")
    for package in ("psycopg", "psycopg_binary")
)


class Rejected(Exception):
    """Only fixed diagnostic codes are retained, not arbitrary exception text."""


class DeadlineExceeded(BaseException):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise Rejected("duplicate_json_key")
            result[key] = value
        return result

    def nonfinite(_):
        raise Rejected("nonfinite_json_number")

    try:
        return json.loads(data, object_pairs_hook=pairs, parse_constant=nonfinite)
    except (UnicodeError, ValueError, TypeError, RecursionError) as error:
        raise Rejected("invalid_json") from error


def read_bounded(path, limit=2 * 1024 * 1024):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise Rejected("input_not_bounded_regular_file")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise Rejected("input_over_limit")
        return data
    finally:
        os.close(fd)


def pinned(path, sha, size=None):
    data = read_bounded(path)
    if digest(data) != sha or (size is not None and len(data) != size):
        raise Rejected("input_pin_drift")
    return data


def load_frozen():
    raw_manifest = pinned(PROPOSAL / "artifact-pins.json", PROPOSAL_MANIFEST_SHA)
    manifest = strict_json(raw_manifest)
    if set(manifest) != {"proposal.json", "README.md"}:
        raise Rejected("unexpected_proposal_inventory")
    for name, entry in manifest.items():
        pinned(PROPOSAL / name, entry["sha256"], entry["size"])
    proposal = strict_json(pinned(PROPOSAL / "proposal.json", PROPOSAL_SHA))
    if proposal["target_container_id"] != TARGET:
        raise Rejected("target_drift")
    if proposal["accepted_events_runtime_pins"]["sha256"] != RUNTIME_SHA:
        raise Rejected("runtime_anchor_drift")
    observed = {"proposal_manifest_sha256": PROPOSAL_MANIFEST_SHA}
    for key in ("accepted_events_runtime_pins", "accepted_container_file", "accepted_catalog_file"):
        entry = proposal[key]
        path = Path(entry["path"])
        if not path.is_relative_to(EVENTS_ROOT):
            raise Rejected("unexpected_frozen_path")
        raw = pinned(path, entry["sha256"])
        observed[key] = {"path": str(path), "sha256": digest(raw), "bytes": len(raw)}
        if key == "accepted_events_runtime_pins":
            runtime_pins = strict_json(raw)
        elif key == "accepted_container_file":
            validate_profile(raw, proposal["expected_container_profile"])
    if not isinstance(runtime_pins, dict) or not 1 <= len(runtime_pins) <= 128:
        raise Rejected("runtime_inventory_shape")
    total = 0
    for name, entry in runtime_pins.items():
        path = Path(name)
        if not path.is_absolute() or not path.is_relative_to(EVENTS_ROOT):
            raise Rejected("unexpected_runtime_path")
        raw = pinned(path, entry["sha256"], entry["bytes"])
        total += len(raw)
        if total > 4 * 1024 * 1024:
            raise Rejected("runtime_inventory_over_limit")
    observed["runtime_entries_verified"] = len(runtime_pins)
    if [c["name"] for c in proposal["commands_in_order"]] != [
        "before-container",
        "runtime-locations",
        "after-container",
    ]:
        raise Rejected("command_order")
    for command in proposal["commands_in_order"]:
        if (
            command["timeout_seconds"],
            command["max_stdout_bytes"],
            command["max_stderr_bytes"],
        ) != (PROCESS_SECONDS, MAX_STREAM, MAX_STREAM):
            raise Rejected("budget_drift")
    return proposal, observed


def validate_profile(stdout, expected):
    actual = strict_json(stdout)
    # Canonical JSON distinguishes bool/int and int/float, unlike Python ==.
    if json.dumps(actual, sort_keys=True) != json.dumps(expected, sort_keys=True):
        raise Rejected("container_profile_mismatch")


def parse_locations(stdout):
    try:
        text = stdout.decode("utf-8", errors="strict")
    except UnicodeError as error:
        raise Rejected("location_encoding") from error
    if not text.endswith("\n") or "\r" in text or len(stdout) > MAX_STREAM:
        raise Rejected("location_framing")
    lines = text[:-1].split("\n")
    if len(lines) != 17:
        raise Rejected("location_line_count")
    commands = {}
    path_rows = {}
    package_rows = {}
    for line, name in zip(lines[:3], COMMAND_NAMES, strict=True):
        parts = line.split("|")
        if len(parts) != 3 or parts[:2] != ["command", name]:
            raise Rejected("command_row")
        value = parts[2]
        if value and (not value.startswith("/") or not all(ch.isprintable() for ch in value)):
            raise Rejected("command_value")
        commands[name] = value
    for line, path in zip(lines[3:9], PATHS, strict=True):
        parts = line.split("|")
        if (
            len(parts) != 5
            or parts[:2] != ["path", path]
            or any(value not in {"yes", "no"} for value in parts[2:])
        ):
            raise Rejected("path_row")
        exists, executable, directory = parts[2:]
        if exists == "no" and (executable == "yes" or directory == "yes"):
            raise Rejected("inconsistent_path_row")
        path_rows[path] = dict(exists=exists, executable=executable, directory=directory)
    for line, path in zip(lines[9:], PACKAGES, strict=True):
        parts = line.split("|")
        if (
            len(parts) != 3
            or parts[:2] != ["package-directory", path]
            or parts[2] not in {"yes", "no"}
        ):
            raise Rejected("package_row")
        package_rows[path] = parts[2]
    visible = (
        any(commands.values())
        or any(row["exists"] == "yes" for row in path_rows.values())
        or ("yes" in package_rows.values())
    )
    return {
        "classification": "VISIBLE_LOCATION_ONLY_NOT_QUALIFIED"
        if visible
        else "NO_ROUTE_FOUND_IN_CHECKED_SET",
        "commands": commands,
        "paths": path_rows,
        "package_directories": package_rows,
        "global_absence_claim": False,
        "interpreter_or_driver_executed": False,
        "versions_importability_abi_dependency_closure_database_reachability": "NOT_TESTED",
    }


@contextlib.contextmanager
def alarm(deadline):
    """Interrupt blocking launch/read/write calls on the main Linux host thread."""
    previous_handler = signal.getsignal(signal.SIGALRM)
    started = time.monotonic()
    previous_timer = signal.setitimer(signal.ITIMER_REAL, 0)

    def expired(*_):
        raise DeadlineExceeded()

    signal.signal(signal.SIGALRM, expired)
    remaining = deadline - time.monotonic()
    try:
        if remaining <= 0:
            raise DeadlineExceeded()
        # Never postpone a surrounding overall deadline.
        duration = min(remaining, previous_timer[0]) if previous_timer[0] else remaining
        signal.setitimer(signal.ITIMER_REAL, duration)
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0]:
            left = previous_timer[0] - (time.monotonic() - started)
            signal.setitimer(signal.ITIMER_REAL, max(left, 0.000001), previous_timer[1])


class System:
    clock = staticmethod(time.monotonic)
    popen = staticmethod(subprocess.Popen)
    selector = staticmethod(selectors.DefaultSelector)
    read = staticmethod(os.read)
    set_blocking = staticmethod(os.set_blocking)
    alarm = staticmethod(alarm)


def run_process(command, overall_deadline, *, system=None):
    system = system or System()
    started = system.clock()
    deadline = min(overall_deadline, started + PROCESS_SECONDS)
    capture_deadline = deadline - 0.25  # Reaping fits inside the seven-second envelope.
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    result = {
        "status": "FAILED_CLOSED",
        "returncode": None,
        "timed_out": False,
        "overflow": False,
        "client_reaped": False,
        "launch_uncertain": False,
        "diagnostic": None,
    }
    proc = None
    selector = None
    launch_started = False
    try:
        timer = (
            system.alarm(capture_deadline) if hasattr(system, "alarm") else contextlib.nullcontext()
        )
        with timer:
            if system.clock() >= capture_deadline:
                raise DeadlineExceeded()
            launch_started = True
            # Inherit the timeout wrapper's process group. Never shell=True.
            proc = system.popen(
                list(command["argv"]),
                executable="/usr/bin/docker",
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=False,
                close_fds=True,
                cwd="/",
                env=dict(FIXED_ENV),
                bufsize=0,
            )
            selector = system.selector()
            for name in ("stdout", "stderr"):
                pipe = getattr(proc, name)
                system.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ, name)
            open_streams = 2
            while open_streams or proc.poll() is None:
                remaining = capture_deadline - system.clock()
                if remaining <= 0:
                    raise DeadlineExceeded()
                for key, _ in selector.select(min(remaining, 0.05)):
                    name = key.data
                    try:
                        chunk = system.read(
                            key.fileobj.fileno(), MAX_STREAM - len(buffers[name]) + 1
                        )
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(key.fileobj)
                        open_streams -= 1
                        continue
                    remaining_bytes = MAX_STREAM - len(buffers[name])
                    buffers[name].extend(chunk[:remaining_bytes])
                    if len(chunk) > remaining_bytes:
                        result["overflow"] = True
                        raise Rejected("stream_overflow")
            result["returncode"] = proc.poll()
            result["client_reaped"] = result["returncode"] is not None
            result["status"] = "COMPLETE"
    except DeadlineExceeded:
        result["timed_out"] = True
        result["diagnostic"] = "host_deadline"
    except BaseException:
        result["diagnostic"] = "host_process_or_io_error"
        result["launch_uncertain"] = launch_started and proc is None
    finally:
        if result["status"] != "COMPLETE" and proc is not None:
            try:
                # Killing the client is NOT proof the target exec was cancelled.
                proc.kill()
                remaining = min(0.25, deadline - system.clock())
                if remaining > 0:
                    timer = (
                        system.alarm(deadline)
                        if hasattr(system, "alarm")
                        else contextlib.nullcontext()
                    )
                    with timer:
                        result["returncode"] = proc.wait(timeout=remaining)
                    result["client_reaped"] = True
            except BaseException:
                result["client_reaped"] = False
        if selector is not None:
            selector.close()
        if proc is not None:
            for name in ("stdout", "stderr"):
                try:
                    getattr(proc, name).close()
                except BaseException:
                    result["status"] = "FAILED_CLOSED"
                    result["diagnostic"] = "pipe_close_error"
        result["stdout"] = bytes(buffers["stdout"])
        result["stderr"] = bytes(buffers["stderr"])
        result["elapsed_seconds"] = max(0, system.clock() - started)
        if system.clock() > deadline:
            result["timed_out"] = True
            result["status"] = "FAILED_CLOSED"
        # Reaping the direct client does not settle inherited pipe or descendant
        # ownership after an interrupted capture. Preserve group cleanup separately.
        result["host_group_kill_required"] = bool(
            result["status"] != "COMPLETE"
            or result["timed_out"]
            or result["overflow"]
            or not result["client_reaped"]
            or result["launch_uncertain"]
        )
    return result


def run_sequence(proposal, runner, *, clock=time.monotonic, record, overall_deadline=None):
    deadline = overall_deadline if overall_deadline is not None else clock() + TOTAL_SECONDS
    result = {
        "status": "FAILED_CLOSED",
        "container_profile_matches": False,
        "native_route_qualified": False,
        "exclusive_release_requires_owner_review": False,
        "completed_commands": [],
        "failed_phase": None,
        "diagnostic": None,
        "host_group_kill_required": False,
        "database_connections": 0,
        "sql_statements": 0,
        "automatic_retry": False,
    }
    finding = None
    for command in proposal["commands_in_order"]:
        name = command["name"]
        result["failed_phase"] = name
        try:
            if clock() >= deadline:
                raise Rejected("overall_deadline")
            record(
                "started",
                name,
                {
                    "argv": list(command["argv"]),
                    "start_utc_unix": time.time(),
                    "start_monotonic": clock(),
                    "timeout_seconds": PROCESS_SECONDS,
                    "max_stdout_bytes": MAX_STREAM,
                    "max_stderr_bytes": MAX_STREAM,
                },
            )
            if clock() >= deadline:
                raise Rejected("overall_deadline")
            if name == "runtime-locations":
                result["exclusive_release_requires_owner_review"] = True
            result["host_group_kill_required"] = True
            outcome = runner(command, deadline)
            result["host_group_kill_required"] = bool(
                outcome.get("host_group_kill_required", True)
                or outcome["status"] != "COMPLETE"
                or outcome["timed_out"]
                or outcome["overflow"]
                or outcome["launch_uncertain"]
                or not outcome["client_reaped"]
            )
            record("process", name, outcome)
            if (
                outcome["status"] != "COMPLETE"
                or result["host_group_kill_required"]
                or outcome["returncode"] != 0
                or outcome["stderr"]
                or outcome["timed_out"]
                or outcome["overflow"]
                or not outcome["client_reaped"]
                or outcome["launch_uncertain"]
                or len(outcome["stdout"]) > MAX_STREAM
                or len(outcome["stderr"]) > MAX_STREAM
                or clock() >= deadline
            ):
                raise Rejected("command_failed_or_uncertain")
            if name == "runtime-locations":
                finding = parse_locations(outcome["stdout"])
            else:
                validate_profile(outcome["stdout"], proposal["expected_container_profile"])
            result["completed_commands"].append(name)
        except BaseException as error:
            result["diagnostic"] = str(error) if isinstance(error, Rejected) else "host_failure"
            return result
    result.update(
        status="COMPLETE_BOUNDED_OBSERVATION",
        container_profile_matches=True,
        failed_phase=None,
        finding=finding,
        exclusive_release_requires_owner_review=False,
    )
    return result


def validate_authority(acceptance, lease, expected, now, *, minimum_remaining=TOTAL_SECONDS):
    if not isinstance(acceptance, dict) or not isinstance(lease, dict):
        raise Rejected("authority_shape")
    for source in (acceptance, lease):
        for key, value in expected.items():
            if source.get(key) != value:
                raise Rejected("authority_pin_mismatch")
    if acceptance.get("status") != "ACCEPTED_EXACT_SOURCE_AND_INVOCATION":
        raise Rejected("independent_acceptance_missing")
    for source, key in (
        (acceptance, "reviewer"),
        (acceptance, "acceptance_id"),
        (lease, "owner"),
        (lease, "lease_id"),
    ):
        if not isinstance(source.get(key), str) or not 1 <= len(source[key]) <= 128:
            raise Rejected("authority_identity_missing")
    if (
        lease.get("status") != "EXCLUSIVE_WINDOW_GRANTED"
        or lease.get("acceptance_id") != acceptance["acceptance_id"]
        or lease.get("latest_accepted_runtime_sha256") != RUNTIME_SHA
        or lease.get("no_other_target_work") is not True
    ):
        raise Rejected("exclusive_window_missing_or_stale")
    for key in ("valid_from_unix", "valid_until_unix"):
        if type(lease.get(key)) not in (float, int) or not math.isfinite(lease[key]):
            raise Rejected("lease_time_invalid")
    if not lease["valid_from_unix"] <= now or lease["valid_until_unix"] < now + minimum_remaining:
        raise Rejected("exclusive_window_too_short_or_stale")


def load_packet():
    raw = read_bounded(HERE / "artifact-pins.json", 65536)
    manifest = strict_json(raw)
    if not isinstance(manifest, dict) or not 1 <= len(manifest) <= 16:
        raise Rejected("packet_inventory_shape")
    actual = {p.name for p in HERE.iterdir()}
    if actual != set(manifest) | {"artifact-pins.json"}:
        raise Rejected("packet_inventory_mismatch")
    for name, entry in manifest.items():
        if Path(name).name != name or name in {".", "..", "artifact-pins.json"}:
            raise Rejected("packet_path")
        pinned(HERE / name, entry["sha256"], entry["bytes"])
    invocation_raw = read_bounded(HERE / "host-invocation.json", 16384)
    return strict_json(invocation_raw), {
        "artifact_manifest_sha256": digest(raw),
        "invocation_sha256": digest(invocation_raw),
        "proposal_manifest_sha256": PROPOSAL_MANIFEST_SHA,
        "accepted_events_runtime_sha256": RUNTIME_SHA,
        "target_container_id": TARGET,
    }


def validate_launcher(invocation):
    expected = b"\0".join(arg.encode() for arg in invocation["linux_host_argv"]) + b"\0"
    parent_pid = os.getppid()
    actual = read_bounded(Path(f"/proc/{parent_pid}/cmdline"), 16384)
    # Matching groups alone could be a surrounding shell's group. GNU timeout
    # must itself lead the isolated group inherited by this controller.
    if (
        actual != expected
        or os.getppid() != parent_pid
        or os.getpgid(parent_pid) != parent_pid
        or os.getpgid(0) != parent_pid
    ):
        raise Rejected("required_outer_timeout_missing")


def write_json(path, value):
    data = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def main():
    if len(sys.argv) == 1:
        print("SOURCE_ONLY_NOT_EXECUTED_REVIEW_REQUIRED")
        return 2
    started = time.monotonic()
    directory = None
    result = None
    try:
        with alarm(started + 24):  # One second of margin before external 25-second KILL.
            invocation, expected = load_packet()
            if sys.argv[1:] != invocation["controller_arguments"]:
                raise Rejected("unreviewed_invocation")
            validate_launcher(invocation)
            proposal, pins = load_frozen()
            acceptance = strict_json(read_bounded(Path(invocation["acceptance_file"]), 16384))
            lease = strict_json(read_bounded(Path(invocation["lease_file"]), 16384))
            validate_authority(acceptance, lease, expected, time.time())
            # The fixed evidence directory is the future no-retry fence, created only now.
            # Preparation, imports and offline tests never call this execution form.
            candidate_directory = Path(invocation["evidence_directory"])
            candidate_directory.mkdir(mode=0o700, exist_ok=False)
            directory = candidate_directory
            write_json(
                directory / "started.json",
                {
                    "status": "STARTED_OUTCOME_NOT_YET_CONFIRMED",
                    "start_utc_unix": time.time(),
                    "pins": expected,
                    "frozen_inputs": pins,
                    "lease": lease,
                    "acceptance": acceptance,
                    "host_argv": invocation["linux_host_argv"],
                    "automatic_retry": False,
                },
            )

            def record(event, name, value):
                if event == "process":
                    for stream in ("stdout", "stderr"):
                        data = value[stream]
                        if not isinstance(data, bytes) or len(data) > MAX_STREAM:
                            raise Rejected("receipt_stream_over_limit")
                        with (directory / f"{name}.{stream}").open("xb") as output:
                            output.write(data)
                    value = {
                        key: val for key, val in value.items() if key not in {"stdout", "stderr"}
                    }
                write_json(directory / f"{name}-{event}.json", value)

            result = run_sequence(
                proposal, run_process, record=record, overall_deadline=started + 24
            )
            if result["status"] == "COMPLETE_BOUNDED_OBSERVATION":
                # Pin changes invalidate even an otherwise complete observation.
                load_frozen()
                _, after_expected = load_packet()
                if after_expected != expected:
                    raise Rejected("postrun_packet_drift")
                validate_authority(acceptance, lease, expected, time.time(), minimum_remaining=0)
            result["elapsed_seconds"] = time.monotonic() - started
            result["pins"] = expected
            write_json(directory / "outcome.json", result)
            if result["host_group_kill_required"]:
                # A lost Popen handle must not outlive a normally exiting timeout wrapper.
                os.killpg(os.getpgrp(), signal.SIGKILL)
        print(result["status"])
        return 0 if result["status"] == "COMPLETE_BOUNDED_OBSERVATION" else 1
    except BaseException:
        # A missing outcome or this marker is failure/uncertainty, never success.
        if directory is not None:
            try:
                write_json(
                    directory / "controller-failed.json",
                    {
                        "status": "FAILED_CLOSED",
                        "outcome_uncertain": True,
                        "notify_events_owner_before_exclusive_release": True,
                        "automatic_retry": False,
                        "container_unchanged_claim": False,
                    },
                )
            except BaseException:
                pass
        if directory is not None:
            # All host children inherit the validated timeout group. If recording or
            # launch handling itself failed, kill that group rather than orphan it.
            os.killpg(os.getpgrp(), signal.SIGKILL)
        print("FAILED_CLOSED_NO_RETRY")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
