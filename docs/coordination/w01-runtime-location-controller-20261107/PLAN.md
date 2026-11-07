# W01 runtime-location controller preparation plan

Goal: prepare, never execute, the exact proposed three-command read-only sequence.
Spec: ../w01-runtime-location-proposal-20261107/proposal.json and README.md.
This private packet is excluded from distributions and supplies no authority.

Architecture: one Linux host Python controller with strict frozen-input validation,
a bounded selector-based subprocess reader, strict output validators, and explicit
future acceptance/exclusivity gates. GNU timeout supplies an independent 25-second
outer process-group KILL ceiling. Exact argv is loaded only from the pinned proposal.
The container shell's 4-second KILL timeout remains unchanged. A failed command stops
the sequence; no aftermath command is attempted after an uncertain or failed exec.

Choice: preserve the fixed shell metadata probe, rather than execute/import an
unqualified interpreter or add a runtime. Source preparation choices were delegated.

- [x] Write mock-only tests first and observe the missing controller failure.
- [x] Implement frozen-input validation, gate schema, bounded runner and sequence.
- [x] Exercise drift, malformed data, stream overflow, deadline and cancellation paths.
- [x] Run complete existing pure suite and packet tests without target access.
- [x] Freeze hashes and document the exact future host invocation for independent review.

Review focus: Popen/pipe exceptions, never-ending output, lingering pipes after client
exit, deadlines during launch/evidence writes, type-confused profile JSON, stale
acceptance/exclusivity, and incomplete aftermath. Failure or interruption means no
retry and no unchanged-container claim. No grants, leases or attempt artifacts are
created by preparation. No commit, product edits, installation or target actions.

Execution, independent acceptance and target reservation are deliberately not performed.
