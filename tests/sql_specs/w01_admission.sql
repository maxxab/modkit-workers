-- NOT_READY SOURCE ONLY. Never run this file as a migration or psql script.
-- Named statements are consumed by tests/w01_protocol_source.py after a separate
-- exact disposable owner/preflight/lease release. No foundation replacement.
-- name: submit
SELECT work_id, inserted FROM modkit_workers.w01(
 %(work_id)s::uuid, %(kind)s::text, %(subscription_id)s::bytea,
 %(namespace)s::bytea, %(command_type)s::bytea, %(scope_evidence)s::bytea,
 %(idempotency_key)s::bytea, %(canonical_version)s::int4,
 %(schema_version_decimal)s::bytea, %(scope_application)s::bytea,
 %(scope_tenant)s::bytea, %(scope_owner)s::bytea, %(intent_evidence)s::bytea,
 %(semantic_input)s::bytea, %(replay_input)s::bytea, %(protected_binding)s::bytea,
 %(replay_policy)s::text, %(max_attempts)s::int4, %(deadline)s::timestamptz,
 %(original_available_at)s::timestamptz, %(material_state)s::text,
 %(protected_sidecar)s::bytea, %(protected_reference)s::bytea,
 %(protected_codec)s::bytea, %(protected_key_version)s::bytea,
 %(protected_expires_at)s::timestamptz, %(protected_recovery_metadata)s::bytea,
 %(protected_cleanup_policy)s::text, %(projection_metadata)s::bytea);
-- name: checked
SELECT * FROM modkit_events.e15(%(work_id)s::uuid);
-- name: half
SELECT * FROM modkit_events.job_payloads WHERE job_work_id=%(work_id)s::uuid;
-- name: work
SELECT * FROM modkit_events.work WHERE work_id=%(work_id)s::uuid;
-- name: history
SELECT * FROM modkit_events.work_history WHERE work_id=%(work_id)s::uuid ORDER BY history_id;
-- name: blockers
SELECT pg_catalog.pg_blocking_pids(%(pid)s::int4);
-- name: inventory
SELECT c.relname,c.relkind FROM pg_catalog.pg_class AS c
JOIN pg_catalog.pg_namespace AS n ON n.oid=c.relnamespace
WHERE n.nspname='modkit_events' AND c.relkind IN ('r','p','S') ORDER BY c.relname;
-- name: naked_work_negative_only
-- Deliberately incomplete composition, in SAME uncommitted disposable owner
-- root only. No subtype/history, no commit, no trigger bypass. This is not a
-- successful producer. Request evidence is still production-built and valid.
INSERT INTO modkit_events.work
 (work_id,kind,subscription_id,namespace,command_type,schema_version_decimal,
 runnable_version,canonical_version,scope_evidence,scope_application,scope_tenant,
 scope_owner,idempotency_key,intent_evidence,semantic_input,replay_input,
 protected_binding,replay_policy,max_attempts,deadline,original_available_at,
 state,cancellation_requested,token,ownership_revision,lease_until,available_at,
 cycle,attempt_count,dispatch_id,result,created_at,updated_at,success_origin,
 completion_guard_id,final_fence_at,completion_result_digest,
 resolution_operation_id,terminal_resolution_operation_id)
VALUES (%(work_id)s,%(kind)s,%(subscription_id)s,%(namespace)s,%(command_type)s,
 %(schema_version_decimal)s,1,%(canonical_version)s,%(scope_evidence)s,
 %(scope_application)s,%(scope_tenant)s,%(scope_owner)s,%(idempotency_key)s,
 %(intent_evidence)s,%(semantic_input)s,%(replay_input)s,%(protected_binding)s,
 %(replay_policy)s,%(max_attempts)s,%(deadline)s,%(original_available_at)s,
 'queued',FALSE,NULL,0,NULL,%(original_available_at)s,1,0,NULL,NULL,
 pg_catalog.clock_timestamp(),pg_catalog.clock_timestamp(),NULL,NULL,NULL,NULL,NULL,NULL);
