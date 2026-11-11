-- Workers explicit wrapper grants. Caller owns transaction and qualified closure verification.
DO $workers_grants_preflight$
DECLARE
    owner_oid pg_catalog.oid;
    workers_oid pg_catalog.oid;
    events_oid pg_catalog.oid;
    expected pg_catalog.record;
    p pg_catalog.pg_proc%ROWTYPE;
    role_row pg_catalog.record;
    object_row pg_catalog.record;
    known_functions pg_catalog.oid[] := ARRAY[]::pg_catalog.oid[];
    wanted_types pg_catalog.oid[];
    is_post pg_catalog.bool := FALSE;
BEGIN
    SELECT oid INTO owner_oid FROM pg_catalog.pg_roles
      WHERE rolname=CURRENT_USER AND NOT rolcanlogin AND NOT rolsuper
        AND NOT rolbypassrls AND NOT rolcreaterole AND NOT rolcreatedb AND NOT rolreplication;
    SELECT oid INTO workers_oid FROM pg_catalog.pg_namespace
      WHERE nspname='modkit_workers' AND nspowner=owner_oid;
    SELECT oid INTO events_oid FROM pg_catalog.pg_namespace
      WHERE nspname='modkit_events' AND nspowner=owner_oid;
    IF owner_oid IS NULL OR workers_oid IS NULL OR events_oid IS NULL
       OR pg_catalog.current_setting('server_version_num')::pg_catalog.int4<160000
       OR pg_catalog.current_setting('session_replication_role')<>'origin'
       OR NOT pg_catalog.has_database_privilege(owner_oid,pg_catalog.current_database(),'CREATE')
       OR (SELECT pg_catalog.count(*) FROM pg_catalog.pg_roles
           WHERE rolname IN ('modkit_runtime','modkit_reconciler','modkit_operator')
             AND oid<>owner_oid AND NOT rolcanlogin AND NOT rolsuper AND NOT rolbypassrls
             AND NOT rolcreaterole AND NOT rolcreatedb AND NOT rolreplication)<>3 THEN
        RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='invalid Workers grant owner or roles';
    END IF;
    -- Membership paths are checked regardless of INHERIT/SET option flags.
    IF EXISTS (
        WITH RECURSIVE ancestry(origin,ancestor) AS (
            SELECT oid,oid FROM pg_catalog.pg_roles
             WHERE oid=owner_oid OR rolname IN ('modkit_runtime','modkit_reconciler','modkit_operator')
            UNION
            SELECT a.origin,m.roleid FROM ancestry AS a
              JOIN pg_catalog.pg_auth_members AS m ON m.member=a.ancestor
        )
        SELECT 1 FROM ancestry AS a JOIN pg_catalog.pg_roles AS origin ON origin.oid=a.origin
          JOIN pg_catalog.pg_roles AS ancestor ON ancestor.oid=a.ancestor
         WHERE a.origin<>a.ancestor AND NOT
           (origin.rolname IN ('modkit_runtime','modkit_reconciler') AND ancestor.rolname='modkit_operator')
    ) THEN
        RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='unsafe Workers grant role ancestry';
    END IF;
    -- Only explicit owner global/target defaults are contamination; absent rows
    -- retain PostgreSQL built-ins. Initial function PUBLIC revocations still apply.
    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_default_acl AS d,
          LATERAL pg_catalog.aclexplode(d.defaclacl) AS acl
        WHERE d.defaclrole=owner_oid AND d.defaclnamespace IN (0,workers_oid)
          AND acl.grantee<>owner_oid
    ) THEN
        RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='unsafe Workers explicit default ACL';
    END IF;
    FOR expected IN SELECT * FROM (VALUES
        ('modkit_workers.w01(uuid,text,bytea,bytea,bytea,bytea,bytea,int4,bytea,bytea,bytea,bytea,bytea,bytea,bytea,bytea,text,int4,timestamptz,timestamptz,text,bytea,bytea,bytea,bytea,timestamptz,bytea,text,bytea)',29,ARRAY['p_work_id','p_kind','p_subscription_id','p_namespace','p_command_type','p_scope_evidence','p_idempotency_key','p_canonical_version','p_schema_version_decimal','p_scope_application','p_scope_tenant','p_scope_owner','p_intent_evidence','p_semantic_input','p_replay_input','p_protected_binding','p_replay_policy','p_max_attempts','p_deadline','p_original_available_at','p_material_state','p_protected_sidecar','p_protected_reference','p_protected_codec','p_protected_key_version','p_protected_expires_at','p_protected_recovery_metadata','p_protected_cleanup_policy','p_projection_metadata','work_id','inserted']::pg_catalog.text[],ARRAY['uuid','text','bytea','bytea','bytea','bytea','bytea','int4','bytea','bytea','bytea','bytea','bytea','bytea','bytea','bytea','text','int4','timestamptz','timestamptz','text','bytea','bytea','bytea','bytea','timestamptz','bytea','text','bytea','uuid','bool']::pg_catalog.text[],ARRAY['i','i','i','i','i','i','i','i','i','i','i','i','i','i','i','i','i','i','i','i','i','i','i','i','i','i','i','i','i','t','t']::pg_catalog.text[],'v','2de26e20290b0689c9907f77949ed49ba3c225850074a34d03c7b795ccc23a22',ARRAY['modkit_runtime']::pg_catalog.text[]),
        ('modkit_workers.w02(uuid)',1,ARRAY['p_work_id','work_id','kind','subscription_id','namespace','command_type','schema_version_decimal','runnable_version','canonical_version','scope_evidence','scope_application','scope_tenant','scope_owner','idempotency_key','intent_evidence','semantic_input','replay_input','protected_binding','replay_policy','max_attempts','deadline','original_available_at','state','cancellation_requested','token','ownership_revision','lease_until','available_at','cycle','attempt_count','dispatch_id','result','created_at','updated_at','success_origin','completion_guard_id','final_fence_at','completion_result_digest','resolution_operation_id','terminal_resolution_operation_id','resolution_present','resolution_record_operation_id','resolution_record_operation_kind','resolution_record_work_id','resolution_record_expected_revision','resolution_record_cycle','resolution_record_attempt','resolution_record_dispatch_id','resolution_record_outcome','resolution_record_retry_at','resolution_record_result','resolution_record_result_digest','resolution_record_reason','resolution_record_evidence','resolution_record_binding','resolution_record_resolution_root_xid','resolution_record_recorded_at','job_work_id','job_application','job_tenant','job_owner','job_protected_binding','job_semantic_input','material_state','protected_sidecar','protected_reference','protected_codec','protected_key_version','protected_expires_at','protected_recovery_metadata','protected_cleanup_policy','projection_metadata']::pg_catalog.text[],ARRAY['uuid','uuid','text','bytea','bytea','bytea','bytea','int4','int4','bytea','bytea','bytea','bytea','bytea','bytea','bytea','bytea','bytea','text','int4','timestamptz','timestamptz','text','bool','uuid','int8','timestamptz','timestamptz','int4','int4','uuid','bytea','timestamptz','timestamptz','text','uuid','timestamptz','bytea','uuid','uuid','bool','uuid','text','uuid','int8','int4','int4','uuid','text','timestamptz','bytea','bytea','text','bytea','bytea','xid8','timestamptz','uuid','bytea','bytea','bytea','bytea','bytea','text','bytea','bytea','bytea','bytea','timestamptz','bytea','text','bytea']::pg_catalog.text[],ARRAY['i','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t']::pg_catalog.text[],'s','6c5a320a0be8afb9a8fc6df0655569fa96cad55996c78b90a677565642072ce2',ARRAY['modkit_runtime','modkit_reconciler','modkit_operator']::pg_catalog.text[]),
        ('modkit_workers.w04(uuid,text,bytea,bytea,bytea,bytea,bytea)',7,ARRAY['p_work_id','p_kind','p_subscription_id','p_namespace','p_command_type','p_scope_evidence','p_idempotency_key','work_id','kind','subscription_id','namespace','command_type','schema_version_decimal','runnable_version','canonical_version','scope_evidence','scope_application','scope_tenant','scope_owner','idempotency_key','intent_evidence','semantic_input','replay_input','protected_binding','replay_policy','max_attempts','deadline','original_available_at','state','cancellation_requested','token','ownership_revision','lease_until','available_at','cycle','attempt_count','dispatch_id','result','created_at','updated_at','success_origin','completion_guard_id','final_fence_at','completion_result_digest','resolution_operation_id','terminal_resolution_operation_id','resolution_present','resolution_record_operation_id','resolution_record_operation_kind','resolution_record_work_id','resolution_record_expected_revision','resolution_record_cycle','resolution_record_attempt','resolution_record_dispatch_id','resolution_record_outcome','resolution_record_retry_at','resolution_record_result','resolution_record_result_digest','resolution_record_reason','resolution_record_evidence','resolution_record_binding','resolution_record_resolution_root_xid','resolution_record_recorded_at','job_half_present','job_work_id','job_application','job_tenant','job_owner','job_protected_binding','job_semantic_input','material_state','protected_sidecar','protected_reference','protected_codec','protected_key_version','protected_expires_at','protected_recovery_metadata','protected_cleanup_policy','projection_metadata']::pg_catalog.text[],ARRAY['uuid','text','bytea','bytea','bytea','bytea','bytea','uuid','text','bytea','bytea','bytea','bytea','int4','int4','bytea','bytea','bytea','bytea','bytea','bytea','bytea','bytea','bytea','text','int4','timestamptz','timestamptz','text','bool','uuid','int8','timestamptz','timestamptz','int4','int4','uuid','bytea','timestamptz','timestamptz','text','uuid','timestamptz','bytea','uuid','uuid','bool','uuid','text','uuid','int8','int4','int4','uuid','text','timestamptz','bytea','bytea','text','bytea','bytea','xid8','timestamptz','bool','uuid','bytea','bytea','bytea','bytea','bytea','text','bytea','bytea','bytea','bytea','timestamptz','bytea','text','bytea']::pg_catalog.text[],ARRAY['i','i','i','i','i','i','i','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t']::pg_catalog.text[],'s','ac70f1e303a5da1dc89dbb398d7d388639f7f574a93b099fc26de4c96205defe',ARRAY['modkit_runtime','modkit_reconciler','modkit_operator']::pg_catalog.text[]),
        ('modkit_workers.w03(bytea,timestamptz,uuid,int4)',4,ARRAY['p_namespace','p_after_created_at','p_after_work_id','p_limit','work_id','kind','subscription_id','namespace','command_type','schema_version_decimal','runnable_version','canonical_version','scope_evidence','scope_application','scope_tenant','scope_owner','idempotency_key','intent_evidence','semantic_input','replay_input','protected_binding','replay_policy','max_attempts','deadline','original_available_at','state','cancellation_requested','token','ownership_revision','lease_until','available_at','cycle','attempt_count','dispatch_id','result','created_at','updated_at','success_origin','completion_guard_id','final_fence_at','completion_result_digest','resolution_operation_id','terminal_resolution_operation_id','resolution_present','resolution_record_operation_id','resolution_record_operation_kind','resolution_record_work_id','resolution_record_expected_revision','resolution_record_cycle','resolution_record_attempt','resolution_record_dispatch_id','resolution_record_outcome','resolution_record_retry_at','resolution_record_result','resolution_record_result_digest','resolution_record_reason','resolution_record_evidence','resolution_record_binding','resolution_record_resolution_root_xid','resolution_record_recorded_at','job_work_id','job_application','job_tenant','job_owner','job_protected_binding','job_semantic_input','material_state','protected_sidecar','protected_reference','protected_codec','protected_key_version','protected_expires_at','protected_recovery_metadata','protected_cleanup_policy','projection_metadata']::pg_catalog.text[],ARRAY['bytea','timestamptz','uuid','int4','uuid','text','bytea','bytea','bytea','bytea','int4','int4','bytea','bytea','bytea','bytea','bytea','bytea','bytea','bytea','bytea','text','int4','timestamptz','timestamptz','text','bool','uuid','int8','timestamptz','timestamptz','int4','int4','uuid','bytea','timestamptz','timestamptz','text','uuid','timestamptz','bytea','uuid','uuid','bool','uuid','text','uuid','int8','int4','int4','uuid','text','timestamptz','bytea','bytea','text','bytea','bytea','xid8','timestamptz','uuid','bytea','bytea','bytea','bytea','bytea','text','bytea','bytea','bytea','bytea','timestamptz','bytea','text','bytea']::pg_catalog.text[],ARRAY['i','i','i','i','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t']::pg_catalog.text[],'s','cd353100335310e882d689a21b9b494e95872e86b16f30fd0b0c786ff733a6da',ARRAY['modkit_runtime','modkit_reconciler','modkit_operator']::pg_catalog.text[]),
        ('modkit_workers.w03(bytea,timestamptz,uuid,int4,int8)',5,ARRAY['p_namespace','p_after_created_at','p_after_work_id','p_limit','p_max_page_payload_bytes','work_id','kind','subscription_id','namespace','command_type','schema_version_decimal','runnable_version','canonical_version','scope_evidence','scope_application','scope_tenant','scope_owner','idempotency_key','intent_evidence','semantic_input','replay_input','protected_binding','replay_policy','max_attempts','deadline','original_available_at','state','cancellation_requested','token','ownership_revision','lease_until','available_at','cycle','attempt_count','dispatch_id','result','created_at','updated_at','success_origin','completion_guard_id','final_fence_at','completion_result_digest','resolution_operation_id','terminal_resolution_operation_id','resolution_present','resolution_record_operation_id','resolution_record_operation_kind','resolution_record_work_id','resolution_record_expected_revision','resolution_record_cycle','resolution_record_attempt','resolution_record_dispatch_id','resolution_record_outcome','resolution_record_retry_at','resolution_record_result','resolution_record_result_digest','resolution_record_reason','resolution_record_evidence','resolution_record_binding','resolution_record_resolution_root_xid','resolution_record_recorded_at','job_work_id','job_application','job_tenant','job_owner','job_protected_binding','job_semantic_input','material_state','protected_sidecar','protected_reference','protected_codec','protected_key_version','protected_expires_at','protected_recovery_metadata','protected_cleanup_policy','projection_metadata']::pg_catalog.text[],ARRAY['bytea','timestamptz','uuid','int4','int8','uuid','text','bytea','bytea','bytea','bytea','int4','int4','bytea','bytea','bytea','bytea','bytea','bytea','bytea','bytea','bytea','text','int4','timestamptz','timestamptz','text','bool','uuid','int8','timestamptz','timestamptz','int4','int4','uuid','bytea','timestamptz','timestamptz','text','uuid','timestamptz','bytea','uuid','uuid','bool','uuid','text','uuid','int8','int4','int4','uuid','text','timestamptz','bytea','bytea','text','bytea','bytea','xid8','timestamptz','uuid','bytea','bytea','bytea','bytea','bytea','text','bytea','bytea','bytea','bytea','timestamptz','bytea','text','bytea']::pg_catalog.text[],ARRAY['i','i','i','i','i','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t']::pg_catalog.text[],'s','a2770f4be92f4669b06cccecd790e6db13c7b6f5b0c29ae21c6fb1f18d2a4e52',ARRAY['modkit_runtime','modkit_reconciler','modkit_operator']::pg_catalog.text[]),
        ('modkit_workers.w05(bytea,bytea[],int4[],int4,float8,uuid,int4)',7,ARRAY['p_namespace','p_command_types','p_schema_versions','p_limit','p_lease_seconds','p_scan_after','p_discovery_budget','record_type','visited','next_cursor','pass_exhausted','work_id','kind','subscription_id','namespace','command_type','schema_version_decimal','runnable_version','canonical_version','scope_evidence','scope_application','scope_tenant','scope_owner','idempotency_key','intent_evidence','semantic_input','replay_input','protected_binding','replay_policy','max_attempts','deadline','original_available_at','state','cancellation_requested','token','ownership_revision','lease_until','available_at','cycle','attempt_count','dispatch_id','result','created_at','updated_at','success_origin','completion_guard_id','final_fence_at','completion_result_digest','resolution_operation_id','terminal_resolution_operation_id','resolution_present','resolution_record_operation_id','resolution_record_operation_kind','resolution_record_work_id','resolution_record_expected_revision','resolution_record_cycle','resolution_record_attempt','resolution_record_dispatch_id','resolution_record_outcome','resolution_record_retry_at','resolution_record_result','resolution_record_result_digest','resolution_record_reason','resolution_record_evidence','resolution_record_binding','resolution_record_resolution_root_xid','resolution_record_recorded_at','job_work_id','job_application','job_tenant','job_owner','job_protected_binding','job_semantic_input','material_state','protected_sidecar','protected_reference','protected_codec','protected_key_version','protected_expires_at','protected_recovery_metadata','protected_cleanup_policy','projection_metadata']::pg_catalog.text[],ARRAY['bytea','bytea[]','int4[]','int4','float8','uuid','int4','text','int4','uuid','bool','uuid','text','bytea','bytea','bytea','bytea','int4','int4','bytea','bytea','bytea','bytea','bytea','bytea','bytea','bytea','bytea','text','int4','timestamptz','timestamptz','text','bool','uuid','int8','timestamptz','timestamptz','int4','int4','uuid','bytea','timestamptz','timestamptz','text','uuid','timestamptz','bytea','uuid','uuid','bool','uuid','text','uuid','int8','int4','int4','uuid','text','timestamptz','bytea','bytea','text','bytea','bytea','xid8','timestamptz','uuid','bytea','bytea','bytea','bytea','bytea','text','bytea','bytea','bytea','bytea','timestamptz','bytea','text','bytea']::pg_catalog.text[],ARRAY['i','i','i','i','i','i','i','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t']::pg_catalog.text[],'v','5f7ee4f68b25fcc70e14244c5488bd6f6b9eb3c32e0932970ee79ab75652e9bb',ARRAY['modkit_runtime']::pg_catalog.text[]),
        ('modkit_workers.w05(bytea,bytea[],int4[],int4,float8,uuid,int4,int8)',8,ARRAY['p_namespace','p_command_types','p_schema_versions','p_limit','p_lease_seconds','p_scan_after','p_discovery_budget','p_max_page_payload_bytes','record_type','visited','next_cursor','pass_exhausted','work_id','kind','subscription_id','namespace','command_type','schema_version_decimal','runnable_version','canonical_version','scope_evidence','scope_application','scope_tenant','scope_owner','idempotency_key','intent_evidence','semantic_input','replay_input','protected_binding','replay_policy','max_attempts','deadline','original_available_at','state','cancellation_requested','token','ownership_revision','lease_until','available_at','cycle','attempt_count','dispatch_id','result','created_at','updated_at','success_origin','completion_guard_id','final_fence_at','completion_result_digest','resolution_operation_id','terminal_resolution_operation_id','resolution_present','resolution_record_operation_id','resolution_record_operation_kind','resolution_record_work_id','resolution_record_expected_revision','resolution_record_cycle','resolution_record_attempt','resolution_record_dispatch_id','resolution_record_outcome','resolution_record_retry_at','resolution_record_result','resolution_record_result_digest','resolution_record_reason','resolution_record_evidence','resolution_record_binding','resolution_record_resolution_root_xid','resolution_record_recorded_at','job_work_id','job_application','job_tenant','job_owner','job_protected_binding','job_semantic_input','material_state','protected_sidecar','protected_reference','protected_codec','protected_key_version','protected_expires_at','protected_recovery_metadata','protected_cleanup_policy','projection_metadata']::pg_catalog.text[],ARRAY['bytea','bytea[]','int4[]','int4','float8','uuid','int4','int8','text','int4','uuid','bool','uuid','text','bytea','bytea','bytea','bytea','int4','int4','bytea','bytea','bytea','bytea','bytea','bytea','bytea','bytea','bytea','text','int4','timestamptz','timestamptz','text','bool','uuid','int8','timestamptz','timestamptz','int4','int4','uuid','bytea','timestamptz','timestamptz','text','uuid','timestamptz','bytea','uuid','uuid','bool','uuid','text','uuid','int8','int4','int4','uuid','text','timestamptz','bytea','bytea','text','bytea','bytea','xid8','timestamptz','uuid','bytea','bytea','bytea','bytea','bytea','text','bytea','bytea','bytea','bytea','timestamptz','bytea','text','bytea']::pg_catalog.text[],ARRAY['i','i','i','i','i','i','i','i','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t']::pg_catalog.text[],'v','816e8850ff4d2b26bcbe016d230a60b86c80fd68fa0bb3526e1856f69f0253b8',ARRAY['modkit_runtime']::pg_catalog.text[])
    ) AS e(identity,input_count,names,types,modes,volatility,body_sha,roles) LOOP
        SELECT * INTO p FROM pg_catalog.pg_proc
          WHERE oid=pg_catalog.to_regprocedure(expected.identity);
        SELECT pg_catalog.array_agg(pg_catalog.to_regtype(t.name)::pg_catalog.oid ORDER BY t.pos)
          INTO wanted_types FROM pg_catalog.unnest(expected.types) WITH ORDINALITY AS t(name,pos);
        IF p.oid IS NULL OR p.pronamespace<>workers_oid OR p.proowner<>owner_oid
           OR p.prokind<>'f' OR p.prosecdef IS DISTINCT FROM TRUE
           OR p.proretset IS DISTINCT FROM TRUE OR p.prorettype<>pg_catalog.to_regtype('record')
           OR p.proisstrict OR p.proleakproof OR p.pronargdefaults<>0 OR p.provariadic<>0
           OR p.provolatile::pg_catalog.text<>expected.volatility
           OR p.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, pg_temp']::pg_catalog.text[]
           OR p.prolang IS DISTINCT FROM (SELECT oid FROM pg_catalog.pg_language WHERE lanname='plpgsql')
           OR p.pronargs<>expected.input_count OR p.proargnames IS DISTINCT FROM expected.names
           OR p.proallargtypes IS DISTINCT FROM wanted_types
           OR p.proargmodes::pg_catalog.text[] IS DISTINCT FROM expected.modes
           OR pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p.prosrc,'UTF8')),'hex')
                IS DISTINCT FROM expected.body_sha THEN
            RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='unexpected Workers function identity or ABI';
        END IF;
        known_functions:=pg_catalog.array_append(known_functions,p.oid);
        IF EXISTS (
            WITH wanted AS (
                SELECT acl.grantee,acl.grantor,acl.privilege_type,acl.is_grantable
                FROM pg_catalog.aclexplode(pg_catalog.acldefault('f',owner_oid)) AS acl
                WHERE acl.grantee=owner_oid
                UNION ALL
                SELECT r.oid,owner_oid,'EXECUTE'::pg_catalog.text,FALSE
                FROM pg_catalog.pg_roles AS r
                WHERE is_post AND r.rolname=ANY(expected.roles)
            ), actual AS (
                SELECT acl.grantee,acl.grantor,acl.privilege_type,acl.is_grantable
                FROM pg_catalog.aclexplode(COALESCE(p.proacl,pg_catalog.acldefault('f',owner_oid))) AS acl
            )
            (SELECT * FROM actual EXCEPT SELECT * FROM wanted)
            UNION ALL
            (SELECT * FROM wanted EXCEPT SELECT * FROM actual)
        ) THEN
            RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='unexpected Workers function ACL';
        END IF;
        FOR role_row IN SELECT oid,rolname FROM pg_catalog.pg_roles
          WHERE rolname IN ('modkit_runtime','modkit_reconciler','modkit_operator') LOOP
            IF pg_catalog.has_function_privilege(role_row.oid,p.oid,'EXECUTE')
                 IS DISTINCT FROM (is_post AND role_row.rolname=ANY(expected.roles)) THEN
                RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='unsafe effective Workers function access';
            END IF;
        END LOOP;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_catalog.pg_proc
               WHERE pronamespace=workers_oid AND NOT (oid=ANY(known_functions)))
       OR pg_catalog.cardinality(known_functions)<>7
       OR EXISTS (SELECT 1 FROM pg_catalog.pg_class WHERE relnamespace=workers_oid)
       OR EXISTS (SELECT 1 FROM pg_catalog.pg_type WHERE typnamespace=workers_oid) THEN
        RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='unexpected Workers object inventory';
    END IF;
    FOR object_row IN SELECT oid,nspowner,nspacl FROM pg_catalog.pg_namespace
      WHERE oid IN (workers_oid,events_oid) LOOP
        IF EXISTS (
            WITH wanted AS (
                SELECT acl.grantee,acl.grantor,acl.privilege_type,acl.is_grantable
                FROM pg_catalog.aclexplode(pg_catalog.acldefault('n',owner_oid)) AS acl
                UNION ALL
                SELECT r.oid,owner_oid,'USAGE'::pg_catalog.text,FALSE
                FROM pg_catalog.pg_roles AS r
                WHERE (is_post OR object_row.oid=events_oid)
                  AND r.rolname IN ('modkit_runtime','modkit_reconciler','modkit_operator')
            ), actual AS (
                SELECT acl.grantee,acl.grantor,acl.privilege_type,acl.is_grantable
                FROM pg_catalog.aclexplode(COALESCE(object_row.nspacl,
                  pg_catalog.acldefault('n',owner_oid))) AS acl
            )
            (SELECT * FROM actual EXCEPT SELECT * FROM wanted)
            UNION ALL
            (SELECT * FROM wanted EXCEPT SELECT * FROM actual)
        ) THEN
            RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='unexpected installation schema ACL';
        END IF;
        FOR role_row IN SELECT oid FROM pg_catalog.pg_roles
          WHERE rolname IN ('modkit_runtime','modkit_reconciler','modkit_operator') LOOP
            IF pg_catalog.has_schema_privilege(role_row.oid,object_row.oid,'USAGE')
                 IS DISTINCT FROM (is_post OR object_row.oid=events_oid)
               OR pg_catalog.has_schema_privilege(role_row.oid,object_row.oid,'CREATE') THEN
                RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='unsafe effective installation schema access';
            END IF;
        END LOOP;
    END LOOP;
    -- Events is an already qualified prerequisite, never repaired here.
    IF NOT EXISTS (SELECT 1 FROM modkit_events.schema_versions
                   WHERE component='events' AND version=1
                     AND pg_catalog.octet_length(migration_digest)=32
                     AND catalog_contract_id='modkit-pg-ab-2'
                     AND scope_format_id='MKSC-1' AND intent_format_id='MKPF-1'
                     AND applied_at IS NOT NULL) THEN
        RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='missing Events installation receipt';
    END IF;
    FOR object_row IN SELECT c.oid,c.relowner,c.relkind,c.relacl FROM pg_catalog.pg_class AS c
      WHERE c.relnamespace=events_oid AND c.relkind IN ('r','p','v','m','f','S') LOOP
        IF object_row.relowner<>owner_oid OR EXISTS (
            SELECT 1 FROM pg_catalog.aclexplode(COALESCE(object_row.relacl,
                pg_catalog.acldefault(CASE WHEN object_row.relkind='S' THEN 's'::pg_catalog."char"
                                          ELSE 'r'::pg_catalog."char" END,owner_oid))) AS acl
            WHERE acl.grantee<>owner_oid
        ) OR EXISTS (
            SELECT 1 FROM pg_catalog.pg_attribute AS a,
              LATERAL pg_catalog.aclexplode(a.attacl) AS acl
            WHERE a.attrelid=object_row.oid AND a.attnum>0 AND NOT a.attisdropped
              AND acl.grantee<>owner_oid
        ) THEN
            RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='unsafe Events direct relation or column ACL';
        END IF;
        FOR role_row IN SELECT oid FROM pg_catalog.pg_roles
          WHERE rolname IN ('modkit_runtime','modkit_reconciler','modkit_operator') LOOP
            IF (CASE WHEN object_row.relkind='S' THEN
                pg_catalog.has_sequence_privilege(role_row.oid,object_row.oid,'SELECT,USAGE,UPDATE')
               ELSE pg_catalog.has_table_privilege(role_row.oid,object_row.oid,
                       'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
                 OR EXISTS (SELECT 1 FROM pg_catalog.pg_attribute AS a
                    WHERE a.attrelid=object_row.oid AND a.attnum>0 AND NOT a.attisdropped
                      AND pg_catalog.has_column_privilege(role_row.oid,object_row.oid,a.attnum,
                          'SELECT,INSERT,UPDATE,REFERENCES')) END) THEN
                RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='unsafe effective Events data access';
            END IF;
        END LOOP;
    END LOOP;
    FOR object_row IN SELECT f.oid,f.proowner,f.proacl FROM pg_catalog.pg_proc AS f
      WHERE f.pronamespace=events_oid AND
        (pg_catalog.left(f.proname,1)='_' OR f.oid=pg_catalog.to_regprocedure(
         'modkit_events.e04(bytea,text,bytea[],int4[],int4,float8,uuid,int4,int8)')) LOOP
        IF object_row.proowner<>owner_oid OR EXISTS (
            SELECT 1 FROM pg_catalog.aclexplode(COALESCE(object_row.proacl,
              pg_catalog.acldefault('f',owner_oid))) AS acl WHERE acl.grantee<>owner_oid
        ) OR EXISTS (SELECT 1 FROM pg_catalog.pg_roles AS checked_role
            WHERE checked_role.rolname IN ('modkit_runtime','modkit_reconciler','modkit_operator')
              AND pg_catalog.has_function_privilege(checked_role.oid,object_row.oid,'EXECUTE')) THEN
            RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='unsafe Events private function access';
        END IF;
    END LOOP;
    -- Implicit row/array types retain PostgreSQL's ordinary NULL ACL behavior.
    -- The explicit private composite has its own existing PUBLIC revocation.
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_type AS t
                   WHERE t.oid=pg_catalog.to_regtype('modkit_events._parse_result')
                     AND t.typowner=owner_oid AND t.typacl IS NOT NULL)
       OR EXISTS (
          SELECT 1 FROM pg_catalog.pg_type AS t
          WHERE t.typnamespace=events_oid AND (
            t.typowner<>owner_oid
            OR NOT (
              (t.oid=pg_catalog.to_regtype('modkit_events._parse_result') AND t.typtype='c')
              OR (t.typtype='c' AND t.typacl IS NULL AND EXISTS (
                  SELECT 1 FROM pg_catalog.pg_class AS c
                  WHERE c.oid=t.typrelid AND c.reltype=t.oid
                    AND c.relnamespace=events_oid AND c.relowner=owner_oid
                    AND c.relkind IN ('r','p')))
              OR (t.typtype='b' AND t.typcategory='A' AND t.typacl IS NULL AND EXISTS (
                  SELECT 1 FROM pg_catalog.pg_type AS element
                  WHERE element.oid=t.typelem AND element.typarray=t.oid
                    AND element.typnamespace=events_oid AND element.typowner=owner_oid
                    AND element.typtype='c' AND
                    (element.oid=pg_catalog.to_regtype('modkit_events._parse_result')
                     OR EXISTS (SELECT 1 FROM pg_catalog.pg_class AS c
                         WHERE c.oid=element.typrelid AND c.reltype=element.oid
                           AND c.relnamespace=events_oid AND c.relowner=owner_oid
                           AND c.relkind IN ('r','p')))))
            )
            OR EXISTS (SELECT 1 FROM pg_catalog.aclexplode(t.typacl) AS acl
                       WHERE acl.grantee<>owner_oid OR acl.grantor<>owner_oid
                         OR acl.privilege_type<>'USAGE' OR acl.is_grantable)
          )
       ) THEN
        RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='unsafe Events explicit type ACL';
    END IF;
END
$workers_grants_preflight$;

GRANT USAGE ON SCHEMA modkit_workers TO modkit_runtime,modkit_reconciler,modkit_operator;
GRANT EXECUTE ON FUNCTION modkit_workers.w01(uuid,text,bytea,bytea,bytea,bytea,bytea,int4,bytea,bytea,bytea,bytea,bytea,bytea,bytea,bytea,text,int4,timestamptz,timestamptz,text,bytea,bytea,bytea,bytea,timestamptz,bytea,text,bytea) TO modkit_runtime;
GRANT EXECUTE ON FUNCTION modkit_workers.w02(uuid) TO modkit_runtime,modkit_reconciler,modkit_operator;
GRANT EXECUTE ON FUNCTION modkit_workers.w04(uuid,text,bytea,bytea,bytea,bytea,bytea) TO modkit_runtime,modkit_reconciler,modkit_operator;
GRANT EXECUTE ON FUNCTION modkit_workers.w03(bytea,timestamptz,uuid,int4) TO modkit_runtime,modkit_reconciler,modkit_operator;
GRANT EXECUTE ON FUNCTION modkit_workers.w03(bytea,timestamptz,uuid,int4,int8) TO modkit_runtime,modkit_reconciler,modkit_operator;
GRANT EXECUTE ON FUNCTION modkit_workers.w05(bytea,bytea[],int4[],int4,float8,uuid,int4) TO modkit_runtime;
GRANT EXECUTE ON FUNCTION modkit_workers.w05(bytea,bytea[],int4[],int4,float8,uuid,int4,int8) TO modkit_runtime;

DO $workers_grants_postflight$
DECLARE
    owner_oid pg_catalog.oid;
    workers_oid pg_catalog.oid;
    events_oid pg_catalog.oid;
    expected pg_catalog.record;
    p pg_catalog.pg_proc%ROWTYPE;
    role_row pg_catalog.record;
    object_row pg_catalog.record;
    known_functions pg_catalog.oid[] := ARRAY[]::pg_catalog.oid[];
    wanted_types pg_catalog.oid[];
    is_post pg_catalog.bool := TRUE;
BEGIN
    SELECT oid INTO owner_oid FROM pg_catalog.pg_roles
      WHERE rolname=CURRENT_USER AND NOT rolcanlogin AND NOT rolsuper
        AND NOT rolbypassrls AND NOT rolcreaterole AND NOT rolcreatedb AND NOT rolreplication;
    SELECT oid INTO workers_oid FROM pg_catalog.pg_namespace
      WHERE nspname='modkit_workers' AND nspowner=owner_oid;
    SELECT oid INTO events_oid FROM pg_catalog.pg_namespace
      WHERE nspname='modkit_events' AND nspowner=owner_oid;
    IF owner_oid IS NULL OR workers_oid IS NULL OR events_oid IS NULL
       OR pg_catalog.current_setting('server_version_num')::pg_catalog.int4<160000
       OR pg_catalog.current_setting('session_replication_role')<>'origin'
       OR NOT pg_catalog.has_database_privilege(owner_oid,pg_catalog.current_database(),'CREATE')
       OR (SELECT pg_catalog.count(*) FROM pg_catalog.pg_roles
           WHERE rolname IN ('modkit_runtime','modkit_reconciler','modkit_operator')
             AND oid<>owner_oid AND NOT rolcanlogin AND NOT rolsuper AND NOT rolbypassrls
             AND NOT rolcreaterole AND NOT rolcreatedb AND NOT rolreplication)<>3 THEN
        RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='invalid Workers grant owner or roles';
    END IF;
    -- Membership paths are checked regardless of INHERIT/SET option flags.
    IF EXISTS (
        WITH RECURSIVE ancestry(origin,ancestor) AS (
            SELECT oid,oid FROM pg_catalog.pg_roles
             WHERE oid=owner_oid OR rolname IN ('modkit_runtime','modkit_reconciler','modkit_operator')
            UNION
            SELECT a.origin,m.roleid FROM ancestry AS a
              JOIN pg_catalog.pg_auth_members AS m ON m.member=a.ancestor
        )
        SELECT 1 FROM ancestry AS a JOIN pg_catalog.pg_roles AS origin ON origin.oid=a.origin
          JOIN pg_catalog.pg_roles AS ancestor ON ancestor.oid=a.ancestor
         WHERE a.origin<>a.ancestor AND NOT
           (origin.rolname IN ('modkit_runtime','modkit_reconciler') AND ancestor.rolname='modkit_operator')
    ) THEN
        RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='unsafe Workers grant role ancestry';
    END IF;
    -- Only explicit owner global/target defaults are contamination; absent rows
    -- retain PostgreSQL built-ins. Initial function PUBLIC revocations still apply.
    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_default_acl AS d,
          LATERAL pg_catalog.aclexplode(d.defaclacl) AS acl
        WHERE d.defaclrole=owner_oid AND d.defaclnamespace IN (0,workers_oid)
          AND acl.grantee<>owner_oid
    ) THEN
        RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='unsafe Workers explicit default ACL';
    END IF;
    FOR expected IN SELECT * FROM (VALUES
        ('modkit_workers.w01(uuid,text,bytea,bytea,bytea,bytea,bytea,int4,bytea,bytea,bytea,bytea,bytea,bytea,bytea,bytea,text,int4,timestamptz,timestamptz,text,bytea,bytea,bytea,bytea,timestamptz,bytea,text,bytea)',29,ARRAY['p_work_id','p_kind','p_subscription_id','p_namespace','p_command_type','p_scope_evidence','p_idempotency_key','p_canonical_version','p_schema_version_decimal','p_scope_application','p_scope_tenant','p_scope_owner','p_intent_evidence','p_semantic_input','p_replay_input','p_protected_binding','p_replay_policy','p_max_attempts','p_deadline','p_original_available_at','p_material_state','p_protected_sidecar','p_protected_reference','p_protected_codec','p_protected_key_version','p_protected_expires_at','p_protected_recovery_metadata','p_protected_cleanup_policy','p_projection_metadata','work_id','inserted']::pg_catalog.text[],ARRAY['uuid','text','bytea','bytea','bytea','bytea','bytea','int4','bytea','bytea','bytea','bytea','bytea','bytea','bytea','bytea','text','int4','timestamptz','timestamptz','text','bytea','bytea','bytea','bytea','timestamptz','bytea','text','bytea','uuid','bool']::pg_catalog.text[],ARRAY['i','i','i','i','i','i','i','i','i','i','i','i','i','i','i','i','i','i','i','i','i','i','i','i','i','i','i','i','i','t','t']::pg_catalog.text[],'v','2de26e20290b0689c9907f77949ed49ba3c225850074a34d03c7b795ccc23a22',ARRAY['modkit_runtime']::pg_catalog.text[]),
        ('modkit_workers.w02(uuid)',1,ARRAY['p_work_id','work_id','kind','subscription_id','namespace','command_type','schema_version_decimal','runnable_version','canonical_version','scope_evidence','scope_application','scope_tenant','scope_owner','idempotency_key','intent_evidence','semantic_input','replay_input','protected_binding','replay_policy','max_attempts','deadline','original_available_at','state','cancellation_requested','token','ownership_revision','lease_until','available_at','cycle','attempt_count','dispatch_id','result','created_at','updated_at','success_origin','completion_guard_id','final_fence_at','completion_result_digest','resolution_operation_id','terminal_resolution_operation_id','resolution_present','resolution_record_operation_id','resolution_record_operation_kind','resolution_record_work_id','resolution_record_expected_revision','resolution_record_cycle','resolution_record_attempt','resolution_record_dispatch_id','resolution_record_outcome','resolution_record_retry_at','resolution_record_result','resolution_record_result_digest','resolution_record_reason','resolution_record_evidence','resolution_record_binding','resolution_record_resolution_root_xid','resolution_record_recorded_at','job_work_id','job_application','job_tenant','job_owner','job_protected_binding','job_semantic_input','material_state','protected_sidecar','protected_reference','protected_codec','protected_key_version','protected_expires_at','protected_recovery_metadata','protected_cleanup_policy','projection_metadata']::pg_catalog.text[],ARRAY['uuid','uuid','text','bytea','bytea','bytea','bytea','int4','int4','bytea','bytea','bytea','bytea','bytea','bytea','bytea','bytea','bytea','text','int4','timestamptz','timestamptz','text','bool','uuid','int8','timestamptz','timestamptz','int4','int4','uuid','bytea','timestamptz','timestamptz','text','uuid','timestamptz','bytea','uuid','uuid','bool','uuid','text','uuid','int8','int4','int4','uuid','text','timestamptz','bytea','bytea','text','bytea','bytea','xid8','timestamptz','uuid','bytea','bytea','bytea','bytea','bytea','text','bytea','bytea','bytea','bytea','timestamptz','bytea','text','bytea']::pg_catalog.text[],ARRAY['i','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t']::pg_catalog.text[],'s','6c5a320a0be8afb9a8fc6df0655569fa96cad55996c78b90a677565642072ce2',ARRAY['modkit_runtime','modkit_reconciler','modkit_operator']::pg_catalog.text[]),
        ('modkit_workers.w04(uuid,text,bytea,bytea,bytea,bytea,bytea)',7,ARRAY['p_work_id','p_kind','p_subscription_id','p_namespace','p_command_type','p_scope_evidence','p_idempotency_key','work_id','kind','subscription_id','namespace','command_type','schema_version_decimal','runnable_version','canonical_version','scope_evidence','scope_application','scope_tenant','scope_owner','idempotency_key','intent_evidence','semantic_input','replay_input','protected_binding','replay_policy','max_attempts','deadline','original_available_at','state','cancellation_requested','token','ownership_revision','lease_until','available_at','cycle','attempt_count','dispatch_id','result','created_at','updated_at','success_origin','completion_guard_id','final_fence_at','completion_result_digest','resolution_operation_id','terminal_resolution_operation_id','resolution_present','resolution_record_operation_id','resolution_record_operation_kind','resolution_record_work_id','resolution_record_expected_revision','resolution_record_cycle','resolution_record_attempt','resolution_record_dispatch_id','resolution_record_outcome','resolution_record_retry_at','resolution_record_result','resolution_record_result_digest','resolution_record_reason','resolution_record_evidence','resolution_record_binding','resolution_record_resolution_root_xid','resolution_record_recorded_at','job_half_present','job_work_id','job_application','job_tenant','job_owner','job_protected_binding','job_semantic_input','material_state','protected_sidecar','protected_reference','protected_codec','protected_key_version','protected_expires_at','protected_recovery_metadata','protected_cleanup_policy','projection_metadata']::pg_catalog.text[],ARRAY['uuid','text','bytea','bytea','bytea','bytea','bytea','uuid','text','bytea','bytea','bytea','bytea','int4','int4','bytea','bytea','bytea','bytea','bytea','bytea','bytea','bytea','bytea','text','int4','timestamptz','timestamptz','text','bool','uuid','int8','timestamptz','timestamptz','int4','int4','uuid','bytea','timestamptz','timestamptz','text','uuid','timestamptz','bytea','uuid','uuid','bool','uuid','text','uuid','int8','int4','int4','uuid','text','timestamptz','bytea','bytea','text','bytea','bytea','xid8','timestamptz','bool','uuid','bytea','bytea','bytea','bytea','bytea','text','bytea','bytea','bytea','bytea','timestamptz','bytea','text','bytea']::pg_catalog.text[],ARRAY['i','i','i','i','i','i','i','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t']::pg_catalog.text[],'s','ac70f1e303a5da1dc89dbb398d7d388639f7f574a93b099fc26de4c96205defe',ARRAY['modkit_runtime','modkit_reconciler','modkit_operator']::pg_catalog.text[]),
        ('modkit_workers.w03(bytea,timestamptz,uuid,int4)',4,ARRAY['p_namespace','p_after_created_at','p_after_work_id','p_limit','work_id','kind','subscription_id','namespace','command_type','schema_version_decimal','runnable_version','canonical_version','scope_evidence','scope_application','scope_tenant','scope_owner','idempotency_key','intent_evidence','semantic_input','replay_input','protected_binding','replay_policy','max_attempts','deadline','original_available_at','state','cancellation_requested','token','ownership_revision','lease_until','available_at','cycle','attempt_count','dispatch_id','result','created_at','updated_at','success_origin','completion_guard_id','final_fence_at','completion_result_digest','resolution_operation_id','terminal_resolution_operation_id','resolution_present','resolution_record_operation_id','resolution_record_operation_kind','resolution_record_work_id','resolution_record_expected_revision','resolution_record_cycle','resolution_record_attempt','resolution_record_dispatch_id','resolution_record_outcome','resolution_record_retry_at','resolution_record_result','resolution_record_result_digest','resolution_record_reason','resolution_record_evidence','resolution_record_binding','resolution_record_resolution_root_xid','resolution_record_recorded_at','job_work_id','job_application','job_tenant','job_owner','job_protected_binding','job_semantic_input','material_state','protected_sidecar','protected_reference','protected_codec','protected_key_version','protected_expires_at','protected_recovery_metadata','protected_cleanup_policy','projection_metadata']::pg_catalog.text[],ARRAY['bytea','timestamptz','uuid','int4','uuid','text','bytea','bytea','bytea','bytea','int4','int4','bytea','bytea','bytea','bytea','bytea','bytea','bytea','bytea','bytea','text','int4','timestamptz','timestamptz','text','bool','uuid','int8','timestamptz','timestamptz','int4','int4','uuid','bytea','timestamptz','timestamptz','text','uuid','timestamptz','bytea','uuid','uuid','bool','uuid','text','uuid','int8','int4','int4','uuid','text','timestamptz','bytea','bytea','text','bytea','bytea','xid8','timestamptz','uuid','bytea','bytea','bytea','bytea','bytea','text','bytea','bytea','bytea','bytea','timestamptz','bytea','text','bytea']::pg_catalog.text[],ARRAY['i','i','i','i','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t']::pg_catalog.text[],'s','cd353100335310e882d689a21b9b494e95872e86b16f30fd0b0c786ff733a6da',ARRAY['modkit_runtime','modkit_reconciler','modkit_operator']::pg_catalog.text[]),
        ('modkit_workers.w03(bytea,timestamptz,uuid,int4,int8)',5,ARRAY['p_namespace','p_after_created_at','p_after_work_id','p_limit','p_max_page_payload_bytes','work_id','kind','subscription_id','namespace','command_type','schema_version_decimal','runnable_version','canonical_version','scope_evidence','scope_application','scope_tenant','scope_owner','idempotency_key','intent_evidence','semantic_input','replay_input','protected_binding','replay_policy','max_attempts','deadline','original_available_at','state','cancellation_requested','token','ownership_revision','lease_until','available_at','cycle','attempt_count','dispatch_id','result','created_at','updated_at','success_origin','completion_guard_id','final_fence_at','completion_result_digest','resolution_operation_id','terminal_resolution_operation_id','resolution_present','resolution_record_operation_id','resolution_record_operation_kind','resolution_record_work_id','resolution_record_expected_revision','resolution_record_cycle','resolution_record_attempt','resolution_record_dispatch_id','resolution_record_outcome','resolution_record_retry_at','resolution_record_result','resolution_record_result_digest','resolution_record_reason','resolution_record_evidence','resolution_record_binding','resolution_record_resolution_root_xid','resolution_record_recorded_at','job_work_id','job_application','job_tenant','job_owner','job_protected_binding','job_semantic_input','material_state','protected_sidecar','protected_reference','protected_codec','protected_key_version','protected_expires_at','protected_recovery_metadata','protected_cleanup_policy','projection_metadata']::pg_catalog.text[],ARRAY['bytea','timestamptz','uuid','int4','int8','uuid','text','bytea','bytea','bytea','bytea','int4','int4','bytea','bytea','bytea','bytea','bytea','bytea','bytea','bytea','bytea','text','int4','timestamptz','timestamptz','text','bool','uuid','int8','timestamptz','timestamptz','int4','int4','uuid','bytea','timestamptz','timestamptz','text','uuid','timestamptz','bytea','uuid','uuid','bool','uuid','text','uuid','int8','int4','int4','uuid','text','timestamptz','bytea','bytea','text','bytea','bytea','xid8','timestamptz','uuid','bytea','bytea','bytea','bytea','bytea','text','bytea','bytea','bytea','bytea','timestamptz','bytea','text','bytea']::pg_catalog.text[],ARRAY['i','i','i','i','i','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t']::pg_catalog.text[],'s','a2770f4be92f4669b06cccecd790e6db13c7b6f5b0c29ae21c6fb1f18d2a4e52',ARRAY['modkit_runtime','modkit_reconciler','modkit_operator']::pg_catalog.text[]),
        ('modkit_workers.w05(bytea,bytea[],int4[],int4,float8,uuid,int4)',7,ARRAY['p_namespace','p_command_types','p_schema_versions','p_limit','p_lease_seconds','p_scan_after','p_discovery_budget','record_type','visited','next_cursor','pass_exhausted','work_id','kind','subscription_id','namespace','command_type','schema_version_decimal','runnable_version','canonical_version','scope_evidence','scope_application','scope_tenant','scope_owner','idempotency_key','intent_evidence','semantic_input','replay_input','protected_binding','replay_policy','max_attempts','deadline','original_available_at','state','cancellation_requested','token','ownership_revision','lease_until','available_at','cycle','attempt_count','dispatch_id','result','created_at','updated_at','success_origin','completion_guard_id','final_fence_at','completion_result_digest','resolution_operation_id','terminal_resolution_operation_id','resolution_present','resolution_record_operation_id','resolution_record_operation_kind','resolution_record_work_id','resolution_record_expected_revision','resolution_record_cycle','resolution_record_attempt','resolution_record_dispatch_id','resolution_record_outcome','resolution_record_retry_at','resolution_record_result','resolution_record_result_digest','resolution_record_reason','resolution_record_evidence','resolution_record_binding','resolution_record_resolution_root_xid','resolution_record_recorded_at','job_work_id','job_application','job_tenant','job_owner','job_protected_binding','job_semantic_input','material_state','protected_sidecar','protected_reference','protected_codec','protected_key_version','protected_expires_at','protected_recovery_metadata','protected_cleanup_policy','projection_metadata']::pg_catalog.text[],ARRAY['bytea','bytea[]','int4[]','int4','float8','uuid','int4','text','int4','uuid','bool','uuid','text','bytea','bytea','bytea','bytea','int4','int4','bytea','bytea','bytea','bytea','bytea','bytea','bytea','bytea','bytea','text','int4','timestamptz','timestamptz','text','bool','uuid','int8','timestamptz','timestamptz','int4','int4','uuid','bytea','timestamptz','timestamptz','text','uuid','timestamptz','bytea','uuid','uuid','bool','uuid','text','uuid','int8','int4','int4','uuid','text','timestamptz','bytea','bytea','text','bytea','bytea','xid8','timestamptz','uuid','bytea','bytea','bytea','bytea','bytea','text','bytea','bytea','bytea','bytea','timestamptz','bytea','text','bytea']::pg_catalog.text[],ARRAY['i','i','i','i','i','i','i','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t']::pg_catalog.text[],'v','5f7ee4f68b25fcc70e14244c5488bd6f6b9eb3c32e0932970ee79ab75652e9bb',ARRAY['modkit_runtime']::pg_catalog.text[]),
        ('modkit_workers.w05(bytea,bytea[],int4[],int4,float8,uuid,int4,int8)',8,ARRAY['p_namespace','p_command_types','p_schema_versions','p_limit','p_lease_seconds','p_scan_after','p_discovery_budget','p_max_page_payload_bytes','record_type','visited','next_cursor','pass_exhausted','work_id','kind','subscription_id','namespace','command_type','schema_version_decimal','runnable_version','canonical_version','scope_evidence','scope_application','scope_tenant','scope_owner','idempotency_key','intent_evidence','semantic_input','replay_input','protected_binding','replay_policy','max_attempts','deadline','original_available_at','state','cancellation_requested','token','ownership_revision','lease_until','available_at','cycle','attempt_count','dispatch_id','result','created_at','updated_at','success_origin','completion_guard_id','final_fence_at','completion_result_digest','resolution_operation_id','terminal_resolution_operation_id','resolution_present','resolution_record_operation_id','resolution_record_operation_kind','resolution_record_work_id','resolution_record_expected_revision','resolution_record_cycle','resolution_record_attempt','resolution_record_dispatch_id','resolution_record_outcome','resolution_record_retry_at','resolution_record_result','resolution_record_result_digest','resolution_record_reason','resolution_record_evidence','resolution_record_binding','resolution_record_resolution_root_xid','resolution_record_recorded_at','job_work_id','job_application','job_tenant','job_owner','job_protected_binding','job_semantic_input','material_state','protected_sidecar','protected_reference','protected_codec','protected_key_version','protected_expires_at','protected_recovery_metadata','protected_cleanup_policy','projection_metadata']::pg_catalog.text[],ARRAY['bytea','bytea[]','int4[]','int4','float8','uuid','int4','int8','text','int4','uuid','bool','uuid','text','bytea','bytea','bytea','bytea','int4','int4','bytea','bytea','bytea','bytea','bytea','bytea','bytea','bytea','bytea','text','int4','timestamptz','timestamptz','text','bool','uuid','int8','timestamptz','timestamptz','int4','int4','uuid','bytea','timestamptz','timestamptz','text','uuid','timestamptz','bytea','uuid','uuid','bool','uuid','text','uuid','int8','int4','int4','uuid','text','timestamptz','bytea','bytea','text','bytea','bytea','xid8','timestamptz','uuid','bytea','bytea','bytea','bytea','bytea','text','bytea','bytea','bytea','bytea','timestamptz','bytea','text','bytea']::pg_catalog.text[],ARRAY['i','i','i','i','i','i','i','i','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t','t']::pg_catalog.text[],'v','816e8850ff4d2b26bcbe016d230a60b86c80fd68fa0bb3526e1856f69f0253b8',ARRAY['modkit_runtime']::pg_catalog.text[])
    ) AS e(identity,input_count,names,types,modes,volatility,body_sha,roles) LOOP
        SELECT * INTO p FROM pg_catalog.pg_proc
          WHERE oid=pg_catalog.to_regprocedure(expected.identity);
        SELECT pg_catalog.array_agg(pg_catalog.to_regtype(t.name)::pg_catalog.oid ORDER BY t.pos)
          INTO wanted_types FROM pg_catalog.unnest(expected.types) WITH ORDINALITY AS t(name,pos);
        IF p.oid IS NULL OR p.pronamespace<>workers_oid OR p.proowner<>owner_oid
           OR p.prokind<>'f' OR p.prosecdef IS DISTINCT FROM TRUE
           OR p.proretset IS DISTINCT FROM TRUE OR p.prorettype<>pg_catalog.to_regtype('record')
           OR p.proisstrict OR p.proleakproof OR p.pronargdefaults<>0 OR p.provariadic<>0
           OR p.provolatile::pg_catalog.text<>expected.volatility
           OR p.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, pg_temp']::pg_catalog.text[]
           OR p.prolang IS DISTINCT FROM (SELECT oid FROM pg_catalog.pg_language WHERE lanname='plpgsql')
           OR p.pronargs<>expected.input_count OR p.proargnames IS DISTINCT FROM expected.names
           OR p.proallargtypes IS DISTINCT FROM wanted_types
           OR p.proargmodes::pg_catalog.text[] IS DISTINCT FROM expected.modes
           OR pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p.prosrc,'UTF8')),'hex')
                IS DISTINCT FROM expected.body_sha THEN
            RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='unexpected Workers function identity or ABI';
        END IF;
        known_functions:=pg_catalog.array_append(known_functions,p.oid);
        IF EXISTS (
            WITH wanted AS (
                SELECT acl.grantee,acl.grantor,acl.privilege_type,acl.is_grantable
                FROM pg_catalog.aclexplode(pg_catalog.acldefault('f',owner_oid)) AS acl
                WHERE acl.grantee=owner_oid
                UNION ALL
                SELECT r.oid,owner_oid,'EXECUTE'::pg_catalog.text,FALSE
                FROM pg_catalog.pg_roles AS r
                WHERE is_post AND r.rolname=ANY(expected.roles)
            ), actual AS (
                SELECT acl.grantee,acl.grantor,acl.privilege_type,acl.is_grantable
                FROM pg_catalog.aclexplode(COALESCE(p.proacl,pg_catalog.acldefault('f',owner_oid))) AS acl
            )
            (SELECT * FROM actual EXCEPT SELECT * FROM wanted)
            UNION ALL
            (SELECT * FROM wanted EXCEPT SELECT * FROM actual)
        ) THEN
            RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='unexpected Workers function ACL';
        END IF;
        FOR role_row IN SELECT oid,rolname FROM pg_catalog.pg_roles
          WHERE rolname IN ('modkit_runtime','modkit_reconciler','modkit_operator') LOOP
            IF pg_catalog.has_function_privilege(role_row.oid,p.oid,'EXECUTE')
                 IS DISTINCT FROM (is_post AND role_row.rolname=ANY(expected.roles)) THEN
                RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='unsafe effective Workers function access';
            END IF;
        END LOOP;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_catalog.pg_proc
               WHERE pronamespace=workers_oid AND NOT (oid=ANY(known_functions)))
       OR pg_catalog.cardinality(known_functions)<>7
       OR EXISTS (SELECT 1 FROM pg_catalog.pg_class WHERE relnamespace=workers_oid)
       OR EXISTS (SELECT 1 FROM pg_catalog.pg_type WHERE typnamespace=workers_oid) THEN
        RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='unexpected Workers object inventory';
    END IF;
    FOR object_row IN SELECT oid,nspowner,nspacl FROM pg_catalog.pg_namespace
      WHERE oid IN (workers_oid,events_oid) LOOP
        IF EXISTS (
            WITH wanted AS (
                SELECT acl.grantee,acl.grantor,acl.privilege_type,acl.is_grantable
                FROM pg_catalog.aclexplode(pg_catalog.acldefault('n',owner_oid)) AS acl
                UNION ALL
                SELECT r.oid,owner_oid,'USAGE'::pg_catalog.text,FALSE
                FROM pg_catalog.pg_roles AS r
                WHERE (is_post OR object_row.oid=events_oid)
                  AND r.rolname IN ('modkit_runtime','modkit_reconciler','modkit_operator')
            ), actual AS (
                SELECT acl.grantee,acl.grantor,acl.privilege_type,acl.is_grantable
                FROM pg_catalog.aclexplode(COALESCE(object_row.nspacl,
                  pg_catalog.acldefault('n',owner_oid))) AS acl
            )
            (SELECT * FROM actual EXCEPT SELECT * FROM wanted)
            UNION ALL
            (SELECT * FROM wanted EXCEPT SELECT * FROM actual)
        ) THEN
            RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='unexpected installation schema ACL';
        END IF;
        FOR role_row IN SELECT oid FROM pg_catalog.pg_roles
          WHERE rolname IN ('modkit_runtime','modkit_reconciler','modkit_operator') LOOP
            IF pg_catalog.has_schema_privilege(role_row.oid,object_row.oid,'USAGE')
                 IS DISTINCT FROM (is_post OR object_row.oid=events_oid)
               OR pg_catalog.has_schema_privilege(role_row.oid,object_row.oid,'CREATE') THEN
                RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='unsafe effective installation schema access';
            END IF;
        END LOOP;
    END LOOP;
    -- Events is an already qualified prerequisite, never repaired here.
    IF NOT EXISTS (SELECT 1 FROM modkit_events.schema_versions
                   WHERE component='events' AND version=1
                     AND pg_catalog.octet_length(migration_digest)=32
                     AND catalog_contract_id='modkit-pg-ab-2'
                     AND scope_format_id='MKSC-1' AND intent_format_id='MKPF-1'
                     AND applied_at IS NOT NULL) THEN
        RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='missing Events installation receipt';
    END IF;
    FOR object_row IN SELECT c.oid,c.relowner,c.relkind,c.relacl FROM pg_catalog.pg_class AS c
      WHERE c.relnamespace=events_oid AND c.relkind IN ('r','p','v','m','f','S') LOOP
        IF object_row.relowner<>owner_oid OR EXISTS (
            SELECT 1 FROM pg_catalog.aclexplode(COALESCE(object_row.relacl,
                pg_catalog.acldefault(CASE WHEN object_row.relkind='S' THEN 's'::pg_catalog."char"
                                          ELSE 'r'::pg_catalog."char" END,owner_oid))) AS acl
            WHERE acl.grantee<>owner_oid
        ) OR EXISTS (
            SELECT 1 FROM pg_catalog.pg_attribute AS a,
              LATERAL pg_catalog.aclexplode(a.attacl) AS acl
            WHERE a.attrelid=object_row.oid AND a.attnum>0 AND NOT a.attisdropped
              AND acl.grantee<>owner_oid
        ) THEN
            RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='unsafe Events direct relation or column ACL';
        END IF;
        FOR role_row IN SELECT oid FROM pg_catalog.pg_roles
          WHERE rolname IN ('modkit_runtime','modkit_reconciler','modkit_operator') LOOP
            IF (CASE WHEN object_row.relkind='S' THEN
                pg_catalog.has_sequence_privilege(role_row.oid,object_row.oid,'SELECT,USAGE,UPDATE')
               ELSE pg_catalog.has_table_privilege(role_row.oid,object_row.oid,
                       'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
                 OR EXISTS (SELECT 1 FROM pg_catalog.pg_attribute AS a
                    WHERE a.attrelid=object_row.oid AND a.attnum>0 AND NOT a.attisdropped
                      AND pg_catalog.has_column_privilege(role_row.oid,object_row.oid,a.attnum,
                          'SELECT,INSERT,UPDATE,REFERENCES')) END) THEN
                RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='unsafe effective Events data access';
            END IF;
        END LOOP;
    END LOOP;
    FOR object_row IN SELECT f.oid,f.proowner,f.proacl FROM pg_catalog.pg_proc AS f
      WHERE f.pronamespace=events_oid AND
        (pg_catalog.left(f.proname,1)='_' OR f.oid=pg_catalog.to_regprocedure(
         'modkit_events.e04(bytea,text,bytea[],int4[],int4,float8,uuid,int4,int8)')) LOOP
        IF object_row.proowner<>owner_oid OR EXISTS (
            SELECT 1 FROM pg_catalog.aclexplode(COALESCE(object_row.proacl,
              pg_catalog.acldefault('f',owner_oid))) AS acl WHERE acl.grantee<>owner_oid
        ) OR EXISTS (SELECT 1 FROM pg_catalog.pg_roles AS checked_role
            WHERE checked_role.rolname IN ('modkit_runtime','modkit_reconciler','modkit_operator')
              AND pg_catalog.has_function_privilege(checked_role.oid,object_row.oid,'EXECUTE')) THEN
            RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='unsafe Events private function access';
        END IF;
    END LOOP;
    -- Implicit row/array types retain PostgreSQL's ordinary NULL ACL behavior.
    -- The explicit private composite has its own existing PUBLIC revocation.
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_type AS t
                   WHERE t.oid=pg_catalog.to_regtype('modkit_events._parse_result')
                     AND t.typowner=owner_oid AND t.typacl IS NOT NULL)
       OR EXISTS (
          SELECT 1 FROM pg_catalog.pg_type AS t
          WHERE t.typnamespace=events_oid AND (
            t.typowner<>owner_oid
            OR NOT (
              (t.oid=pg_catalog.to_regtype('modkit_events._parse_result') AND t.typtype='c')
              OR (t.typtype='c' AND t.typacl IS NULL AND EXISTS (
                  SELECT 1 FROM pg_catalog.pg_class AS c
                  WHERE c.oid=t.typrelid AND c.reltype=t.oid
                    AND c.relnamespace=events_oid AND c.relowner=owner_oid
                    AND c.relkind IN ('r','p')))
              OR (t.typtype='b' AND t.typcategory='A' AND t.typacl IS NULL AND EXISTS (
                  SELECT 1 FROM pg_catalog.pg_type AS element
                  WHERE element.oid=t.typelem AND element.typarray=t.oid
                    AND element.typnamespace=events_oid AND element.typowner=owner_oid
                    AND element.typtype='c' AND
                    (element.oid=pg_catalog.to_regtype('modkit_events._parse_result')
                     OR EXISTS (SELECT 1 FROM pg_catalog.pg_class AS c
                         WHERE c.oid=element.typrelid AND c.reltype=element.oid
                           AND c.relnamespace=events_oid AND c.relowner=owner_oid
                           AND c.relkind IN ('r','p')))))
            )
            OR EXISTS (SELECT 1 FROM pg_catalog.aclexplode(t.typacl) AS acl
                       WHERE acl.grantee<>owner_oid OR acl.grantor<>owner_oid
                         OR acl.privilege_type<>'USAGE' OR acl.is_grantable)
          )
       ) THEN
        RAISE EXCEPTION USING ERRCODE='PZ011',MESSAGE='unsafe Events explicit type ACL';
    END IF;
END
$workers_grants_postflight$;
