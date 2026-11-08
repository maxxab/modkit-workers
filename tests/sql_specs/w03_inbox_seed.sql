-- W03 lawful inbox collision setup through the real E01/E03 producers.
-- Caller owns the disposable root; no owner Work/subtype/history INSERT.
DO $seed$
DECLARE
    sub pg_catalog.bytea:='listing-sub'::pg_catalog.bytea;
    scope_bytes pg_catalog.bytea:=pg_catalog.decode('4d4b5343010001610000','hex');
    obj pg_catalog.bytea:=pg_catalog.decode('6f00000000','hex');
    binding pg_catalog.bytea; replay pg_catalog.bytea; semantic pg_catalog.bytea; intent pg_catalog.bytea;
    event_value pg_catalog.bytea:='listing-event'::pg_catalog.bytea;
    key_value pg_catalog.bytea:='listing-key'::pg_catalog.bytea;
    t pg_catalog.timestamptz:='2026-01-02 03:04:05+00'; receipt pg_catalog.record;
BEGIN
    SELECT * INTO STRICT receipt FROM modkit_events.e01(sub,''::pg_catalog.bytea,'listing-group'::pg_catalog.bytea,4);
    IF receipt.ok IS DISTINCT FROM TRUE THEN RAISE EXCEPTION 'listing E01 setup differs'; END IF;
    binding:=modkit_events._make_record('protected-binding'::pg_catalog.bytea,ARRAY[
        'absent'::pg_catalog.bytea,'0'::pg_catalog.bytea,'0'::pg_catalog.bytea,'0'::pg_catalog.bytea,
        'retain'::pg_catalog.bytea,'0'::pg_catalog.bytea,'0'::pg_catalog.bytea,''::pg_catalog.bytea,''::pg_catalog.bytea,obj]::pg_catalog.bytea[]);
    replay:=pg_catalog.convert_to('{"event_id":"listing-event","name":"cmd","schema_version":1,"payload":{},"metadata":{}}','UTF8');
    semantic:=modkit_events._event_replay_frame(replay);
    intent:=modkit_events._make_record('work-intent'::pg_catalog.bytea,ARRAY[
        'inbox'::pg_catalog.bytea,modkit_events._optional_bytes(sub),'jobs'::pg_catalog.bytea,'cmd'::pg_catalog.bytea,
        '1'::pg_catalog.bytea,'1'::pg_catalog.bytea,scope_bytes,modkit_events._optional_bytes(key_value),semantic,binding,
        'application_safe'::pg_catalog.bytea,'3'::pg_catalog.bytea,'0'::pg_catalog.bytea,modkit_events._instant_bytes(t)]::pg_catalog.bytea[]);
    SELECT * INTO STRICT receipt FROM modkit_events.e03('15000000-0000-0000-0000-000000000001'::pg_catalog.uuid,
        'inbox'::pg_catalog.text,sub,'jobs'::pg_catalog.bytea,'cmd'::pg_catalog.bytea,scope_bytes,key_value,1,
        '1'::pg_catalog.bytea,'a'::pg_catalog.bytea,NULL::pg_catalog.bytea,NULL::pg_catalog.bytea,
        intent,semantic,replay,binding,'application_safe'::pg_catalog.text,3,NULL::pg_catalog.timestamptz,t,
        event_value,1,semantic,replay,TRUE,''::pg_catalog.bytea,''::pg_catalog.bytea);
    IF receipt.inserted IS DISTINCT FROM TRUE
       OR receipt.work_id IS DISTINCT FROM '15000000-0000-0000-0000-000000000001'::pg_catalog.uuid THEN
        RAISE EXCEPTION 'listing lawful E03 setup differs'; END IF;
END
$seed$;
