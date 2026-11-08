-- Workers W01 SOURCE DRAFT / NOT_READY. NOT AUTHORIZED TO APPLY.
-- Owner-only structural profile, not production E33/MKMF/grants readiness.
-- Application owns the explicit installation transaction and every W01 root.
-- No grants resource/manifest, transaction control, role or shared schema changes.
-- Dependency source closure: w01-implementation/abi-pins.json + sql-owner.md.
DO $preflight$
DECLARE
    owner_oid pg_catalog.oid;
    role_oid pg_catalog.oid;
    role_name pg_catalog.text;
    dependency pg_catalog.record;
    actual pg_catalog.record;
    object_oid pg_catalog.oid;
BEGIN
    IF pg_catalog.current_setting('server_version_num')::pg_catalog.int4 < 160000 THEN
        RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='unsupported structural installation profile';
    END IF;
    SELECT r.oid INTO owner_oid FROM pg_catalog.pg_roles AS r
     WHERE r.rolname=CURRENT_USER AND NOT r.rolcanlogin AND NOT r.rolsuper
       AND NOT r.rolbypassrls AND NOT r.rolcreaterole AND NOT r.rolcreatedb AND NOT r.rolreplication;
    IF owner_oid IS NULL
       OR NOT pg_catalog.has_database_privilege(owner_oid,pg_catalog.current_database(),'CREATE')
       OR EXISTS (SELECT 1 FROM pg_catalog.pg_namespace AS n WHERE n.nspname='modkit_workers')
       OR NOT EXISTS (SELECT 1 FROM pg_catalog.pg_namespace AS n
                       WHERE n.nspname='modkit_events' AND n.nspowner=owner_oid) THEN
        RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='invalid structural owner or namespace';
    END IF;
    FOREACH role_name IN ARRAY ARRAY['modkit_runtime','modkit_reconciler','modkit_operator']::pg_catalog.text[] LOOP
        SELECT r.oid INTO role_oid FROM pg_catalog.pg_roles AS r
         WHERE r.rolname=role_name AND NOT r.rolcanlogin AND NOT r.rolsuper AND NOT r.rolbypassrls
           AND NOT r.rolcreaterole AND NOT r.rolcreatedb AND NOT r.rolreplication;
        IF role_oid IS NULL OR role_oid=owner_oid
           OR pg_catalog.has_schema_privilege(role_oid,'modkit_events','CREATE') THEN
            RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='invalid structural restricted role';
        END IF;
    END LOOP;
    IF EXISTS (
        WITH RECURSIVE ancestry(origin,ancestor) AS (
            SELECT r.oid,r.oid FROM pg_catalog.pg_roles AS r
             WHERE r.oid=owner_oid OR r.rolname IN ('modkit_runtime','modkit_reconciler','modkit_operator')
            UNION
            SELECT a.origin,m.roleid FROM ancestry AS a JOIN pg_catalog.pg_auth_members AS m ON m.member=a.ancestor
        )
        SELECT 1 FROM ancestry AS a JOIN pg_catalog.pg_roles AS origin ON origin.oid=a.origin
          JOIN pg_catalog.pg_roles AS ancestor ON ancestor.oid=a.ancestor
         WHERE a.ancestor<>a.origin
           AND NOT (origin.rolname IN ('modkit_runtime','modkit_reconciler') AND ancestor.rolname='modkit_operator')
    ) THEN
        RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='unsafe structural role ancestry';
    END IF;
    -- Literal private ABI. This checks available structure, not installed source
    -- identity or a readiness receipt. No alternate dependency digest is invented.
    FOR dependency IN SELECT * FROM (VALUES
        ('modkit_events._intent_valid(text,bytea,bytea,bytea,bytea,bytea,int4,bytea,bytea,bytea,bytea,bytea,bytea,bytea,bytea,text,int4,timestamptz,timestamptz)','bool','i',FALSE,FALSE),
        ('modkit_events._protected_frame_valid(bytea)','bool','i',FALSE,FALSE),
        ('modkit_events._protected_valid(bytea,text,bytea,bytea,bytea,bytea,timestamptz,bytea,text,bytea)','bool','i',FALSE,FALSE),
        ('modkit_events._instant_bytes(timestamptz)','bytea','i',FALSE,FALSE),
        ('modkit_events.e15(uuid)','record','s',TRUE,TRUE),
        ('modkit_events._job_payload_record_check()','trigger','v',TRUE,FALSE),
        ('modkit_events._inbox_record_check()','trigger','v',TRUE,FALSE),
        ('modkit_events._work_admission_immutable()','trigger','v',FALSE,FALSE)
    ) AS expected(identity,result_type,volatility,definer,returns_set) LOOP
        object_oid:=pg_catalog.to_regprocedure(dependency.identity);
        SELECT p.* INTO actual FROM pg_catalog.pg_proc AS p WHERE p.oid=object_oid;
        IF NOT FOUND OR actual.proowner<>owner_oid OR actual.prorettype<>pg_catalog.to_regtype(dependency.result_type)
           OR actual.provolatile::pg_catalog.text<>dependency.volatility OR actual.prosecdef<>dependency.definer
           OR actual.proretset<>dependency.returns_set OR actual.proisstrict
           OR actual.prokind<>'f' OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, pg_temp']::pg_catalog.text[]
           OR actual.prolang<>(SELECT l.oid FROM pg_catalog.pg_language AS l WHERE l.lanname='plpgsql') THEN
            RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='invalid structural helper ABI';
        END IF;
        IF EXISTS (SELECT 1 FROM pg_catalog.aclexplode(COALESCE(actual.proacl,
                     pg_catalog.acldefault('f',owner_oid))) AS acl WHERE acl.grantee=0) THEN
            RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='public structural helper access';
        END IF;
        -- E15 may have separately Events-owned public wrapper grants. Private
        -- helpers must remain unavailable to every restricted role.
        IF dependency.identity<>'modkit_events.e15(uuid)' AND EXISTS (
            SELECT 1 FROM pg_catalog.pg_roles AS r
             WHERE r.rolname IN ('modkit_runtime','modkit_reconciler','modkit_operator')
               AND pg_catalog.has_function_privilege(r.oid,object_oid,'EXECUTE')) THEN
            RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='restricted structural helper access';
        END IF;
    END LOOP;
    -- Exact E15 OUT layout: literal checked56, not merely RETURNS record.
    IF (SELECT pg_catalog.array_agg(pg_catalog.format_type(t.type_oid,NULL) ORDER BY t.position)
          FROM pg_catalog.pg_proc AS p,
               LATERAL pg_catalog.unnest(p.proallargtypes) WITH ORDINALITY AS t(type_oid,position)
         WHERE p.oid=pg_catalog.to_regprocedure('modkit_events.e15(uuid)') AND t.position>1)
       IS DISTINCT FROM ARRAY[
        'uuid','text','bytea','bytea','bytea','bytea','integer','integer','bytea','bytea','bytea','bytea',
        'bytea','bytea','bytea','bytea','bytea','text','integer','timestamp with time zone','timestamp with time zone',
        'text','boolean','uuid','bigint','timestamp with time zone','timestamp with time zone','integer','integer',
        'uuid','bytea','timestamp with time zone','timestamp with time zone','text','uuid','timestamp with time zone',
        'bytea','uuid','uuid','boolean','uuid','text','uuid','bigint','integer','integer','uuid','text',
        'timestamp with time zone','bytea','bytea','text','bytea','bytea','xid8','timestamp with time zone']::pg_catalog.text[] THEN
        RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='invalid structural reader layout';
    END IF;
    IF (SELECT p.proargnames[2:57] FROM pg_catalog.pg_proc AS p WHERE p.oid=pg_catalog.to_regprocedure('modkit_events.e15(uuid)'))
       IS DISTINCT FROM ARRAY['work_id','kind','subscription_id','namespace','command_type','schema_version_decimal','runnable_version','canonical_version','scope_evidence','scope_application','scope_tenant','scope_owner','idempotency_key','intent_evidence','semantic_input','replay_input','protected_binding','replay_policy','max_attempts','deadline','original_available_at','state','cancellation_requested','token','ownership_revision','lease_until','available_at','cycle','attempt_count','dispatch_id','result','created_at','updated_at','success_origin','completion_guard_id','final_fence_at','completion_result_digest','resolution_operation_id','terminal_resolution_operation_id','resolution_present','resolution_record_operation_id','resolution_record_operation_kind','resolution_record_work_id','resolution_record_expected_revision','resolution_record_cycle','resolution_record_attempt','resolution_record_dispatch_id','resolution_record_outcome','resolution_record_retry_at','resolution_record_result','resolution_record_result_digest','resolution_record_reason','resolution_record_evidence','resolution_record_binding','resolution_record_resolution_root_xid','resolution_record_recorded_at']::pg_catalog.text[]
       OR (SELECT p.proargmodes FROM pg_catalog.pg_proc AS p WHERE p.oid=pg_catalog.to_regprocedure('modkit_events.e15(uuid)'))
          IS DISTINCT FROM (ARRAY['i'::pg_catalog."char"] || pg_catalog.array_fill('t'::pg_catalog."char",ARRAY[56])) THEN
        RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='invalid structural reader names or modes';
    END IF;
    -- Every E15 relation and the only W01 sequence must share the actual owner.
    FOR dependency IN SELECT * FROM (VALUES
        ('work','r'),('job_payloads','r'),('work_history','r'),('inbox','r'),('subscriptions','r'),
        ('attempts','r'),('finalization_guards','r'),('mutation_operations','r'),('work_history_history_id_seq','S')
    ) AS expected(name,kind) LOOP
        object_oid:=pg_catalog.to_regclass('modkit_events.'||dependency.name);
        IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_class AS c WHERE c.oid=object_oid
             AND c.relowner=owner_oid AND c.relkind::pg_catalog.text=dependency.kind
             AND NOT c.relrowsecurity AND NOT c.relforcerowsecurity) THEN
            RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='invalid structural shared ownership';
        END IF;
        IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles AS r
             WHERE r.rolname IN ('modkit_runtime','modkit_reconciler','modkit_operator') AND
             CASE WHEN dependency.kind='S' THEN pg_catalog.has_sequence_privilege(r.oid,object_oid,'USAGE,UPDATE')
                  ELSE pg_catalog.has_table_privilege(r.oid,object_oid,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') END) THEN
            RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='restricted structural shared mutation access';
        END IF;
    END LOOP;
    -- Complete types/nullability of the three directly read/written row types.
    FOR dependency IN SELECT * FROM (VALUES
        ('work',ARRAY['work_id:uuid:1','kind:text:1','subscription_id:bytea:0','namespace:bytea:1','command_type:bytea:1',
         'schema_version_decimal:bytea:1','runnable_version:integer:0','canonical_version:integer:1','scope_evidence:bytea:1',
         'scope_application:bytea:1','scope_tenant:bytea:0','scope_owner:bytea:0','idempotency_key:bytea:0',
         'intent_evidence:bytea:1','semantic_input:bytea:1','replay_input:bytea:1','protected_binding:bytea:1','replay_policy:text:1',
         'max_attempts:integer:1','deadline:timestamp with time zone:0','original_available_at:timestamp with time zone:1',
         'state:text:1','cancellation_requested:boolean:1','token:uuid:0','ownership_revision:bigint:1',
         'lease_until:timestamp with time zone:0','available_at:timestamp with time zone:1','cycle:integer:1','attempt_count:integer:1',
         'dispatch_id:uuid:0','result:bytea:0','created_at:timestamp with time zone:1','updated_at:timestamp with time zone:1',
         'success_origin:text:0','completion_guard_id:uuid:0','final_fence_at:timestamp with time zone:0',
         'completion_result_digest:bytea:0','resolution_operation_id:uuid:0','terminal_resolution_operation_id:uuid:0']::pg_catalog.text[]),
        ('job_payloads',ARRAY['job_work_id:uuid:1','job_application:bytea:1','job_tenant:bytea:0','job_owner:bytea:0',
         'job_protected_binding:bytea:1','job_semantic_input:bytea:1','material_state:text:1','protected_sidecar:bytea:0',
         'protected_reference:bytea:0','protected_codec:bytea:0','protected_key_version:bytea:0',
         'protected_expires_at:timestamp with time zone:0','protected_recovery_metadata:bytea:1','protected_cleanup_policy:text:1',
         'projection_metadata:bytea:1']::pg_catalog.text[]),
        ('work_history',ARRAY['history_id:bigint:1','work_id:uuid:1','cycle:integer:1','attempt:integer:1','transition:text:1',
         'reason:text:1','token:uuid:0','ownership_revision:bigint:1','evidence:bytea:1','recorded_at:timestamp with time zone:1']::pg_catalog.text[])
    ) AS expected(name,columns) LOOP
        object_oid:=pg_catalog.to_regclass('modkit_events.'||dependency.name);
        IF (SELECT pg_catalog.array_agg(a.attname||':'||pg_catalog.format_type(a.atttypid,a.atttypmod)||':'||
                    CASE WHEN a.attnotnull THEN '1' ELSE '0' END ORDER BY a.attnum)
              FROM pg_catalog.pg_attribute AS a WHERE a.attrelid=object_oid AND a.attnum>0 AND NOT a.attisdropped)
           IS DISTINCT FROM dependency.columns
           OR EXISTS (SELECT 1 FROM pg_catalog.pg_constraint AS c WHERE c.conrelid=object_oid
                        AND (NOT c.convalidated OR c.condeferrable))
           OR NOT EXISTS (SELECT 1 FROM pg_catalog.pg_constraint AS c JOIN pg_catalog.pg_index AS i ON i.indexrelid=c.conindid
                           WHERE c.conrelid=object_oid AND c.contype='p' AND i.indisvalid AND i.indisready AND i.indisunique) THEN
            RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='invalid structural shared row profile';
        END IF;
    END LOOP;
    FOR dependency IN SELECT * FROM (VALUES
        ('work','work_pkey','p','PRIMARY KEY (work_id)'),
        ('job_payloads','job_payloads_pkey','p','PRIMARY KEY (job_work_id)'),
        ('job_payloads','job_payloads_work_fk','f','FOREIGN KEY (job_work_id) REFERENCES modkit_events.work(work_id) ON UPDATE RESTRICT ON DELETE RESTRICT'),
        ('work_history','work_history_pkey','p','PRIMARY KEY (history_id)'),
        ('work_history','work_history_work_id_fkey','f','FOREIGN KEY (work_id) REFERENCES modkit_events.work(work_id)')
    ) AS expected(relation,name,kind,definition) LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_constraint AS c
                        WHERE c.conrelid=pg_catalog.to_regclass('modkit_events.'||dependency.relation)
                          AND c.conname=dependency.name AND c.contype::pg_catalog.text=dependency.kind
                          AND c.convalidated AND NOT c.condeferrable
                          AND (CASE WHEN dependency.kind='p' THEN pg_catalog.pg_get_constraintdef(c.oid,TRUE)=dependency.definition
                               ELSE c.confrelid=pg_catalog.to_regclass('modkit_events.work')
                                    AND c.conkey=CASE WHEN dependency.relation='job_payloads' THEN ARRAY[1]::pg_catalog.int2[]
                                                     ELSE ARRAY[2]::pg_catalog.int2[] END
                                    AND c.confkey=ARRAY[1]::pg_catalog.int2[]
                                    AND c.confupdtype=CASE WHEN dependency.relation='job_payloads' THEN 'r'::pg_catalog."char" ELSE 'a'::pg_catalog."char" END
                                    AND c.confdeltype=CASE WHEN dependency.relation='job_payloads' THEN 'r'::pg_catalog."char" ELSE 'a'::pg_catalog."char" END END)) THEN
            RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='invalid structural key constraint';
        END IF;
    END LOOP;
    FOR dependency IN SELECT * FROM (VALUES
        ('job_payloads','job_payloads_application_valid'),('job_payloads','job_payloads_tenant_valid'),
        ('job_payloads','job_payloads_owner_valid'),('job_payloads','job_payloads_binding_size'),
        ('job_payloads','job_payloads_semantic_size'),('job_payloads','job_payloads_semantic_object'),
        ('job_payloads','job_payloads_material_state'),('job_payloads','job_payloads_sidecar_size'),
        ('job_payloads','job_payloads_reference_size'),('job_payloads','job_payloads_codec_valid'),
        ('job_payloads','job_payloads_key_valid'),('job_payloads','job_payloads_expiry_valid'),
        ('job_payloads','job_payloads_recovery_size'),('job_payloads','job_payloads_cleanup_policy'),
        ('job_payloads','job_payloads_projection_size'),('job_payloads','job_payloads_projection_object'),
        ('job_payloads','job_payloads_material_binding'),('work_history','history_current_cycle'),
        ('work_history','history_code_and_attempt'),('work_history','history_ownership_shape'),
        ('work_history','history_reason_shape'),('work_history','history_evidence_origin'),
        ('work_history','work_history_id_positive'),('work_history','work_history_time_supported')
    ) AS expected(relation,name) LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_constraint AS c
                        WHERE c.conrelid=pg_catalog.to_regclass('modkit_events.'||dependency.relation)
                          AND c.conname=dependency.name AND c.contype='c' AND c.convalidated AND NOT c.condeferrable) THEN
            RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='missing structural check constraint';
        END IF;
    END LOOP;
    -- Identity arbitration depends on this exact nondeferrable btree index.
    object_oid:=pg_catalog.to_regclass('modkit_events.work_key_identity');
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_index AS i JOIN pg_catalog.pg_class AS c ON c.oid=i.indexrelid
                   JOIN pg_catalog.pg_am AS am ON am.oid=c.relam
                   WHERE i.indexrelid=object_oid AND i.indrelid=pg_catalog.to_regclass('modkit_events.work')
                     AND i.indisunique AND i.indisvalid AND i.indisready AND i.indimmediate AND i.indnullsnotdistinct
                     AND i.indnkeyatts=6 AND i.indnatts=6 AND am.amname='btree'
                     AND pg_catalog.pg_get_expr(i.indpred,i.indrelid)= '(idempotency_key IS NOT NULL)'
                     AND pg_catalog.pg_get_indexdef(i.indexrelid,1,TRUE)='kind'
                     AND pg_catalog.pg_get_indexdef(i.indexrelid,2,TRUE)='sha256(subscription_id)'
                     AND pg_catalog.pg_get_indexdef(i.indexrelid,3,TRUE)='namespace'
                     AND pg_catalog.pg_get_indexdef(i.indexrelid,4,TRUE)='command_type'
                     AND pg_catalog.pg_get_indexdef(i.indexrelid,5,TRUE)='sha256(scope_evidence)'
                     AND pg_catalog.pg_get_indexdef(i.indexrelid,6,TRUE)='sha256(idempotency_key)') THEN
        RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='invalid structural key index';
    END IF;
    FOR dependency IN SELECT * FROM (VALUES
        ('work','work_admission_immutable','modkit_events._work_admission_immutable()',27),
        ('job_payloads','job_payload_record_check','modkit_events._job_payload_record_check()',31),
        ('inbox','inbox_record_check','modkit_events._inbox_record_check()',31)
    ) AS expected(relation,name,identity,event_mask) LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_trigger AS t
                       WHERE t.tgrelid=pg_catalog.to_regclass('modkit_events.'||dependency.relation)
                         AND t.tgname=dependency.name AND NOT t.tgisinternal AND t.tgenabled='O'
                         AND t.tgfoid=pg_catalog.to_regprocedure(dependency.identity)
                         AND t.tgtype=dependency.event_mask AND t.tgnargs=0
                         AND t.tgqual IS NULL AND NOT t.tgdeferrable AND t.tgattr=''::pg_catalog.int2vector)
           OR EXISTS (SELECT 1 FROM pg_catalog.pg_trigger AS t
                       WHERE t.tgrelid=pg_catalog.to_regclass('modkit_events.'||dependency.relation)
                         AND NOT t.tgisinternal AND t.tgname<>dependency.name) THEN
            RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='invalid structural writer trigger';
        END IF;
    END LOOP;
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_attribute AS a
                    WHERE a.attrelid=pg_catalog.to_regclass('modkit_events.work_history')
                      AND a.attname='history_id' AND a.attidentity='a')
       OR pg_catalog.pg_get_serial_sequence('modkit_events.work_history','history_id')::pg_catalog.regclass
          IS DISTINCT FROM pg_catalog.to_regclass('modkit_events.work_history_history_id_seq') THEN
        RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='invalid structural history identity';
    END IF;
    -- Trigger assumptions require ordinary origin execution, never replica bypass.
    IF pg_catalog.current_setting('session_replication_role') IS DISTINCT FROM 'origin' THEN
        RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='invalid structural writer profile';
    END IF;
END
$preflight$;
CREATE SCHEMA modkit_workers;
REVOKE ALL ON SCHEMA modkit_workers FROM PUBLIC;
REVOKE CREATE ON SCHEMA modkit_workers FROM modkit_runtime,modkit_reconciler,modkit_operator;

CREATE FUNCTION modkit_workers.w01(
    p_work_id pg_catalog.uuid,p_kind pg_catalog.text,p_subscription_id pg_catalog.bytea,
    p_namespace pg_catalog.bytea,p_command_type pg_catalog.bytea,
    p_scope_evidence pg_catalog.bytea,p_idempotency_key pg_catalog.bytea,
    p_canonical_version pg_catalog.int4,p_schema_version_decimal pg_catalog.bytea,
    p_scope_application pg_catalog.bytea,p_scope_tenant pg_catalog.bytea,p_scope_owner pg_catalog.bytea,
    p_intent_evidence pg_catalog.bytea,p_semantic_input pg_catalog.bytea,p_replay_input pg_catalog.bytea,
    p_protected_binding pg_catalog.bytea,p_replay_policy pg_catalog.text,p_max_attempts pg_catalog.int4,
    p_deadline pg_catalog.timestamptz,p_original_available_at pg_catalog.timestamptz,
    p_material_state pg_catalog.text,p_protected_sidecar pg_catalog.bytea,p_protected_reference pg_catalog.bytea,
    p_protected_codec pg_catalog.bytea,p_protected_key_version pg_catalog.bytea,p_protected_expires_at pg_catalog.timestamptz,
    p_protected_recovery_metadata pg_catalog.bytea,p_protected_cleanup_policy pg_catalog.text,p_projection_metadata pg_catalog.bytea
)
RETURNS TABLE(work_id pg_catalog.uuid,inserted pg_catalog.bool)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER CALLED ON NULL INPUT
SET search_path = pg_catalog, pg_temp AS $body$
DECLARE
    capture_pass pg_catalog.int4;
    selected_count pg_catalog.int4;
    present_count pg_catalog.int4;
    direct_seen pg_catalog.int4;
    key_seen pg_catalog.int4;
    previous_id pg_catalog.uuid;
    item pg_catalog.record;
    saved_one pg_catalog.record;
    raw_work modkit_events.work%ROWTYPE;
    job_half modkit_events.job_payloads%ROWTYPE;
    lost_reservation pg_catalog.bool:=FALSE;
    reserved pg_catalog.bool:=FALSE;
    affected pg_catalog.int8;
    generated_id pg_catalog.int8;
    creation_time pg_catalog.timestamptz;
    intake_time pg_catalog.timestamptz;
    runnable pg_catalog.int4:=NULL;
    initial_state pg_catalog.text;
    intake_code pg_catalog.text;
BEGIN
    -- P0: complete validation before any relation or sequence operation.
    IF pg_catalog.current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN
        RAISE EXCEPTION USING ERRCODE='PZ005',MESSAGE='unsupported transaction isolation';
    END IF;
    IF p_work_id IS NULL
       OR pg_catalog.convert_to(p_kind,'UTF8') IS DISTINCT FROM pg_catalog.convert_to('job','UTF8')
       OR p_subscription_id IS NOT NULL OR p_namespace IS DISTINCT FROM pg_catalog.convert_to('jobs','UTF8')
       OR (pg_catalog.convert_to(p_replay_policy,'UTF8') IN
           (pg_catalog.convert_to('disabled','UTF8'),pg_catalog.convert_to('application_safe','UTF8'))) IS NOT TRUE
       OR (pg_catalog.convert_to(p_material_state,'UTF8') IN
           (pg_catalog.convert_to('absent','UTF8'),pg_catalog.convert_to('present','UTF8'))) IS NOT TRUE
       OR (pg_catalog.convert_to(p_protected_cleanup_policy,'UTF8') IN
           (pg_catalog.convert_to('retain','UTF8'),pg_catalog.convert_to('erase_after_terminal','UTF8'))) IS NOT TRUE
       OR modkit_events._intent_valid(p_kind,p_subscription_id,p_namespace,p_command_type,
           p_scope_evidence,p_idempotency_key,p_canonical_version,p_schema_version_decimal,
           p_scope_application,p_scope_tenant,p_scope_owner,p_intent_evidence,p_semantic_input,p_replay_input,
           p_protected_binding,p_replay_policy,p_max_attempts,p_deadline,p_original_available_at) IS NOT TRUE
       OR modkit_events._protected_frame_valid(p_protected_binding) IS NOT TRUE
       OR modkit_events._protected_valid(p_protected_binding,p_material_state,p_protected_sidecar,p_protected_reference,
           p_protected_codec,p_protected_key_version,p_protected_expires_at,p_protected_recovery_metadata,
           p_protected_cleanup_policy,p_projection_metadata) IS NOT TRUE THEN
        RAISE EXCEPTION USING ERRCODE='PZ006',MESSAGE='invalid job admission arguments';
    END IF;
    -- Shared helper proved canonical positive decimal. Only then narrow int4.
    -- This is representability, not a claim of W05 handler capability.
    IF pg_catalog.octet_length(p_schema_version_decimal)<10
       OR (pg_catalog.octet_length(p_schema_version_decimal)=10
           AND p_schema_version_decimal<=pg_catalog.convert_to('2147483647','UTF8')) THEN
        runnable:=pg_catalog.convert_from(p_schema_version_decimal,'UTF8')::pg_catalog.int4;
    END IF;
    IF runnable IS NULL THEN initial_state:='blocked_schema'; intake_code:='intake_blocked';
    ELSE initial_state:='queued'; intake_code:='intake_runnable'; END IF;

    -- P1/P4: two bounded captures, second ONLY after actual reservation loss.
    -- No candidate, parent, advisory or global lock is acquired here.
    FOR capture_pass IN 1..2 LOOP
        IF capture_pass=2 AND NOT lost_reservation THEN
            RAISE EXCEPTION USING ERRCODE='PZ012',MESSAGE='invalid admission capture phase';
        END IF;
        selected_count:=0; present_count:=0; direct_seen:=0; key_seen:=0; previous_id:=NULL;
        FOR item IN
            WITH key_ids AS MATERIALIZED (
                SELECT stored.work_id FROM modkit_events.work AS stored
                 WHERE p_idempotency_key IS NOT NULL AND stored.idempotency_key IS NOT NULL
                   AND stored.kind='job' AND stored.subscription_id IS NULL
                   AND pg_catalog.sha256(stored.subscription_id) IS NOT DISTINCT FROM pg_catalog.sha256(p_subscription_id)
                   AND stored.namespace=p_namespace AND stored.command_type=p_command_type
                   AND pg_catalog.sha256(stored.scope_evidence)=pg_catalog.sha256(p_scope_evidence)
                   AND pg_catalog.sha256(stored.idempotency_key)=pg_catalog.sha256(p_idempotency_key)
            ), candidate_ids AS MATERIALIZED (
                SELECT paths.id,pg_catalog.bool_or(paths.direct_path) AS direct_path,
                       pg_catalog.bool_or(paths.key_path) AS key_path
                  FROM (SELECT p_work_id AS id,TRUE AS direct_path,FALSE AS key_path
                        UNION ALL SELECT k.work_id,FALSE,TRUE FROM key_ids AS k) AS paths
                 GROUP BY paths.id
            ), captured AS MATERIALIZED (
                SELECT c.id AS selected_id,c.direct_path,c.key_path,
                       actual.work_id IS NOT NULL AS raw_present,actual AS raw_work_row,
                       checked.work_id IS NOT NULL AS checked_present,
                       half.job_work_id IS NOT NULL AS half_present,half AS job_row,checked.*
                  FROM candidate_ids AS c
                  LEFT JOIN modkit_events.work AS actual ON actual.work_id=c.id
                  LEFT JOIN LATERAL modkit_events.e15(c.id) AS checked ON TRUE
                  LEFT JOIN modkit_events.job_payloads AS half ON half.job_work_id=c.id
            )
            SELECT (SELECT pg_catalog.count(*) FROM key_ids) AS raw_key_count,
                   (SELECT pg_catalog.count(*) FROM captured) AS captured_count,captured.*
              FROM captured ORDER BY selected_id
        LOOP
            selected_count:=selected_count+1;
            IF item.captured_count IS NULL OR item.captured_count<1 OR item.captured_count>2 OR selected_count>2
               OR item.raw_key_count IS NULL OR item.raw_key_count<0 OR item.raw_key_count>1
               OR item.selected_id IS NULL OR (previous_id IS NOT NULL AND item.selected_id<=previous_id)
               OR item.direct_path IS DISTINCT FROM (item.selected_id=p_work_id)
               OR item.key_path IS NULL OR (item.direct_path OR item.key_path) IS NOT TRUE
               OR item.raw_present IS DISTINCT FROM item.checked_present THEN
                RAISE EXCEPTION USING ERRCODE='PZ012',MESSAGE='invalid captured job family';
            END IF;
            previous_id:=item.selected_id;
            IF item.direct_path THEN direct_seen:=direct_seen+1; END IF;
            IF item.key_path THEN key_seen:=key_seen+1; END IF;
            raw_work:=item.raw_work_row; job_half:=item.job_row;
            IF item.checked_present IS DISTINCT FROM TRUE THEN
                -- E15 was invoked even for absent direct and checked BOTH halves.
                IF item.direct_path IS DISTINCT FROM TRUE OR item.key_path OR item.half_present IS DISTINCT FROM FALSE
                   OR raw_work.work_id IS NOT NULL
                   OR job_half.job_work_id IS NOT NULL
                   OR job_half.job_application IS NOT NULL
                   OR job_half.job_tenant IS NOT NULL
                   OR job_half.job_owner IS NOT NULL
                   OR job_half.job_protected_binding IS NOT NULL
                   OR job_half.job_semantic_input IS NOT NULL
                   OR job_half.material_state IS NOT NULL
                   OR job_half.protected_sidecar IS NOT NULL
                   OR job_half.protected_reference IS NOT NULL
                   OR job_half.protected_codec IS NOT NULL
                   OR job_half.protected_key_version IS NOT NULL
                   OR job_half.protected_expires_at IS NOT NULL
                   OR job_half.protected_recovery_metadata IS NOT NULL
                   OR job_half.protected_cleanup_policy IS NOT NULL
                   OR job_half.projection_metadata IS NOT NULL THEN
                    RAISE EXCEPTION USING ERRCODE='PZ012',MESSAGE='missing selected job member';
                END IF;
                CONTINUE;
            END IF;
            IF item.work_id IS DISTINCT FROM item.selected_id OR raw_work.work_id IS DISTINCT FROM item.selected_id THEN
                RAISE EXCEPTION USING ERRCODE='PZ012',MESSAGE='invalid captured job identity';
            END IF;
            -- E15 checked all mutable provenance; also prove its raw immutable
            -- projection and raw half bridge in this SAME calling-query snapshot.
            IF ROW(pg_catalog.convert_to(raw_work.kind,'UTF8'),raw_work.subscription_id,raw_work.namespace,raw_work.command_type,
                   raw_work.scope_evidence,raw_work.idempotency_key,raw_work.canonical_version,raw_work.schema_version_decimal,
                   raw_work.scope_application,raw_work.scope_tenant,raw_work.scope_owner,raw_work.intent_evidence,
                   raw_work.semantic_input,raw_work.replay_input,raw_work.protected_binding,
                   pg_catalog.convert_to(raw_work.replay_policy,'UTF8'),raw_work.max_attempts,raw_work.deadline,raw_work.original_available_at)
               IS DISTINCT FROM
               ROW(pg_catalog.convert_to(item.kind,'UTF8'),item.subscription_id,item.namespace,item.command_type,
                   item.scope_evidence,item.idempotency_key,item.canonical_version,item.schema_version_decimal,
                   item.scope_application,item.scope_tenant,item.scope_owner,item.intent_evidence,
                   item.semantic_input,item.replay_input,item.protected_binding,
                   pg_catalog.convert_to(item.replay_policy,'UTF8'),item.max_attempts,item.deadline,item.original_available_at) THEN
                RAISE EXCEPTION USING ERRCODE='PZ012',MESSAGE='invalid raw job projection';
            END IF;
            IF pg_catalog.convert_to(item.kind,'UTF8')=pg_catalog.convert_to('job','UTF8') THEN
                IF item.half_present IS DISTINCT FROM TRUE OR job_half.job_work_id IS DISTINCT FROM item.selected_id
                   OR item.subscription_id IS NOT NULL OR item.namespace IS DISTINCT FROM pg_catalog.convert_to('jobs','UTF8')
                   OR job_half.job_application IS DISTINCT FROM item.scope_application
                   OR job_half.job_tenant IS DISTINCT FROM item.scope_tenant OR job_half.job_owner IS DISTINCT FROM item.scope_owner
                   OR job_half.job_protected_binding IS DISTINCT FROM item.protected_binding
                   OR job_half.job_semantic_input IS DISTINCT FROM item.semantic_input
                   OR modkit_events._protected_valid(job_half.job_protected_binding,job_half.material_state,
                       job_half.protected_sidecar,job_half.protected_reference,job_half.protected_codec,job_half.protected_key_version,
                       job_half.protected_expires_at,job_half.protected_recovery_metadata,job_half.protected_cleanup_policy,
                       job_half.projection_metadata) IS NOT TRUE THEN
                    RAISE EXCEPTION USING ERRCODE='PZ012',MESSAGE='invalid captured job half';
                END IF;
            ELSIF pg_catalog.convert_to(item.kind,'UTF8')=pg_catalog.convert_to('inbox','UTF8') THEN
                -- Actual foreign inbox is validated through its own parent by E15.
                -- All raw nullable job fields must be absent, not merely its PK.
                IF item.direct_path IS DISTINCT FROM TRUE OR item.half_present IS DISTINCT FROM FALSE
                   OR job_half.job_work_id IS NOT NULL
                   OR job_half.job_application IS NOT NULL
                   OR job_half.job_tenant IS NOT NULL
                   OR job_half.job_owner IS NOT NULL
                   OR job_half.job_protected_binding IS NOT NULL
                   OR job_half.job_semantic_input IS NOT NULL
                   OR job_half.material_state IS NOT NULL
                   OR job_half.protected_sidecar IS NOT NULL
                   OR job_half.protected_reference IS NOT NULL
                   OR job_half.protected_codec IS NOT NULL
                   OR job_half.protected_key_version IS NOT NULL
                   OR job_half.protected_expires_at IS NOT NULL
                   OR job_half.protected_recovery_metadata IS NOT NULL
                   OR job_half.protected_cleanup_policy IS NOT NULL
                   OR job_half.projection_metadata IS NOT NULL THEN
                    RAISE EXCEPTION USING ERRCODE='PZ012',MESSAGE='invalid foreign job projection';
                END IF;
            ELSE
                RAISE EXCEPTION USING ERRCODE='PZ012',MESSAGE='invalid captured job kind';
            END IF;
            IF item.key_path AND (p_idempotency_key IS NULL OR item.idempotency_key IS NULL
               OR pg_catalog.convert_to(item.kind,'UTF8') IS DISTINCT FROM pg_catalog.convert_to('job','UTF8')
               OR item.subscription_id IS NOT NULL OR item.namespace IS DISTINCT FROM p_namespace
               OR item.command_type IS DISTINCT FROM p_command_type
               OR pg_catalog.sha256(item.scope_evidence) IS DISTINCT FROM pg_catalog.sha256(p_scope_evidence)
               OR pg_catalog.sha256(item.idempotency_key) IS DISTINCT FROM pg_catalog.sha256(p_idempotency_key)) THEN
                RAISE EXCEPTION USING ERRCODE='PZ012',MESSAGE='invalid captured job key path';
            END IF;
            present_count:=present_count+1;
            IF present_count=1 THEN saved_one:=item; END IF;
        END LOOP;
        -- ALL rows have passed integrity before ANY request conflict decision.
        IF selected_count<1 THEN
            RAISE EXCEPTION USING ERRCODE='PZ012',MESSAGE='missing job family capture';
        END IF;
        IF selected_count IS DISTINCT FROM item.captured_count OR direct_seen<>1
           OR key_seen IS DISTINCT FROM item.raw_key_count THEN
            RAISE EXCEPTION USING ERRCODE='PZ012',MESSAGE='invalid job family membership';
        END IF;
        IF present_count>1 THEN
            RAISE EXCEPTION USING ERRCODE='PZ002',MESSAGE='split job admission identity';
        END IF;
        IF present_count=1 THEN
            item:=saved_one;
            -- Both replays independently shared-validate to their semantic input.
            -- Only proposed UUID and raw replay spelling are excluded; first raw
            -- replay is never overwritten. Full raw scope/key/intent/binding match.
            IF ROW(pg_catalog.convert_to(item.kind,'UTF8'),item.subscription_id,item.namespace,item.command_type,
                   item.scope_evidence,item.idempotency_key,item.canonical_version,item.schema_version_decimal,
                   item.scope_application,item.scope_tenant,item.scope_owner,item.intent_evidence,item.semantic_input,
                   item.protected_binding,pg_catalog.convert_to(item.replay_policy,'UTF8'),item.max_attempts,
                   item.deadline,item.original_available_at)
               IS DISTINCT FROM
               ROW(pg_catalog.convert_to(p_kind,'UTF8'),p_subscription_id,p_namespace,p_command_type,
                   p_scope_evidence,p_idempotency_key,p_canonical_version,p_schema_version_decimal,
                   p_scope_application,p_scope_tenant,p_scope_owner,p_intent_evidence,p_semantic_input,
                   p_protected_binding,pg_catalog.convert_to(p_replay_policy,'UTF8'),p_max_attempts,
                   p_deadline,p_original_available_at) THEN
                RAISE EXCEPTION USING ERRCODE='PZ002',MESSAGE='job immutable intent conflict';
            END IF;
            RETURN QUERY SELECT item.work_id,FALSE;
            RETURN;
        END IF;
        IF capture_pass=2 OR lost_reservation THEN
            RAISE EXCEPTION USING ERRCODE='PZ012',MESSAGE='missing lost job reservation winner';
        END IF;
        -- Empty family ONLY: exactly ONE targetless reservation, covering PK/key.
        creation_time:=pg_catalog.clock_timestamp();
        IF modkit_events._instant_bytes(creation_time) IS NULL THEN
            RAISE EXCEPTION USING ERRCODE='PZ012',MESSAGE='unsupported job creation time';
        END IF;
        INSERT INTO modkit_events.work AS reservation
            (work_id,kind,subscription_id,namespace,command_type,schema_version_decimal,runnable_version,
             canonical_version,scope_evidence,scope_application,scope_tenant,scope_owner,idempotency_key,
             intent_evidence,semantic_input,replay_input,protected_binding,replay_policy,max_attempts,
             deadline,original_available_at,state,cancellation_requested,token,ownership_revision,
             lease_until,available_at,cycle,attempt_count,dispatch_id,result,created_at,updated_at,
             success_origin,completion_guard_id,final_fence_at,completion_result_digest,
             resolution_operation_id,terminal_resolution_operation_id)
            VALUES(p_work_id,p_kind,p_subscription_id,p_namespace,p_command_type,p_schema_version_decimal,runnable,
             p_canonical_version,p_scope_evidence,p_scope_application,p_scope_tenant,p_scope_owner,p_idempotency_key,
             p_intent_evidence,p_semantic_input,p_replay_input,p_protected_binding,p_replay_policy,p_max_attempts,
             p_deadline,p_original_available_at,initial_state,FALSE,NULL,0,NULL,p_original_available_at,1,0,
             NULL,NULL,creation_time,creation_time,NULL,NULL,NULL,NULL,NULL,NULL)
            ON CONFLICT DO NOTHING;
        GET DIAGNOSTICS affected=ROW_COUNT;
        IF affected=1 THEN reserved:=TRUE; EXIT;
        ELSIF affected<>0 THEN
            RAISE EXCEPTION USING ERRCODE='PZ012',MESSAGE='invalid job reservation count';
        END IF;
        lost_reservation:=TRUE;
        -- Next iteration executes ONE NEW complete capture after uniqueness wait.
        -- It may return a lawful duplicate. It cannot reinsert or extend locks.
    END LOOP;
    IF NOT reserved THEN
        RAISE EXCEPTION USING ERRCODE='PZ012',MESSAGE='unowned job reservation';
    END IF;
    -- P5: only our newly reserved Work. Job trigger's lock is self-owned.
    intake_time:=pg_catalog.clock_timestamp();
    IF modkit_events._instant_bytes(intake_time) IS NULL THEN
        RAISE EXCEPTION USING ERRCODE='PZ012',MESSAGE='unsupported job intake time';
    END IF;
    UPDATE modkit_events.work AS stored SET updated_at=intake_time WHERE stored.work_id=p_work_id;
    GET DIAGNOSTICS affected=ROW_COUNT;
    IF affected<>1 THEN RAISE EXCEPTION USING ERRCODE='PZ012',MESSAGE='missing reserved job'; END IF;
    INSERT INTO modkit_events.job_payloads
        (job_work_id,job_application,job_tenant,job_owner,job_protected_binding,job_semantic_input,
         material_state,protected_sidecar,protected_reference,protected_codec,protected_key_version,
         protected_expires_at,protected_recovery_metadata,protected_cleanup_policy,projection_metadata)
        VALUES(p_work_id,p_scope_application,p_scope_tenant,p_scope_owner,p_protected_binding,p_semantic_input,
         p_material_state,p_protected_sidecar,p_protected_reference,p_protected_codec,p_protected_key_version,
         p_protected_expires_at,p_protected_recovery_metadata,p_protected_cleanup_policy,p_projection_metadata);
    GET DIAGNOSTICS affected=ROW_COUNT;
    IF affected<>1 THEN RAISE EXCEPTION USING ERRCODE='PZ012',MESSAGE='invalid job subtype count'; END IF;
    INSERT INTO modkit_events.work_history AS history
        (work_id,cycle,attempt,transition,reason,token,ownership_revision,evidence,recorded_at)
        VALUES(p_work_id,1,0,intake_code,intake_code,NULL,0,''::pg_catalog.bytea,intake_time)
        RETURNING history.history_id INTO generated_id;
    GET DIAGNOSTICS affected=ROW_COUNT;
    IF affected<>1 OR generated_id IS NULL OR generated_id<=0 THEN
        RAISE EXCEPTION USING ERRCODE='PZ012',MESSAGE='invalid job intake receipt';
    END IF;
    -- Staged only: no same-command E15 proof, root commit or cleanup assertion.
    -- Native errors/cancellation propagate. Caller rolls back its root; sequence
    -- gaps remain lawful. Unknown COMMIT never authorizes automatic resubmission.
    RETURN QUERY SELECT p_work_id,TRUE;
END
$body$;
REVOKE ALL ON FUNCTION modkit_workers.w01(pg_catalog.uuid,pg_catalog.text,pg_catalog.bytea,pg_catalog.bytea,pg_catalog.bytea,pg_catalog.bytea,pg_catalog.bytea,pg_catalog.int4,pg_catalog.bytea,pg_catalog.bytea,pg_catalog.bytea,pg_catalog.bytea,pg_catalog.bytea,pg_catalog.bytea,pg_catalog.bytea,pg_catalog.bytea,pg_catalog.text,pg_catalog.int4,pg_catalog.timestamptz,pg_catalog.timestamptz,pg_catalog.text,pg_catalog.bytea,pg_catalog.bytea,pg_catalog.bytea,pg_catalog.bytea,pg_catalog.timestamptz,pg_catalog.bytea,pg_catalog.text,pg_catalog.bytea) FROM PUBLIC;
-- Refuse unintended function ACLs introduced by installer default privileges.
-- No default ACL is edited, no runtime authority granted by this draft.
DO $private_boundary$
DECLARE routine pg_catalog.regprocedure;
BEGIN
    routine:='modkit_workers.w01(uuid,text,bytea,bytea,bytea,bytea,bytea,int4,bytea,bytea,bytea,bytea,bytea,bytea,bytea,bytea,text,int4,timestamptz,timestamptz,text,bytea,bytea,bytea,bytea,timestamptz,bytea,text,bytea)'::pg_catalog.regprocedure;
    IF EXISTS (SELECT 1 FROM pg_catalog.pg_proc AS p,
                      LATERAL pg_catalog.aclexplode(COALESCE(p.proacl,pg_catalog.acldefault('f',p.proowner))) AS acl
                WHERE p.oid=routine AND acl.grantee<>p.proowner)
       OR EXISTS (SELECT 1 FROM pg_catalog.pg_namespace AS n,
                      LATERAL pg_catalog.aclexplode(COALESCE(n.nspacl,pg_catalog.acldefault('n',n.nspowner))) AS acl
                WHERE n.nspname='modkit_workers' AND acl.grantee<>n.nspowner) THEN
        RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='unsafe private Workers boundary';
    END IF;
END
$private_boundary$;

-- NOT_READY integration dependency guard; source only, never executed.
DO $workers_readers_preflight$
DECLARE
    owner_oid pg_catalog.oid;
    dependency pg_catalog.record;
    actual pg_catalog.record;
    reader_oid pg_catalog.oid;
    finder_oid pg_catalog.oid;
BEGIN
    SELECT r.oid INTO owner_oid FROM pg_catalog.pg_roles AS r
     WHERE r.rolname=CURRENT_USER AND NOT r.rolcanlogin AND NOT r.rolsuper
       AND NOT r.rolbypassrls AND NOT r.rolcreaterole AND NOT r.rolcreatedb AND NOT r.rolreplication;
    IF owner_oid IS NULL
       OR NOT EXISTS (SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname='modkit_workers' AND nspowner=owner_oid)
       OR NOT EXISTS (SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname='modkit_events' AND nspowner=owner_oid)
       OR NOT EXISTS (SELECT 1 FROM pg_catalog.pg_class WHERE oid=pg_catalog.to_regclass('modkit_events.job_payloads')
                       AND relowner=owner_oid AND relkind='r' AND NOT relrowsecurity AND NOT relforcerowsecurity) THEN
        RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='invalid job reader installation owner';
    END IF;
    FOR dependency IN SELECT * FROM (VALUES
        ('modkit_events.e15(uuid)','s',TRUE,TRUE,'record'),
        ('modkit_events.e17(uuid,text,bytea,bytea,bytea,bytea,bytea)','s',TRUE,TRUE,'record'),
        ('modkit_events._protected_valid(bytea,text,bytea,bytea,bytea,bytea,timestamptz,bytea,text,bytea)','i',FALSE,FALSE,'bool')
    ) AS expected(identity,volatility,definer,returns_set,result_type) LOOP
        SELECT p.* INTO actual FROM pg_catalog.pg_proc AS p WHERE p.oid=pg_catalog.to_regprocedure(dependency.identity);
        IF NOT FOUND OR actual.proowner<>owner_oid OR actual.provolatile::pg_catalog.text<>dependency.volatility
           OR actual.prosecdef<>dependency.definer OR actual.proretset<>dependency.returns_set
           OR actual.prorettype<>pg_catalog.to_regtype(dependency.result_type)
           OR actual.proisstrict OR actual.prokind<>'f'
           OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, pg_temp']::pg_catalog.text[]
           OR actual.prolang<>(SELECT oid FROM pg_catalog.pg_language WHERE lanname='plpgsql') THEN
            RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='invalid job reader dependency ABI';
        END IF;
        IF EXISTS (SELECT 1 FROM pg_catalog.aclexplode(COALESCE(actual.proacl,pg_catalog.acldefault('f',owner_oid))) AS acl WHERE acl.grantee=0) THEN
            RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='public job reader dependency';
        END IF;
    END LOOP;
    reader_oid:=pg_catalog.to_regprocedure('modkit_events.e15(uuid)');
    finder_oid:=pg_catalog.to_regprocedure('modkit_events.e17(uuid,text,bytea,bytea,bytea,bytea,bytea)');
    -- W01 preflight already checks E15 against literal checked56. Require E17's
    -- complete OUT suffix to match that same type/name/mode ABI, not just record.
    IF (SELECT proallargtypes[8:63] FROM pg_catalog.pg_proc WHERE oid=finder_oid)
       IS DISTINCT FROM (SELECT proallargtypes[2:57] FROM pg_catalog.pg_proc WHERE oid=reader_oid)
       OR (SELECT proargnames[8:63] FROM pg_catalog.pg_proc WHERE oid=finder_oid)
       IS DISTINCT FROM (SELECT proargnames[2:57] FROM pg_catalog.pg_proc WHERE oid=reader_oid)
       OR (SELECT proargmodes FROM pg_catalog.pg_proc WHERE oid=finder_oid)
       IS DISTINCT FROM (pg_catalog.array_fill('i'::pg_catalog."char",ARRAY[7]) || pg_catalog.array_fill('t'::pg_catalog."char",ARRAY[56])) THEN
        RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='invalid complete job candidate reader ABI';
    END IF;
END
$workers_readers_preflight$;

-- NOT_READY Workers reader SOURCE DRAFT. NOT AUTHORIZED TO APPLY.
-- External draft only: W01 frozen packet unchanged. SQL parser/DB behavior NOT_RUN.
-- Integration requires actual same restricted owner and reviewed E15/E17 ABI.

CREATE FUNCTION modkit_workers.w02(p_work_id pg_catalog.uuid)
RETURNS TABLE(
    work_id pg_catalog.uuid,
    kind pg_catalog.text,
    subscription_id pg_catalog.bytea,
    namespace pg_catalog.bytea,
    command_type pg_catalog.bytea,
    schema_version_decimal pg_catalog.bytea,
    runnable_version pg_catalog.int4,
    canonical_version pg_catalog.int4,
    scope_evidence pg_catalog.bytea,
    scope_application pg_catalog.bytea,
    scope_tenant pg_catalog.bytea,
    scope_owner pg_catalog.bytea,
    idempotency_key pg_catalog.bytea,
    intent_evidence pg_catalog.bytea,
    semantic_input pg_catalog.bytea,
    replay_input pg_catalog.bytea,
    protected_binding pg_catalog.bytea,
    replay_policy pg_catalog.text,
    max_attempts pg_catalog.int4,
    deadline pg_catalog.timestamptz,
    original_available_at pg_catalog.timestamptz,
    state pg_catalog.text,
    cancellation_requested pg_catalog.bool,
    token pg_catalog.uuid,
    ownership_revision pg_catalog.int8,
    lease_until pg_catalog.timestamptz,
    available_at pg_catalog.timestamptz,
    cycle pg_catalog.int4,
    attempt_count pg_catalog.int4,
    dispatch_id pg_catalog.uuid,
    result pg_catalog.bytea,
    created_at pg_catalog.timestamptz,
    updated_at pg_catalog.timestamptz,
    success_origin pg_catalog.text,
    completion_guard_id pg_catalog.uuid,
    final_fence_at pg_catalog.timestamptz,
    completion_result_digest pg_catalog.bytea,
    resolution_operation_id pg_catalog.uuid,
    terminal_resolution_operation_id pg_catalog.uuid,
    resolution_present pg_catalog.bool,
    resolution_record_operation_id pg_catalog.uuid,
    resolution_record_operation_kind pg_catalog.text,
    resolution_record_work_id pg_catalog.uuid,
    resolution_record_expected_revision pg_catalog.int8,
    resolution_record_cycle pg_catalog.int4,
    resolution_record_attempt pg_catalog.int4,
    resolution_record_dispatch_id pg_catalog.uuid,
    resolution_record_outcome pg_catalog.text,
    resolution_record_retry_at pg_catalog.timestamptz,
    resolution_record_result pg_catalog.bytea,
    resolution_record_result_digest pg_catalog.bytea,
    resolution_record_reason pg_catalog.text,
    resolution_record_evidence pg_catalog.bytea,
    resolution_record_binding pg_catalog.bytea,
    resolution_record_resolution_root_xid pg_catalog.xid8,
    resolution_record_recorded_at pg_catalog.timestamptz,
    job_work_id pg_catalog.uuid,
    job_application pg_catalog.bytea,
    job_tenant pg_catalog.bytea,
    job_owner pg_catalog.bytea,
    job_protected_binding pg_catalog.bytea,
    job_semantic_input pg_catalog.bytea,
    material_state pg_catalog.text,
    protected_sidecar pg_catalog.bytea,
    protected_reference pg_catalog.bytea,
    protected_codec pg_catalog.bytea,
    protected_key_version pg_catalog.bytea,
    protected_expires_at pg_catalog.timestamptz,
    protected_recovery_metadata pg_catalog.bytea,
    protected_cleanup_policy pg_catalog.text,
    projection_metadata pg_catalog.bytea
)
LANGUAGE plpgsql STABLE SECURITY DEFINER CALLED ON NULL INPUT
SET search_path = pg_catalog, pg_temp AS $body$
DECLARE
    item pg_catalog.record;
    saved_one pg_catalog.record;
    saved_two pg_catalog.record;
    checked_count pg_catalog.int4:=0;
    result_index pg_catalog.int4;
    previous_id pg_catalog.uuid;
BEGIN
    IF pg_catalog.current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN
        RAISE EXCEPTION USING ERRCODE='PZ005',MESSAGE='unsupported job reader isolation';
    END IF;
    IF p_work_id IS NULL THEN
        RAISE EXCEPTION USING ERRCODE='PZ006',MESSAGE='invalid job reader arguments';
    END IF;
    -- One complete invoking-query snapshot; no later relation repair.
    FOR item IN

        SELECT checked.*,j.*
          FROM (VALUES(p_work_id)) AS requested(id)
          LEFT JOIN LATERAL modkit_events.e15(requested.id) AS checked ON TRUE
          LEFT JOIN modkit_events.job_payloads AS j ON j.job_work_id=requested.id
    LOOP
        IF item.work_id IS NULL THEN
            IF item.job_work_id IS NOT NULL THEN
                RAISE EXCEPTION USING ERRCODE='PZ012',MESSAGE='orphan job reader half';
            END IF;
            RETURN;
        END IF;
        IF item.work_id IS DISTINCT FROM p_work_id THEN
            RAISE EXCEPTION USING ERRCODE='PZ012',MESSAGE='job reader identity mismatch';
        END IF;

        IF pg_catalog.convert_to(item.kind,'UTF8') = pg_catalog.convert_to('job','UTF8') THEN
            IF item.job_work_id IS NULL OR item.subscription_id IS NOT NULL
               OR item.namespace IS DISTINCT FROM pg_catalog.convert_to('jobs','UTF8')
               OR item.job_work_id IS DISTINCT FROM item.work_id
               OR item.job_application IS DISTINCT FROM item.scope_application
               OR item.job_tenant IS DISTINCT FROM item.scope_tenant
               OR item.job_owner IS DISTINCT FROM item.scope_owner
               OR item.job_protected_binding IS DISTINCT FROM item.protected_binding
               OR item.job_semantic_input IS DISTINCT FROM item.semantic_input
               OR modkit_events._protected_valid(item.job_protected_binding,item.material_state,
                    item.protected_sidecar,item.protected_reference,item.protected_codec,item.protected_key_version,
                    item.protected_expires_at,item.protected_recovery_metadata,item.protected_cleanup_policy,
                    item.projection_metadata) IS NOT TRUE THEN
                RAISE EXCEPTION USING ERRCODE='PZ012',MESSAGE='invalid complete job reader composition';
            END IF;
        ELSE
            RAISE EXCEPTION USING ERRCODE='PZ012',MESSAGE='requested work is not a job';
        END IF;

        checked_count:=checked_count+1;
        IF checked_count=1 THEN saved_one:=item;
        ELSE RAISE EXCEPTION USING ERRCODE='PZ012',MESSAGE='job reader cardinality exceeded';
        END IF;
    END LOOP;
    -- Entire family validated before output; project captured locals only.
    FOR result_index IN 1..checked_count LOOP
        IF result_index=1 THEN item:=saved_one; ELSE item:=saved_two; END IF;
        RETURN QUERY SELECT item.work_id,
            item.kind,
            item.subscription_id,
            item.namespace,
            item.command_type,
            item.schema_version_decimal,
            item.runnable_version,
            item.canonical_version,
            item.scope_evidence,
            item.scope_application,
            item.scope_tenant,
            item.scope_owner,
            item.idempotency_key,
            item.intent_evidence,
            item.semantic_input,
            item.replay_input,
            item.protected_binding,
            item.replay_policy,
            item.max_attempts,
            item.deadline,
            item.original_available_at,
            item.state,
            item.cancellation_requested,
            item.token,
            item.ownership_revision,
            item.lease_until,
            item.available_at,
            item.cycle,
            item.attempt_count,
            item.dispatch_id,
            item.result,
            item.created_at,
            item.updated_at,
            item.success_origin,
            item.completion_guard_id,
            item.final_fence_at,
            item.completion_result_digest,
            item.resolution_operation_id,
            item.terminal_resolution_operation_id,
            item.resolution_present,
            item.resolution_record_operation_id,
            item.resolution_record_operation_kind,
            item.resolution_record_work_id,
            item.resolution_record_expected_revision,
            item.resolution_record_cycle,
            item.resolution_record_attempt,
            item.resolution_record_dispatch_id,
            item.resolution_record_outcome,
            item.resolution_record_retry_at,
            item.resolution_record_result,
            item.resolution_record_result_digest,
            item.resolution_record_reason,
            item.resolution_record_evidence,
            item.resolution_record_binding,
            item.resolution_record_resolution_root_xid,
            item.resolution_record_recorded_at,
            item.job_work_id,
            item.job_application,
            item.job_tenant,
            item.job_owner,
            item.job_protected_binding,
            item.job_semantic_input,
            item.material_state,
            item.protected_sidecar,
            item.protected_reference,
            item.protected_codec,
            item.protected_key_version,
            item.protected_expires_at,
            item.protected_recovery_metadata,
            item.protected_cleanup_policy,
            item.projection_metadata;
    END LOOP;
END
$body$;
REVOKE ALL ON FUNCTION modkit_workers.w02(pg_catalog.uuid) FROM PUBLIC;

CREATE FUNCTION modkit_workers.w04(p_work_id pg_catalog.uuid,p_kind pg_catalog.text,p_subscription_id pg_catalog.bytea,
    p_namespace pg_catalog.bytea,p_command_type pg_catalog.bytea,p_scope_evidence pg_catalog.bytea,p_idempotency_key pg_catalog.bytea)
RETURNS TABLE(
    work_id pg_catalog.uuid,
    kind pg_catalog.text,
    subscription_id pg_catalog.bytea,
    namespace pg_catalog.bytea,
    command_type pg_catalog.bytea,
    schema_version_decimal pg_catalog.bytea,
    runnable_version pg_catalog.int4,
    canonical_version pg_catalog.int4,
    scope_evidence pg_catalog.bytea,
    scope_application pg_catalog.bytea,
    scope_tenant pg_catalog.bytea,
    scope_owner pg_catalog.bytea,
    idempotency_key pg_catalog.bytea,
    intent_evidence pg_catalog.bytea,
    semantic_input pg_catalog.bytea,
    replay_input pg_catalog.bytea,
    protected_binding pg_catalog.bytea,
    replay_policy pg_catalog.text,
    max_attempts pg_catalog.int4,
    deadline pg_catalog.timestamptz,
    original_available_at pg_catalog.timestamptz,
    state pg_catalog.text,
    cancellation_requested pg_catalog.bool,
    token pg_catalog.uuid,
    ownership_revision pg_catalog.int8,
    lease_until pg_catalog.timestamptz,
    available_at pg_catalog.timestamptz,
    cycle pg_catalog.int4,
    attempt_count pg_catalog.int4,
    dispatch_id pg_catalog.uuid,
    result pg_catalog.bytea,
    created_at pg_catalog.timestamptz,
    updated_at pg_catalog.timestamptz,
    success_origin pg_catalog.text,
    completion_guard_id pg_catalog.uuid,
    final_fence_at pg_catalog.timestamptz,
    completion_result_digest pg_catalog.bytea,
    resolution_operation_id pg_catalog.uuid,
    terminal_resolution_operation_id pg_catalog.uuid,
    resolution_present pg_catalog.bool,
    resolution_record_operation_id pg_catalog.uuid,
    resolution_record_operation_kind pg_catalog.text,
    resolution_record_work_id pg_catalog.uuid,
    resolution_record_expected_revision pg_catalog.int8,
    resolution_record_cycle pg_catalog.int4,
    resolution_record_attempt pg_catalog.int4,
    resolution_record_dispatch_id pg_catalog.uuid,
    resolution_record_outcome pg_catalog.text,
    resolution_record_retry_at pg_catalog.timestamptz,
    resolution_record_result pg_catalog.bytea,
    resolution_record_result_digest pg_catalog.bytea,
    resolution_record_reason pg_catalog.text,
    resolution_record_evidence pg_catalog.bytea,
    resolution_record_binding pg_catalog.bytea,
    resolution_record_resolution_root_xid pg_catalog.xid8,
    resolution_record_recorded_at pg_catalog.timestamptz,
    job_half_present pg_catalog.bool,
    job_work_id pg_catalog.uuid,
    job_application pg_catalog.bytea,
    job_tenant pg_catalog.bytea,
    job_owner pg_catalog.bytea,
    job_protected_binding pg_catalog.bytea,
    job_semantic_input pg_catalog.bytea,
    material_state pg_catalog.text,
    protected_sidecar pg_catalog.bytea,
    protected_reference pg_catalog.bytea,
    protected_codec pg_catalog.bytea,
    protected_key_version pg_catalog.bytea,
    protected_expires_at pg_catalog.timestamptz,
    protected_recovery_metadata pg_catalog.bytea,
    protected_cleanup_policy pg_catalog.text,
    projection_metadata pg_catalog.bytea
)
LANGUAGE plpgsql STABLE SECURITY DEFINER CALLED ON NULL INPUT
SET search_path = pg_catalog, pg_temp AS $body$
DECLARE
    item pg_catalog.record;
    saved_one pg_catalog.record;
    saved_two pg_catalog.record;
    checked_count pg_catalog.int4:=0;
    result_index pg_catalog.int4;
    previous_id pg_catalog.uuid;
BEGIN
    IF pg_catalog.current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN
        RAISE EXCEPTION USING ERRCODE='PZ005',MESSAGE='unsupported job reader isolation';
    END IF;
    IF p_work_id IS NULL OR pg_catalog.convert_to(p_kind,'UTF8') IS DISTINCT FROM pg_catalog.convert_to('job','UTF8')
       OR p_subscription_id IS NOT NULL OR p_namespace IS DISTINCT FROM pg_catalog.convert_to('jobs','UTF8') THEN
        RAISE EXCEPTION USING ERRCODE='PZ006',MESSAGE='invalid job reader arguments';
    END IF;
    -- One complete invoking-query snapshot; no later relation repair.
    FOR item IN

        SELECT checked.*,j.job_work_id IS NOT NULL AS job_half_present,j.*
          FROM modkit_events.e17(p_work_id,p_kind,p_subscription_id,p_namespace,
                                p_command_type,p_scope_evidence,p_idempotency_key) AS checked
          LEFT JOIN modkit_events.job_payloads AS j ON j.job_work_id=checked.work_id
         ORDER BY checked.work_id
    LOOP
        IF item.work_id IS NULL OR (previous_id IS NOT NULL AND item.work_id<=previous_id) THEN
            RAISE EXCEPTION USING ERRCODE='PZ012',MESSAGE='invalid job candidate ordering';
        END IF;
        previous_id:=item.work_id;

        IF pg_catalog.convert_to(item.kind,'UTF8') = pg_catalog.convert_to('job','UTF8') THEN
            IF item.job_work_id IS NULL OR item.subscription_id IS NOT NULL
               OR item.namespace IS DISTINCT FROM pg_catalog.convert_to('jobs','UTF8')
               OR item.job_work_id IS DISTINCT FROM item.work_id
               OR item.job_application IS DISTINCT FROM item.scope_application
               OR item.job_tenant IS DISTINCT FROM item.scope_tenant
               OR item.job_owner IS DISTINCT FROM item.scope_owner
               OR item.job_protected_binding IS DISTINCT FROM item.protected_binding
               OR item.job_semantic_input IS DISTINCT FROM item.semantic_input
               OR modkit_events._protected_valid(item.job_protected_binding,item.material_state,
                    item.protected_sidecar,item.protected_reference,item.protected_codec,item.protected_key_version,
                    item.protected_expires_at,item.protected_recovery_metadata,item.protected_cleanup_policy,
                    item.projection_metadata) IS NOT TRUE THEN
                RAISE EXCEPTION USING ERRCODE='PZ012',MESSAGE='invalid complete job reader composition';
            END IF;
        ELSE
            IF pg_catalog.convert_to(item.kind,'UTF8') IS DISTINCT FROM pg_catalog.convert_to('inbox','UTF8')
               OR item.job_half_present IS DISTINCT FROM FALSE OR item.job_work_id IS NOT NULL THEN
                RAISE EXCEPTION USING ERRCODE='PZ012',MESSAGE='invalid foreign job candidate';
            END IF;
        END IF;

        checked_count:=checked_count+1;
        IF checked_count=1 THEN saved_one:=item;
        ELSIF checked_count=2 THEN saved_two:=item;
        ELSE RAISE EXCEPTION USING ERRCODE='PZ012',MESSAGE='job reader cardinality exceeded';
        END IF;
    END LOOP;
    -- Entire family validated before output; project captured locals only.
    FOR result_index IN 1..checked_count LOOP
        IF result_index=1 THEN item:=saved_one; ELSE item:=saved_two; END IF;
        RETURN QUERY SELECT item.work_id,
            item.kind,
            item.subscription_id,
            item.namespace,
            item.command_type,
            item.schema_version_decimal,
            item.runnable_version,
            item.canonical_version,
            item.scope_evidence,
            item.scope_application,
            item.scope_tenant,
            item.scope_owner,
            item.idempotency_key,
            item.intent_evidence,
            item.semantic_input,
            item.replay_input,
            item.protected_binding,
            item.replay_policy,
            item.max_attempts,
            item.deadline,
            item.original_available_at,
            item.state,
            item.cancellation_requested,
            item.token,
            item.ownership_revision,
            item.lease_until,
            item.available_at,
            item.cycle,
            item.attempt_count,
            item.dispatch_id,
            item.result,
            item.created_at,
            item.updated_at,
            item.success_origin,
            item.completion_guard_id,
            item.final_fence_at,
            item.completion_result_digest,
            item.resolution_operation_id,
            item.terminal_resolution_operation_id,
            item.resolution_present,
            item.resolution_record_operation_id,
            item.resolution_record_operation_kind,
            item.resolution_record_work_id,
            item.resolution_record_expected_revision,
            item.resolution_record_cycle,
            item.resolution_record_attempt,
            item.resolution_record_dispatch_id,
            item.resolution_record_outcome,
            item.resolution_record_retry_at,
            item.resolution_record_result,
            item.resolution_record_result_digest,
            item.resolution_record_reason,
            item.resolution_record_evidence,
            item.resolution_record_binding,
            item.resolution_record_resolution_root_xid,
            item.resolution_record_recorded_at,
            item.job_half_present,
            item.job_work_id,
            item.job_application,
            item.job_tenant,
            item.job_owner,
            item.job_protected_binding,
            item.job_semantic_input,
            item.material_state,
            item.protected_sidecar,
            item.protected_reference,
            item.protected_codec,
            item.protected_key_version,
            item.protected_expires_at,
            item.protected_recovery_metadata,
            item.protected_cleanup_policy,
            item.projection_metadata;
    END LOOP;
END
$body$;
REVOKE ALL ON FUNCTION modkit_workers.w04(pg_catalog.uuid,pg_catalog.text,pg_catalog.bytea,pg_catalog.bytea,pg_catalog.bytea,pg_catalog.bytea,pg_catalog.bytea) FROM PUBLIC;

-- Refuse unintended function ACLs introduced by installer default privileges.
-- Match W01's private boundary; do not edit defaults or grant runtime authority.
DO $workers_readers_private_boundary$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_proc AS p,
            LATERAL pg_catalog.aclexplode(
                COALESCE(p.proacl,pg_catalog.acldefault('f',p.proowner))) AS acl
        WHERE p.oid IN (
            'modkit_workers.w02(uuid)'::pg_catalog.regprocedure,
            'modkit_workers.w04(uuid,text,bytea,bytea,bytea,bytea,bytea)'::pg_catalog.regprocedure)
          AND acl.grantee<>p.proowner
    ) OR EXISTS (
        SELECT 1 FROM pg_catalog.pg_namespace AS n,
            LATERAL pg_catalog.aclexplode(
                COALESCE(n.nspacl,pg_catalog.acldefault('n',n.nspowner))) AS acl
        WHERE n.nspname='modkit_workers' AND acl.grantee<>n.nspowner
    ) THEN
        RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='unsafe private Workers reader boundary';
    END IF;
END
$workers_readers_private_boundary$;


-- W03 source candidate / NOT_READY. Shared listing index is Events-owned.
-- Existing W01/readers preflights establish literal E15 and material helper ABI.
DO $workers_listing_preflight$
DECLARE
    owner_oid pg_catalog.oid;
    index_oid pg_catalog.oid;
BEGIN
    SELECT n.nspowner INTO owner_oid FROM pg_catalog.pg_namespace AS n
     WHERE n.nspname='modkit_workers' AND n.nspowner=CURRENT_USER::pg_catalog.regrole;
    index_oid:=pg_catalog.to_regclass('modkit_events.work_jobs_created_page');
    IF owner_oid IS NULL OR NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_index AS i
          JOIN pg_catalog.pg_class AS c ON c.oid=i.indexrelid
          JOIN pg_catalog.pg_am AS am ON am.oid=c.relam
         WHERE i.indexrelid=index_oid
           AND i.indrelid=pg_catalog.to_regclass('modkit_events.work')
           AND c.relowner=owner_oid AND c.relkind='i' AND am.amname='btree'
           AND i.indisvalid AND i.indisready AND i.indislive
           AND NOT i.indisunique AND NOT i.indisexclusion
           AND i.indnkeyatts=3 AND i.indnatts=3 AND i.indexprs IS NULL
           AND i.indoption='0 0 0'::pg_catalog.int2vector
           AND i.indcollation='0 0 0'::pg_catalog.oidvector
           AND pg_catalog.pg_get_indexdef(i.indexrelid,1,TRUE)='namespace'
           AND pg_catalog.pg_get_indexdef(i.indexrelid,2,TRUE)='created_at'
           AND pg_catalog.pg_get_indexdef(i.indexrelid,3,TRUE)='work_id'
           AND i.indclass=ARRAY[
               (SELECT o.oid FROM pg_catalog.pg_opclass AS o
                 WHERE o.opcnamespace='pg_catalog'::pg_catalog.regnamespace
                   AND o.opcname='bytea_ops' AND o.opcmethod=am.oid),
               (SELECT o.oid FROM pg_catalog.pg_opclass AS o
                 WHERE o.opcnamespace='pg_catalog'::pg_catalog.regnamespace
                   AND o.opcname='timestamptz_ops' AND o.opcmethod=am.oid),
               (SELECT o.oid FROM pg_catalog.pg_opclass AS o
                 WHERE o.opcnamespace='pg_catalog'::pg_catalog.regnamespace
                   AND o.opcname='uuid_ops' AND o.opcmethod=am.oid)]::pg_catalog.oidvector
           AND pg_catalog.pg_get_expr(i.indpred,i.indrelid)=
               '((kind COLLATE "C") = (''job''::text COLLATE "C"))'
    ) THEN
        RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='invalid job listing index';
    END IF;
END
$workers_listing_preflight$;

CREATE FUNCTION modkit_workers.w03(p_namespace pg_catalog.bytea,
    p_after_created_at pg_catalog.timestamptz,p_after_work_id pg_catalog.uuid,p_limit pg_catalog.int4)
RETURNS TABLE(
    work_id pg_catalog.uuid,
    kind pg_catalog.text,
    subscription_id pg_catalog.bytea,
    namespace pg_catalog.bytea,
    command_type pg_catalog.bytea,
    schema_version_decimal pg_catalog.bytea,
    runnable_version pg_catalog.int4,
    canonical_version pg_catalog.int4,
    scope_evidence pg_catalog.bytea,
    scope_application pg_catalog.bytea,
    scope_tenant pg_catalog.bytea,
    scope_owner pg_catalog.bytea,
    idempotency_key pg_catalog.bytea,
    intent_evidence pg_catalog.bytea,
    semantic_input pg_catalog.bytea,
    replay_input pg_catalog.bytea,
    protected_binding pg_catalog.bytea,
    replay_policy pg_catalog.text,
    max_attempts pg_catalog.int4,
    deadline pg_catalog.timestamptz,
    original_available_at pg_catalog.timestamptz,
    state pg_catalog.text,
    cancellation_requested pg_catalog.bool,
    token pg_catalog.uuid,
    ownership_revision pg_catalog.int8,
    lease_until pg_catalog.timestamptz,
    available_at pg_catalog.timestamptz,
    cycle pg_catalog.int4,
    attempt_count pg_catalog.int4,
    dispatch_id pg_catalog.uuid,
    result pg_catalog.bytea,
    created_at pg_catalog.timestamptz,
    updated_at pg_catalog.timestamptz,
    success_origin pg_catalog.text,
    completion_guard_id pg_catalog.uuid,
    final_fence_at pg_catalog.timestamptz,
    completion_result_digest pg_catalog.bytea,
    resolution_operation_id pg_catalog.uuid,
    terminal_resolution_operation_id pg_catalog.uuid,
    resolution_present pg_catalog.bool,
    resolution_record_operation_id pg_catalog.uuid,
    resolution_record_operation_kind pg_catalog.text,
    resolution_record_work_id pg_catalog.uuid,
    resolution_record_expected_revision pg_catalog.int8,
    resolution_record_cycle pg_catalog.int4,
    resolution_record_attempt pg_catalog.int4,
    resolution_record_dispatch_id pg_catalog.uuid,
    resolution_record_outcome pg_catalog.text,
    resolution_record_retry_at pg_catalog.timestamptz,
    resolution_record_result pg_catalog.bytea,
    resolution_record_result_digest pg_catalog.bytea,
    resolution_record_reason pg_catalog.text,
    resolution_record_evidence pg_catalog.bytea,
    resolution_record_binding pg_catalog.bytea,
    resolution_record_resolution_root_xid pg_catalog.xid8,
    resolution_record_recorded_at pg_catalog.timestamptz,
    job_work_id pg_catalog.uuid,
    job_application pg_catalog.bytea,
    job_tenant pg_catalog.bytea,
    job_owner pg_catalog.bytea,
    job_protected_binding pg_catalog.bytea,
    job_semantic_input pg_catalog.bytea,
    material_state pg_catalog.text,
    protected_sidecar pg_catalog.bytea,
    protected_reference pg_catalog.bytea,
    protected_codec pg_catalog.bytea,
    protected_key_version pg_catalog.bytea,
    protected_expires_at pg_catalog.timestamptz,
    protected_recovery_metadata pg_catalog.bytea,
    protected_cleanup_policy pg_catalog.text,
    projection_metadata pg_catalog.bytea
)
LANGUAGE plpgsql STABLE SECURITY DEFINER CALLED ON NULL INPUT
SET search_path = pg_catalog, pg_temp AS $body$
DECLARE
    item pg_catalog.record;
    checked_count pg_catalog.int4:=0;
    previous_created_at pg_catalog.timestamptz:=p_after_created_at;
    previous_id pg_catalog.uuid:=p_after_work_id;
BEGIN
    IF pg_catalog.current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN
        RAISE EXCEPTION USING ERRCODE='PZ005',MESSAGE='unsupported job listing isolation';
    END IF;
    IF p_namespace IS DISTINCT FROM pg_catalog.convert_to('jobs','UTF8')
       OR p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 256
       OR (p_after_created_at IS NULL) <> (p_after_work_id IS NULL)
       OR (p_after_created_at IS NOT NULL AND modkit_events._instant_bytes(p_after_created_at) IS NULL) THEN
        RAISE EXCEPTION USING ERRCODE='PZ006',MESSAGE='invalid job listing arguments';
    END IF;
    -- Both bounded branches and all complete evidence share one invoking-query
    -- snapshot. Only one branch is active; job filtering precedes either LIMIT.
    FOR item IN
        WITH page AS MATERIALIZED (
            (SELECT listed.work_id AS selected_work_id,listed.created_at AS selected_created_at
               FROM modkit_events.work AS listed
              WHERE p_after_created_at IS NULL AND listed.namespace=p_namespace
                AND listed.kind COLLATE pg_catalog."C" = 'job' COLLATE pg_catalog."C"
              ORDER BY listed.created_at,listed.work_id
              LIMIT p_limit)
            UNION ALL
            (SELECT listed.work_id AS selected_work_id,listed.created_at AS selected_created_at
               FROM modkit_events.work AS listed
              WHERE p_after_created_at IS NOT NULL AND listed.namespace=p_namespace
                AND listed.kind COLLATE pg_catalog."C" = 'job' COLLATE pg_catalog."C"
                AND (listed.created_at,listed.work_id)>(p_after_created_at,p_after_work_id)
              ORDER BY listed.created_at,listed.work_id
              LIMIT p_limit)
        )
        SELECT page.selected_work_id,page.selected_created_at,checked.*,j.*
          FROM page
          LEFT JOIN LATERAL modkit_events.e15(page.selected_work_id) AS checked ON TRUE
          LEFT JOIN modkit_events.job_payloads AS j ON j.job_work_id=page.selected_work_id
         ORDER BY page.selected_created_at,page.selected_work_id
    LOOP
        IF item.work_id IS NULL OR item.work_id IS DISTINCT FROM item.selected_work_id
           OR item.created_at IS DISTINCT FROM item.selected_created_at
           OR (previous_id IS NOT NULL
               AND (item.created_at,item.work_id)<=(previous_created_at,previous_id)) THEN
            RAISE EXCEPTION USING ERRCODE='PZ012',MESSAGE='invalid job listing identity or order';
        END IF;
        IF pg_catalog.convert_to(item.kind,'UTF8') IS DISTINCT FROM pg_catalog.convert_to('job','UTF8')
           OR item.subscription_id IS NOT NULL OR item.namespace IS DISTINCT FROM p_namespace
           OR item.job_work_id IS DISTINCT FROM item.work_id
           OR item.job_application IS DISTINCT FROM item.scope_application
           OR item.job_tenant IS DISTINCT FROM item.scope_tenant
           OR item.job_owner IS DISTINCT FROM item.scope_owner
           OR item.job_protected_binding IS DISTINCT FROM item.protected_binding
           OR item.job_semantic_input IS DISTINCT FROM item.semantic_input
           OR modkit_events._protected_valid(item.job_protected_binding,item.material_state,
                item.protected_sidecar,item.protected_reference,item.protected_codec,item.protected_key_version,
                item.protected_expires_at,item.protected_recovery_metadata,item.protected_cleanup_policy,
                item.projection_metadata) IS NOT TRUE THEN
            RAISE EXCEPTION USING ERRCODE='PZ012',MESSAGE='invalid complete job listing composition';
        END IF;
        checked_count:=checked_count+1;
        IF checked_count>p_limit THEN
            RAISE EXCEPTION USING ERRCODE='PZ012',MESSAGE='job listing cardinality exceeded';
        END IF;
        previous_created_at:=item.created_at;
        previous_id:=item.work_id;
        -- PL/pgSQL buffers this result until the whole function succeeds.
        -- A corrupt later family aborts the statement without releasing a prefix.
        RETURN QUERY SELECT item.work_id,
            item.kind,
            item.subscription_id,
            item.namespace,
            item.command_type,
            item.schema_version_decimal,
            item.runnable_version,
            item.canonical_version,
            item.scope_evidence,
            item.scope_application,
            item.scope_tenant,
            item.scope_owner,
            item.idempotency_key,
            item.intent_evidence,
            item.semantic_input,
            item.replay_input,
            item.protected_binding,
            item.replay_policy,
            item.max_attempts,
            item.deadline,
            item.original_available_at,
            item.state,
            item.cancellation_requested,
            item.token,
            item.ownership_revision,
            item.lease_until,
            item.available_at,
            item.cycle,
            item.attempt_count,
            item.dispatch_id,
            item.result,
            item.created_at,
            item.updated_at,
            item.success_origin,
            item.completion_guard_id,
            item.final_fence_at,
            item.completion_result_digest,
            item.resolution_operation_id,
            item.terminal_resolution_operation_id,
            item.resolution_present,
            item.resolution_record_operation_id,
            item.resolution_record_operation_kind,
            item.resolution_record_work_id,
            item.resolution_record_expected_revision,
            item.resolution_record_cycle,
            item.resolution_record_attempt,
            item.resolution_record_dispatch_id,
            item.resolution_record_outcome,
            item.resolution_record_retry_at,
            item.resolution_record_result,
            item.resolution_record_result_digest,
            item.resolution_record_reason,
            item.resolution_record_evidence,
            item.resolution_record_binding,
            item.resolution_record_resolution_root_xid,
            item.resolution_record_recorded_at,
            item.job_work_id,
            item.job_application,
            item.job_tenant,
            item.job_owner,
            item.job_protected_binding,
            item.job_semantic_input,
            item.material_state,
            item.protected_sidecar,
            item.protected_reference,
            item.protected_codec,
            item.protected_key_version,
            item.protected_expires_at,
            item.protected_recovery_metadata,
            item.protected_cleanup_policy,
            item.projection_metadata;
    END LOOP;
END
$body$;
REVOKE ALL ON FUNCTION modkit_workers.w03(pg_catalog.bytea,pg_catalog.timestamptz,pg_catalog.uuid,pg_catalog.int4) FROM PUBLIC;

DO $workers_listing_private_boundary$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_proc AS p,
            LATERAL pg_catalog.aclexplode(
                COALESCE(p.proacl,pg_catalog.acldefault('f',p.proowner))) AS acl
        WHERE p.oid='modkit_workers.w03(bytea,timestamptz,uuid,int4)'::pg_catalog.regprocedure
          AND acl.grantee<>p.proowner
    ) OR EXISTS (
        SELECT 1 FROM pg_catalog.pg_namespace AS n,
            LATERAL pg_catalog.aclexplode(
                COALESCE(n.nspacl,pg_catalog.acldefault('n',n.nspowner))) AS acl
        WHERE n.nspname='modkit_workers' AND acl.grantee<>n.nspowner
    ) THEN
        RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='unsafe private Workers listing boundary';
    END IF;
END
$workers_listing_private_boundary$;


-- W05 source candidate. Production resources and runtime qualification remain NOT_READY.
DO $workers_acquisition_preflight$
DECLARE
    owner_oid pg_catalog.oid;
    claim_abi pg_catalog.record;
    reader_abi pg_catalog.record;
BEGIN
    SELECT r.oid INTO owner_oid FROM pg_catalog.pg_roles AS r
      WHERE r.rolname=CURRENT_USER AND NOT r.rolcanlogin AND NOT r.rolsuper
        AND NOT r.rolbypassrls AND NOT r.rolcreaterole AND NOT r.rolcreatedb AND NOT r.rolreplication;
    SELECT p.* INTO claim_abi FROM pg_catalog.pg_proc AS p
      WHERE p.oid=pg_catalog.to_regprocedure(
        'modkit_events.e04(bytea,text,bytea[],int4[],int4,float8,uuid,int4)');
    SELECT p.* INTO reader_abi FROM pg_catalog.pg_proc AS p
      WHERE p.oid=pg_catalog.to_regprocedure('modkit_events.e15(uuid)');
    -- The preceding W01/readers guards pin Work39/job15/E15 checked56 and owner.
    IF owner_oid IS NULL OR claim_abi.oid IS NULL OR reader_abi.oid IS NULL
       OR claim_abi.proowner IS DISTINCT FROM owner_oid
       OR claim_abi.provolatile::pg_catalog.text IS DISTINCT FROM 'v'
       OR claim_abi.prosecdef IS DISTINCT FROM TRUE
       OR claim_abi.proretset IS DISTINCT FROM TRUE
       OR claim_abi.prorettype IS DISTINCT FROM pg_catalog.to_regtype('record')
       OR claim_abi.proisstrict IS DISTINCT FROM FALSE OR claim_abi.prokind IS DISTINCT FROM 'f'
       OR claim_abi.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, pg_temp']::pg_catalog.text[]
       OR claim_abi.prolang IS DISTINCT FROM (SELECT oid FROM pg_catalog.pg_language WHERE lanname='plpgsql')
       OR claim_abi.proargnames[1:8] IS DISTINCT FROM ARRAY[
          'p_namespace','p_kind','p_command_types','p_schema_versions',
          'p_limit','p_lease_seconds','p_scan_after','p_discovery_budget']::pg_catalog.text[]
       OR claim_abi.proargnames[9:12] IS DISTINCT FROM ARRAY[
          'record_type','visited','next_cursor','pass_exhausted']::pg_catalog.text[]
       OR claim_abi.proallargtypes[9:12] IS DISTINCT FROM ARRAY[
          pg_catalog.to_regtype('text')::pg_catalog.oid,pg_catalog.to_regtype('int4')::pg_catalog.oid,
          pg_catalog.to_regtype('uuid')::pg_catalog.oid,pg_catalog.to_regtype('bool')::pg_catalog.oid]
       OR claim_abi.proargnames[13:68] IS DISTINCT FROM reader_abi.proargnames[2:57]
       OR claim_abi.proallargtypes[13:68] IS DISTINCT FROM reader_abi.proallargtypes[2:57]
       OR claim_abi.proargmodes IS DISTINCT FROM
          (pg_catalog.array_fill('i'::pg_catalog."char",ARRAY[8]) ||
           pg_catalog.array_fill('t'::pg_catalog."char",ARRAY[60]))
       OR EXISTS (SELECT 1 FROM pg_catalog.aclexplode(
           COALESCE(claim_abi.proacl,pg_catalog.acldefault('f',owner_oid))) AS acl
           WHERE acl.grantee=0) THEN
        RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='invalid shared job acquisition ABI';
    END IF;
END
$workers_acquisition_preflight$;
CREATE FUNCTION modkit_workers.w05(
    p_namespace pg_catalog.bytea,
    p_command_types pg_catalog.bytea[],
    p_schema_versions pg_catalog.int4[],
    p_limit pg_catalog.int4,
    p_lease_seconds pg_catalog.float8,
    p_scan_after pg_catalog.uuid,
    p_discovery_budget pg_catalog.int4)
RETURNS TABLE(
    record_type pg_catalog.text,
    visited pg_catalog.int4,
    next_cursor pg_catalog.uuid,
    pass_exhausted pg_catalog.bool,
    work_id pg_catalog.uuid,
    kind pg_catalog.text,
    subscription_id pg_catalog.bytea,
    namespace pg_catalog.bytea,
    command_type pg_catalog.bytea,
    schema_version_decimal pg_catalog.bytea,
    runnable_version pg_catalog.int4,
    canonical_version pg_catalog.int4,
    scope_evidence pg_catalog.bytea,
    scope_application pg_catalog.bytea,
    scope_tenant pg_catalog.bytea,
    scope_owner pg_catalog.bytea,
    idempotency_key pg_catalog.bytea,
    intent_evidence pg_catalog.bytea,
    semantic_input pg_catalog.bytea,
    replay_input pg_catalog.bytea,
    protected_binding pg_catalog.bytea,
    replay_policy pg_catalog.text,
    max_attempts pg_catalog.int4,
    deadline pg_catalog.timestamptz,
    original_available_at pg_catalog.timestamptz,
    state pg_catalog.text,
    cancellation_requested pg_catalog.bool,
    token pg_catalog.uuid,
    ownership_revision pg_catalog.int8,
    lease_until pg_catalog.timestamptz,
    available_at pg_catalog.timestamptz,
    cycle pg_catalog.int4,
    attempt_count pg_catalog.int4,
    dispatch_id pg_catalog.uuid,
    result pg_catalog.bytea,
    created_at pg_catalog.timestamptz,
    updated_at pg_catalog.timestamptz,
    success_origin pg_catalog.text,
    completion_guard_id pg_catalog.uuid,
    final_fence_at pg_catalog.timestamptz,
    completion_result_digest pg_catalog.bytea,
    resolution_operation_id pg_catalog.uuid,
    terminal_resolution_operation_id pg_catalog.uuid,
    resolution_present pg_catalog.bool,
    resolution_record_operation_id pg_catalog.uuid,
    resolution_record_operation_kind pg_catalog.text,
    resolution_record_work_id pg_catalog.uuid,
    resolution_record_expected_revision pg_catalog.int8,
    resolution_record_cycle pg_catalog.int4,
    resolution_record_attempt pg_catalog.int4,
    resolution_record_dispatch_id pg_catalog.uuid,
    resolution_record_outcome pg_catalog.text,
    resolution_record_retry_at pg_catalog.timestamptz,
    resolution_record_result pg_catalog.bytea,
    resolution_record_result_digest pg_catalog.bytea,
    resolution_record_reason pg_catalog.text,
    resolution_record_evidence pg_catalog.bytea,
    resolution_record_binding pg_catalog.bytea,
    resolution_record_resolution_root_xid pg_catalog.xid8,
    resolution_record_recorded_at pg_catalog.timestamptz,
    job_work_id pg_catalog.uuid,
    job_application pg_catalog.bytea,
    job_tenant pg_catalog.bytea,
    job_owner pg_catalog.bytea,
    job_protected_binding pg_catalog.bytea,
    job_semantic_input pg_catalog.bytea,
    material_state pg_catalog.text,
    protected_sidecar pg_catalog.bytea,
    protected_reference pg_catalog.bytea,
    protected_codec pg_catalog.bytea,
    protected_key_version pg_catalog.bytea,
    protected_expires_at pg_catalog.timestamptz,
    protected_recovery_metadata pg_catalog.bytea,
    protected_cleanup_policy pg_catalog.text,
    projection_metadata pg_catalog.bytea
)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER CALLED ON NULL INPUT
SET search_path = pg_catalog, pg_temp AS $body$
DECLARE
    acquired pg_catalog.record;
    item pg_catalog.record;
    retained_claims modkit_events.work[] := ARRAY[]::modkit_events.work[];
    header_seen pg_catalog.bool := FALSE;
    visited_count pg_catalog.int4;
    cursor_value pg_catalog.uuid;
    exhausted_value pg_catalog.bool;
    item_count pg_catalog.int4 := 0;
    material_count pg_catalog.int4 := 0;
    previous_id pg_catalog.uuid := p_scan_after;
BEGIN
    IF pg_catalog.current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN
        RAISE EXCEPTION USING ERRCODE='PZ005',MESSAGE='unsupported job acquisition isolation';
    END IF;
    IF p_namespace IS DISTINCT FROM pg_catalog.convert_to('jobs','UTF8') THEN
        RAISE EXCEPTION USING ERRCODE='PZ006',MESSAGE='invalid job acquisition namespace';
    END IF;
    -- E04 owns validation, discovery, locks, claims, lease arithmetic and history.
    -- Fully consume its retained postimages before the separate material command.
    FOR acquired IN
        SELECT * FROM modkit_events.e04(p_namespace,'job',p_command_types,p_schema_versions,
            p_limit,p_lease_seconds,p_scan_after,p_discovery_budget)
    LOOP
        IF NOT header_seen THEN
            IF pg_catalog.convert_to(acquired.record_type,'UTF8') IS DISTINCT FROM
                   pg_catalog.convert_to('header','UTF8')
               OR acquired.visited IS NULL OR acquired.visited<0 OR acquired.visited>p_discovery_budget
               OR acquired.pass_exhausted IS NULL
               OR NOT (ROW(
                   acquired.work_id,
                   acquired.kind,
                   acquired.subscription_id,
                   acquired.namespace,
                   acquired.command_type,
                   acquired.schema_version_decimal,
                   acquired.runnable_version,
                   acquired.canonical_version,
                   acquired.scope_evidence,
                   acquired.scope_application,
                   acquired.scope_tenant,
                   acquired.scope_owner,
                   acquired.idempotency_key,
                   acquired.intent_evidence,
                   acquired.semantic_input,
                   acquired.replay_input,
                   acquired.protected_binding,
                   acquired.replay_policy,
                   acquired.max_attempts,
                   acquired.deadline,
                   acquired.original_available_at,
                   acquired.state,
                   acquired.cancellation_requested,
                   acquired.token,
                   acquired.ownership_revision,
                   acquired.lease_until,
                   acquired.available_at,
                   acquired.cycle,
                   acquired.attempt_count,
                   acquired.dispatch_id,
                   acquired.result,
                   acquired.created_at,
                   acquired.updated_at,
                   acquired.success_origin,
                   acquired.completion_guard_id,
                   acquired.final_fence_at,
                   acquired.completion_result_digest,
                   acquired.resolution_operation_id,
                   acquired.terminal_resolution_operation_id,
                   acquired.resolution_present,
                   acquired.resolution_record_operation_id,
                   acquired.resolution_record_operation_kind,
                   acquired.resolution_record_work_id,
                   acquired.resolution_record_expected_revision,
                   acquired.resolution_record_cycle,
                   acquired.resolution_record_attempt,
                   acquired.resolution_record_dispatch_id,
                   acquired.resolution_record_outcome,
                   acquired.resolution_record_retry_at,
                   acquired.resolution_record_result,
                   acquired.resolution_record_result_digest,
                   acquired.resolution_record_reason,
                   acquired.resolution_record_evidence,
                   acquired.resolution_record_binding,
                   acquired.resolution_record_resolution_root_xid,
                   acquired.resolution_record_recorded_at
               ) IS NULL) THEN
                RAISE EXCEPTION USING ERRCODE='PZ012',MESSAGE='invalid shared acquisition header';
            END IF;
            header_seen := TRUE;
            visited_count := acquired.visited;
            cursor_value := acquired.next_cursor;
            exhausted_value := acquired.pass_exhausted;
            CONTINUE;
        END IF;
        IF pg_catalog.convert_to(acquired.record_type,'UTF8') IS DISTINCT FROM
               pg_catalog.convert_to('item','UTF8')
           OR acquired.visited IS NOT NULL OR acquired.next_cursor IS NOT NULL
           OR acquired.pass_exhausted IS NOT NULL
           OR acquired.work_id IS NULL OR cursor_value IS NULL OR acquired.work_id>cursor_value
           OR (previous_id IS NOT NULL AND acquired.work_id<=previous_id)
           OR pg_catalog.convert_to(acquired.kind,'UTF8') IS DISTINCT FROM pg_catalog.convert_to('job','UTF8')
           OR acquired.namespace IS DISTINCT FROM p_namespace OR acquired.subscription_id IS NOT NULL
           OR pg_catalog.convert_to(acquired.state,'UTF8') IS DISTINCT FROM pg_catalog.convert_to('claimed','UTF8')
           OR acquired.cancellation_requested IS DISTINCT FROM FALSE
           OR acquired.token IS NULL OR acquired.ownership_revision IS NULL
           OR acquired.ownership_revision NOT BETWEEN 1 AND 9223372036854775806::pg_catalog.int8
           OR acquired.cycle IS DISTINCT FROM 1 OR acquired.attempt_count IS NULL
           OR acquired.max_attempts IS NULL OR acquired.attempt_count NOT BETWEEN 0 AND acquired.max_attempts-1
           OR acquired.lease_until IS NULL OR acquired.updated_at IS NULL
           OR acquired.lease_until<=acquired.updated_at
           OR (acquired.deadline IS NOT NULL AND acquired.lease_until>acquired.deadline)
           OR acquired.dispatch_id IS NOT NULL OR acquired.result IS NOT NULL
           OR acquired.success_origin IS NOT NULL OR acquired.completion_guard_id IS NOT NULL
           OR acquired.final_fence_at IS NOT NULL OR acquired.completion_result_digest IS NOT NULL
           OR acquired.resolution_operation_id IS NOT NULL OR acquired.terminal_resolution_operation_id IS NOT NULL
           OR NOT EXISTS (
               SELECT 1 FROM pg_catalog.generate_subscripts(p_command_types,1) AS capability(position)
               WHERE p_command_types[capability.position]=acquired.command_type
                 AND p_schema_versions[pg_catalog.array_lower(p_schema_versions,1)
                     +capability.position-pg_catalog.array_lower(p_command_types,1)]=acquired.runnable_version
           ) THEN
            RAISE EXCEPTION USING ERRCODE='PZ012',MESSAGE='invalid retained job claim';
        END IF;
        -- Validate the omitted provenance before re-emitting its identical constants.
        IF acquired.resolution_present IS DISTINCT FROM FALSE
           OR acquired.resolution_record_operation_id IS NOT NULL
           OR acquired.resolution_record_operation_kind IS NOT NULL
           OR acquired.resolution_record_work_id IS NOT NULL
           OR acquired.resolution_record_expected_revision IS NOT NULL
           OR acquired.resolution_record_cycle IS NOT NULL
           OR acquired.resolution_record_attempt IS NOT NULL
           OR acquired.resolution_record_dispatch_id IS NOT NULL
           OR acquired.resolution_record_outcome IS NOT NULL
           OR acquired.resolution_record_retry_at IS NOT NULL
           OR acquired.resolution_record_result IS NOT NULL
           OR acquired.resolution_record_result_digest IS NOT NULL
           OR acquired.resolution_record_reason IS NOT NULL
           OR acquired.resolution_record_evidence IS NOT NULL
           OR acquired.resolution_record_binding IS NOT NULL
           OR acquired.resolution_record_resolution_root_xid IS NOT NULL
           OR acquired.resolution_record_recorded_at IS NOT NULL
        THEN
            RAISE EXCEPTION USING ERRCODE='PZ012',MESSAGE='unexpected retained claim provenance';
        END IF;
        item_count := item_count+1;
        IF item_count>p_limit OR item_count>visited_count THEN
            RAISE EXCEPTION USING ERRCODE='PZ012',MESSAGE='job acquisition cardinality exceeded';
        END IF;
        previous_id := acquired.work_id;
        -- Retain the exact physical Work postimage. No Work/E15/W02 reread.
        retained_claims := pg_catalog.array_append(retained_claims,ROW(
            acquired.work_id,
            acquired.kind,
            acquired.subscription_id,
            acquired.namespace,
            acquired.command_type,
            acquired.schema_version_decimal,
            acquired.runnable_version,
            acquired.canonical_version,
            acquired.scope_evidence,
            acquired.scope_application,
            acquired.scope_tenant,
            acquired.scope_owner,
            acquired.idempotency_key,
            acquired.intent_evidence,
            acquired.semantic_input,
            acquired.replay_input,
            acquired.protected_binding,
            acquired.replay_policy,
            acquired.max_attempts,
            acquired.deadline,
            acquired.original_available_at,
            acquired.state,
            acquired.cancellation_requested,
            acquired.token,
            acquired.ownership_revision,
            acquired.lease_until,
            acquired.available_at,
            acquired.cycle,
            acquired.attempt_count,
            acquired.dispatch_id,
            acquired.result,
            acquired.created_at,
            acquired.updated_at,
            acquired.success_origin,
            acquired.completion_guard_id,
            acquired.final_fence_at,
            acquired.completion_result_digest,
            acquired.resolution_operation_id,
            acquired.terminal_resolution_operation_id
        )::modkit_events.work);
    END LOOP;
    IF NOT header_seen
       OR (visited_count=0 AND (item_count<>0 OR cursor_value IS DISTINCT FROM p_scan_after))
       OR (visited_count>0 AND (cursor_value IS NULL OR (p_scan_after IS NOT NULL AND cursor_value<=p_scan_after)))
       OR (exhausted_value AND (visited_count>=p_discovery_budget OR item_count>=p_limit)) THEN
        RAISE EXCEPTION USING ERRCODE='PZ012',MESSAGE='invalid complete job acquisition frame';
    END IF;
    -- PL/pgSQL buffers all rows until success. A late material error also aborts
    -- E04's claims/history in this statement; no prefix is released to the caller.
    RETURN QUERY SELECT 'header'::pg_catalog.text,visited_count,cursor_value,exhausted_value,
        NULL::pg_catalog.uuid,
        NULL::pg_catalog.text,
        NULL::pg_catalog.bytea,
        NULL::pg_catalog.bytea,
        NULL::pg_catalog.bytea,
        NULL::pg_catalog.bytea,
        NULL::pg_catalog.int4,
        NULL::pg_catalog.int4,
        NULL::pg_catalog.bytea,
        NULL::pg_catalog.bytea,
        NULL::pg_catalog.bytea,
        NULL::pg_catalog.bytea,
        NULL::pg_catalog.bytea,
        NULL::pg_catalog.bytea,
        NULL::pg_catalog.bytea,
        NULL::pg_catalog.bytea,
        NULL::pg_catalog.bytea,
        NULL::pg_catalog.text,
        NULL::pg_catalog.int4,
        NULL::pg_catalog.timestamptz,
        NULL::pg_catalog.timestamptz,
        NULL::pg_catalog.text,
        NULL::pg_catalog.bool,
        NULL::pg_catalog.uuid,
        NULL::pg_catalog.int8,
        NULL::pg_catalog.timestamptz,
        NULL::pg_catalog.timestamptz,
        NULL::pg_catalog.int4,
        NULL::pg_catalog.int4,
        NULL::pg_catalog.uuid,
        NULL::pg_catalog.bytea,
        NULL::pg_catalog.timestamptz,
        NULL::pg_catalog.timestamptz,
        NULL::pg_catalog.text,
        NULL::pg_catalog.uuid,
        NULL::pg_catalog.timestamptz,
        NULL::pg_catalog.bytea,
        NULL::pg_catalog.uuid,
        NULL::pg_catalog.uuid,
        NULL::pg_catalog.bool,
        NULL::pg_catalog.uuid,
        NULL::pg_catalog.text,
        NULL::pg_catalog.uuid,
        NULL::pg_catalog.int8,
        NULL::pg_catalog.int4,
        NULL::pg_catalog.int4,
        NULL::pg_catalog.uuid,
        NULL::pg_catalog.text,
        NULL::pg_catalog.timestamptz,
        NULL::pg_catalog.bytea,
        NULL::pg_catalog.bytea,
        NULL::pg_catalog.text,
        NULL::pg_catalog.bytea,
        NULL::pg_catalog.bytea,
        NULL::pg_catalog.xid8,
        NULL::pg_catalog.timestamptz,
        NULL::pg_catalog.uuid,
        NULL::pg_catalog.bytea,
        NULL::pg_catalog.bytea,
        NULL::pg_catalog.bytea,
        NULL::pg_catalog.bytea,
        NULL::pg_catalog.bytea,
        NULL::pg_catalog.text,
        NULL::pg_catalog.bytea,
        NULL::pg_catalog.bytea,
        NULL::pg_catalog.bytea,
        NULL::pg_catalog.bytea,
        NULL::pg_catalog.timestamptz,
        NULL::pg_catalog.bytea,
        NULL::pg_catalog.text,
        NULL::pg_catalog.bytea;
    -- A distinct VOLATILE-function command gets a fresh READ COMMITTED snapshot.
    -- It sees every producer E04 saw. Held Work locks plus the immutable/no-delete
    -- subtype writer contract preserve this postimage/material family.
    FOR item IN
        SELECT saved.*,j.*
          FROM pg_catalog.unnest(retained_claims) AS saved
          LEFT JOIN modkit_events.job_payloads AS j ON j.job_work_id=saved.work_id
          ORDER BY saved.work_id
    LOOP
        IF item.job_work_id IS NULL OR item.job_work_id IS DISTINCT FROM item.work_id
           OR item.job_application IS DISTINCT FROM item.scope_application
           OR item.job_tenant IS DISTINCT FROM item.scope_tenant
           OR item.job_owner IS DISTINCT FROM item.scope_owner
           OR item.job_protected_binding IS DISTINCT FROM item.protected_binding
           OR item.job_semantic_input IS DISTINCT FROM item.semantic_input
           OR modkit_events._protected_valid(item.job_protected_binding,item.material_state,
                item.protected_sidecar,item.protected_reference,item.protected_codec,item.protected_key_version,
                item.protected_expires_at,item.protected_recovery_metadata,item.protected_cleanup_policy,
                item.projection_metadata) IS NOT TRUE THEN
            RAISE EXCEPTION USING ERRCODE='PZ012',MESSAGE='invalid acquired job material composition';
        END IF;
        material_count := material_count+1;
        IF material_count>item_count THEN
            RAISE EXCEPTION USING ERRCODE='PZ012',MESSAGE='acquired material cardinality exceeded';
        END IF;
        RETURN QUERY SELECT 'item'::pg_catalog.text,NULL::pg_catalog.int4,NULL::pg_catalog.uuid,NULL::pg_catalog.bool,
            item.work_id,
            item.kind,
            item.subscription_id,
            item.namespace,
            item.command_type,
            item.schema_version_decimal,
            item.runnable_version,
            item.canonical_version,
            item.scope_evidence,
            item.scope_application,
            item.scope_tenant,
            item.scope_owner,
            item.idempotency_key,
            item.intent_evidence,
            item.semantic_input,
            item.replay_input,
            item.protected_binding,
            item.replay_policy,
            item.max_attempts,
            item.deadline,
            item.original_available_at,
            item.state,
            item.cancellation_requested,
            item.token,
            item.ownership_revision,
            item.lease_until,
            item.available_at,
            item.cycle,
            item.attempt_count,
            item.dispatch_id,
            item.result,
            item.created_at,
            item.updated_at,
            item.success_origin,
            item.completion_guard_id,
            item.final_fence_at,
            item.completion_result_digest,
            item.resolution_operation_id,
            item.terminal_resolution_operation_id,
            FALSE::pg_catalog.bool,
            NULL::pg_catalog.uuid,
            NULL::pg_catalog.text,
            NULL::pg_catalog.uuid,
            NULL::pg_catalog.int8,
            NULL::pg_catalog.int4,
            NULL::pg_catalog.int4,
            NULL::pg_catalog.uuid,
            NULL::pg_catalog.text,
            NULL::pg_catalog.timestamptz,
            NULL::pg_catalog.bytea,
            NULL::pg_catalog.bytea,
            NULL::pg_catalog.text,
            NULL::pg_catalog.bytea,
            NULL::pg_catalog.bytea,
            NULL::pg_catalog.xid8,
            NULL::pg_catalog.timestamptz,
            item.job_work_id,
            item.job_application,
            item.job_tenant,
            item.job_owner,
            item.job_protected_binding,
            item.job_semantic_input,
            item.material_state,
            item.protected_sidecar,
            item.protected_reference,
            item.protected_codec,
            item.protected_key_version,
            item.protected_expires_at,
            item.protected_recovery_metadata,
            item.protected_cleanup_policy,
            item.projection_metadata;
    END LOOP;
    IF material_count<>item_count THEN
        RAISE EXCEPTION USING ERRCODE='PZ012',MESSAGE='incomplete acquired material page';
    END IF;
END
$body$;
REVOKE ALL ON FUNCTION modkit_workers.w05(pg_catalog.bytea,pg_catalog.bytea[],pg_catalog.int4[],pg_catalog.int4,pg_catalog.float8,pg_catalog.uuid,pg_catalog.int4) FROM PUBLIC;

DO $workers_acquisition_private_boundary$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_proc AS p,
            LATERAL pg_catalog.aclexplode(
                COALESCE(p.proacl,pg_catalog.acldefault('f',p.proowner))) AS acl
        WHERE p.oid='modkit_workers.w05(bytea,bytea[],int4[],int4,float8,uuid,int4)'::pg_catalog.regprocedure
          AND acl.grantee<>p.proowner
    ) OR EXISTS (
        SELECT 1 FROM pg_catalog.pg_namespace AS n,
            LATERAL pg_catalog.aclexplode(
                COALESCE(n.nspacl,pg_catalog.acldefault('n',n.nspowner))) AS acl
        WHERE n.nspname='modkit_workers' AND acl.grantee<>n.nspowner
    ) THEN
        RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='unsafe private Workers acquisition boundary';
    END IF;
END
$workers_acquisition_private_boundary$;
