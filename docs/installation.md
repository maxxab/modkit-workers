# Explicit Workers installation closure

This source candidate includes immutable initial/grants resources and an inert
manifest. It is **not installation-ready**: source controls are connection-free,
not PostgreSQL execution, restricted-role ACL qualification, actual wheel/sdist
installation, or full runtime evidence. Canonical production trees remain gated.

## Trusted caller and roles

Applications select an existing restricted NOLOGIN installation owner and the
pre-existing modkit_runtime, modkit_reconciler and modkit_operator roles.
The same owner owns both component schemas. Runtime/reconciler may have only
operator ancestry; owner/operator have no other ancestors. No package operation
creates roles, memberships, default privileges, connections or transactions.

These are trusted whole-application service roles, not end-user or tenant-level
security boundaries. Operator READ includes protected payloads, identity,
references and provenance. Application authorization and explicit safe output
projection remain mandatory. Before adopting a native connection, validate the
actual login/session cannot obtain extra rights or SET ROLE to a privileged
identity. Checking the four installation roles does not constrain every LOGIN
descendant. A receipt is neither business authority nor ongoing ACL attestation.

Workers grants only schema USAGE and exact function EXECUTE without grant option:
- Runtime: W01; W02; both W03 overloads; W04; both W05 overloads.
- Reconciler and operator: W02; both W03 overloads; W04.
- No restricted direct table, column or sequence rights, schema CREATE or
  private helper access. PUBLIC and unlisted signatures receive none.

Every declared and effective ACL is checked before/after grants. Permitted
operator ancestry includes potential inherited and SET-role exposure. All read
capabilities are granted directly, so membership is optional. Explicit owner
global/target-schema default ACL contamination fails; unrelated schemas and
ordinary implicit PostgreSQL type behavior are not repaired. Explicit private
Events _parse_result remains private. No type privileges are added.

## Verify bytes and prerequisite identity

Use the accepted external release record to authenticate code/artifacts,
both exact descriptor byte pins and the separate owner receipt/reader pin.
Locally consistent hashes alone are not release authenticity or database attestation.
Workers manifest()/read_sql() validate the existing strict descriptor and exact
two-resource bytes; they never execute SQL. Independent installer verification
must recompute Events MKMF from actual accepted Events initial/grants bytes and
compare it to Events descriptor and Workers depends_on. Reject a different
well-formed dependency digest. Do not infer compatibility from package version.

MKMF is ASCII MKMF plus byte01, uint32BE resource count, then sorted logical
component/path frames: uint32BE UTF8 path length, path bytes, raw32 SHA256.
Only initial and grants participate. Neither manifest, receipt nor self-digest
is an aggregate input. Freeze all headers and D-E6 bytes before computing pins.

## Apply only in an explicitly authorized caller-owned root

1. Verify PostgreSQL16+, role/owner prerequisites and the trusted exact closure.
2. Apply the complete Events initial SQL, Events grants/postflight, then its
   separate owner receipt.
3. Verify the Events prerequisite; apply the complete Workers initial SQL,
   including its exact Events schema USAGE preflight.
4. Apply Workers grants_runtime.sql in full, including postflight.
5. Insert the Workers owner receipt and observe E33('workers') as appropriate.
6. The caller commits and acknowledges the root outcome.

Do not interleave own-component grants into initial SQL. The private nine-argument
Events E04 is reached through the same-owner SECURITY DEFINER W05; granting it
to runtime is forbidden. D-E6 admits only owner schema rights plus all three
direct, owner-issued, nongrantable Events schema USAGE entries; it does not
revoke/repair unexpected grants. Every unrelated initial body is preserved.

An already acknowledged Events installation may precede a separate Workers root
only after exact trusted installation evidence, receipt and dependency checks.
No automatic reapply, upsert, hidden savepoint, rollback, reconnect or retry.
A staged receipt is not committed success. Caller-acknowledged rollback removes
that root's effects. Unknown commit remains UNKNOWN and requires explicit
reconciliation; absence or an apparently matching receipt does not authorize replay.

## Shared owner receipt

Retrieve the generic template with Events
migrations.read_owner_receipt(events_migration), passing the exact verified
Events Migration even for Workers. The fixed Events-only owner_receipt.sql is
bounded to4096 bytes, hash checked separately and read with the full Events
resource closure in one anchored lease. Workers exposes no new reader or apply API.

After checking the Workers descriptor and actual Events dependency, bind the six
native parameters: component 'workers', version1, raw32 Workers aggregate,
'modkit-pg-ab-2', 'MKSC-1', 'MKPF-1'. SQL supplies applied_at explicitly with
database clock_timestamp(). Use native $1 through $6 parameter transport, not
interpolation or a general SQL rewriting layer. The future native test must
demonstrate this transport; source regex checks are not execution evidence.
Plain INSERT only: duplicate receipts fail rather than silently succeeding.
Direct restricted access to schema_versions is denied.

## Native paths and remaining gates

Runtime native startup requires Events schema USAGE and E33, then the permitted
Workers wrappers and Events-owned execution lifecycle. Reconciler recovery uses
E33 followed by E13(bytea,text,int4,uuid,int4), not W01/W05. Test each lawful path
as its real restricted role with actual data and denied paths, not merely as owner.

Remaining gates: independent complete source review and pure QA; actual supported
wheel/sdist/rebuilt-wheel byte identity and origin checks; real restricted-role
PostgreSQL installation/ACL/parameter/native qualification; main canonical release.
Accepted unpublished candidate metadata selects Events0.2.0 and Workers0.1.0,
with Workers requiring Events>=0.2,<0.3. Actual dependency resolution and installed
artifact qualification remain pending, as do native backend and platform gates.
This installation-checkpoint candidate is NOT_RELEASE_QUALIFIED; all outstanding
Events final-release requirements remain mandatory. No --no-deps or source
PYTHONPATH workaround counts as artifact acceptance. Windows resource transport
remains unsupported.
No database/container/network/build/install operation is part of these source tests.
