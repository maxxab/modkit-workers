"""Static port variance/return regressions; run with --warn-unused-ignores."""

from modkit_workers._native_control_contracts import _NativeJobPort


class BadStartup(_NativeJobPort[object, object]):
    def startup(self, request: object, /) -> int:  # type: ignore[override]
        return 1


class BadExecute(_NativeJobPort[object, object]):
    def execute(self, work: object, /) -> int:  # type: ignore[override]
        return 1


class BadShutdown(_NativeJobPort[object, object]):
    def shutdown(self) -> int:  # type: ignore[override]
        return 1


def variance(
    accepts_all_fences: _NativeJobPort[object, object],
    accepts_int_fences: _NativeJobPort[object, int],
    string_work: _NativeJobPort[str, object],
) -> None:
    # Fences are consumed only: a wider accepter can serve the narrower caller.
    narrow: _NativeJobPort[object, int] = accepts_all_fences
    # The reverse loses the promise to accept every fence.
    wide: _NativeJobPort[object, object] = accepts_int_fences  # type: ignore[assignment]
    # Work is produced and consumed, and therefore remains invariant.
    general: _NativeJobPort[object, object] = string_work  # type: ignore[assignment]
    _ = narrow, wide, general
