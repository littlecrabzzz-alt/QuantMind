import fcntl, hashlib, json, mmap, os, sqlite3, sys, time
from datetime import datetime, timezone
from pathlib import Path
import pyarrow.parquet as pq

ROOT=Path('/data/tushare')
RELEASE='data-de494289775ece674a54bb560ac3ecad37187af6ed1ef69f8590b78ddbbb3fb0'
MANIFEST_SHA='de494289775ece674a54bb560ac3ecad37187af6ed1ef69f8590b78ddbbb3fb0'
CURRENT_SHA='d47619bf57d327539914694cfdeb0724f7474cbdec02d953357f2a7c9a2ea0bc'
CONFIG_SHA='8ea3f3c5331130058dc854ded3a53d2051c78bb352a2a14e209ff43373cfae8a'
TASK='4781e3570f46c97fd5afc0463a556eb1ee11f28845157d6d052a9f686f234f0b'
LOGICAL='65cb953e7ffa7350dbbfec0a3c896fbc9ec29863f3491623a7916fdc5e4a0f6d'
REPORT=ROOT/'validation/opt-daily-fixed-row-sample-20260912.json'
RECEIPT=ROOT/'validation/opt-daily-fixed-row-sample-20260912-receipt.json'
REPORT_SHA='f71c869d18cb9bcf41d8914bc7208b499cf12003a575f29f6505885d44eae024'
RECEIPT_SHA='c222f9d8a92ac4fb5cc08a3c9d891ba7f12605790990af5d26fb845d8ac1e0bd'
CANDIDATE_SHA='e1712d95174459913646f6a8f5b24241d88842a75e02ed865b5f8fa21be7560d'
RUNNER_SHA='abffa078fbd6c8ea25519c0a0e6c62cad98edb5cba2c5a4f40e1e6b39a1e9f7a'
FIELDS='amount,close,exchange,high,low,oi,open,pre_close,pre_settle,settle,trade_date,ts_code,vol'
FIELD_LIST=FIELDS.split(',')
PARAMS={'trade_date':'20260911','ts_code':'HO2609-C-2500.CFX'}
RAW_ROW=[66.354,360.6,'CFFEX',360.6,348.6,170.0,351.6,398.0,399.4,366.8,'20260911','HO2609-C-2500.CFX',18.0]
CURRENT_REFS={
 'objects/84af83808067f506a2aa666d0f94ee91da36d9d644b618cf4540cbc539cb41c6.json': {'bytes':360,'sha256':'84af83808067f506a2aa666d0f94ee91da36d9d644b618cf4540cbc539cb41c6'},
 'observations/85945389cede483995bb324c63b2b16c.json': {'bytes':872,'sha256':'2259c4e822f13d5933a6c718b0e406777d36917f0540ea5572d89baebea6287d'},
 'parquet/3d4732fb8cf3682cd8467e34e21433ceebaea8d27abe60cdaa0904154c720baf.parquet': {'bytes':6306,'sha256':'3d4732fb8cf3682cd8467e34e21433ceebaea8d27abe60cdaa0904154c720baf'},
}
SOURCE_REFS={
 'parquet/278eab7f81922ebf4b52ad7900d1bd21731bad79ac49edd93eab56c48c4810c8.parquet': {'bytes':657700,'sha256':'278eab7f81922ebf4b52ad7900d1bd21731bad79ac49edd93eab56c48c4810c8'},
 'observations/94c825c8d73f4115b4810dcdf8ec27d9.json': {'bytes':952,'sha256':'837e95fb2db494af9486349f57081de227257a8b4cba88d087e57ea5d73c2730'},
 'parquet/2b1e19ef0d654fc902245b2e8ef6a60d4f611e3f6a9fa8ed35943725750f2f8d.parquet': {'bytes':883157,'sha256':'2b1e19ef0d654fc902245b2e8ef6a60d4f611e3f6a9fa8ed35943725750f2f8d'},
 'observations/a346370c87b24f39b29313db9759b8ff.json': {'bytes':852,'sha256':'eb1bec9781d92161dad87c02443ae182041cdd8dfe9bdd1bb450aa1492c4724e'},
}
SOURCE_OBJECTS={
 'objects/0529579a5e0224ade554eaaaf49f495eadc205de27191aac765a67ff416912da.json':'0529579a5e0224ade554eaaaf49f495eadc205de27191aac765a67ff416912da',
 'objects/568f10201535d3d57e6f3d0b70fce12b0bc7be9d55c7669d4281e5e8b8ec6916.json':'568f10201535d3d57e6f3d0b70fce12b0bc7be9d55c7669d4281e5e8b8ec6916',
}

def sha_bytes(b): return hashlib.sha256(b).hexdigest()
def sha_file(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for chunk in iter(lambda:f.read(8*1024*1024),b''): h.update(chunk)
 return h.hexdigest()
def jbytes(x): return json.dumps(x,ensure_ascii=False,sort_keys=True).encode()
def checked_file(rel, meta):
 p=ROOT/rel; st=p.stat(); got=sha_file(p)
 assert st.st_size==meta['bytes'], (rel,st.st_size,meta['bytes'])
 assert got==meta['sha256'], (rel,got,meta['sha256'])
 return {'path':rel,'bytes':st.st_size,'sha256':got}
def readj(p): return json.loads(p.read_bytes())

# Immutable pins before any state inspection.
current_before=(ROOT/'CURRENT.json').read_bytes()
assert sha_bytes(current_before)==CURRENT_SHA
assert json.loads(current_before)=={'manifest_sha256':MANIFEST_SHA,'release_id':RELEASE}
assert sha_file(ROOT/'pipeline-config.json')==CONFIG_SHA
assert sha_file(REPORT)==REPORT_SHA
assert sha_file(RECEIPT)==RECEIPT_SHA
report=readj(REPORT); receipt=readj(RECEIPT)
assert report['candidate_sha256']==CANDIDATE_SHA and report['runner_sha256']==RUNNER_SHA
assert report['current']['release_id']==RELEASE and report['current']['manifest_sha256']==MANIFEST_SHA
assert report['actual_upstream_calls']==1 and report['decision']['action']=='use_existing_pristine'
assert report['history_complete'] is False and report['historical_versions_complete'] is False
assert report['pit_verified'] is False and report['option_universe_complete'] is False
assert receipt['report_sha256']==REPORT_SHA

# Short, exact-PK read-only snapshot under a nonblocking shared pipeline lock.
lock_started=time.monotonic(); lock_path=ROOT/'pipeline.lock'
lockf=lock_path.open('rb')
try:
 fcntl.flock(lockf,fcntl.LOCK_SH|fcntl.LOCK_NB)
 deadline=time.monotonic()+2.0
 uri=f"file:{ROOT/'pipeline.sqlite'}?mode=ro"
 db=sqlite3.connect(uri,uri=True,timeout=0)
 db.row_factory=sqlite3.Row
 try:
  db.execute('PRAGMA query_only=ON'); db.execute('PRAGMA busy_timeout=0')
  db.set_progress_handler(lambda: 1 if time.monotonic()>deadline else 0,1000)
  row=db.execute('SELECT id,logical_key,epoch,job,priority,state,tries,retry_after,result,expanded,group_name FROM jobs WHERE id=?',(TASK,)).fetchone()
  attempts=db.execute('SELECT rowid,job_id,attempt,result FROM attempts WHERE job_id=? ORDER BY attempt',(TASK,)).fetchall()
 finally:
  db.close()
 finally_elapsed=time.monotonic()-lock_started
finally:
 fcntl.flock(lockf,fcntl.LOCK_UN); lockf.close()
assert row is not None and len(attempts)==1
job=json.loads(row['job']); result=json.loads(row['result'])
assert row['id']==TASK and row['logical_key']==LOGICAL and row['epoch']=='20260912'
assert row['priority']==21 and row['state']=='done' and row['tries']==1 and row['group_name']=='other'
assert attempts[0]['job_id']==TASK and attempts[0]['attempt']==1 and json.loads(attempts[0]['result'])==result
assert result==report['result']
expected_job={'api_name':'opt_daily','params':PARAMS,'fields':FIELDS,'row_cap':15000,'required_fields':['ts_code','trade_date'],'nullable_fields':['exchange','pre_settle','pre_close','open','high','low','close','settle','vol','amount','oi'],'positive_fields':[]}
assert job==expected_job, job
assert sha_bytes(jbytes(job))==LOGICAL
assert sha_bytes(jbytes([LOGICAL,'20260912']))==TASK
assert result['http_status']==200 and result['response_complete'] is True
assert result['status']=='sample_ok' and result['row_count']==1 and result['supplier_has_more'] is False
assert result['history_complete'] is False and result['pit_verified'] is False

# Current exact result chain and physical evidence.
verified_current=[checked_file(k,v) for k,v in sorted(CURRENT_REFS.items())]
raw=readj(ROOT/'objects'/f"{result['object_sha256']}.json")
obs=readj(ROOT/'observations'/result['observation'])
assert raw['code']==0 and raw['msg']=='' and raw['data']['has_more'] is False and raw['data']['count']==0
assert raw['data']['fields']==FIELD_LIST and raw['data']['items']==[RAW_ROW]
assert obs['request']=={'api_name':'opt_daily','fields':FIELDS,'params':PARAMS}
assert obs['object_sha256']==result['object_sha256']
assessment_expected={k:v for k,v in result.items() if k not in {'api_name','object_sha256','observation','observation_sha256','parquet'}}
assert obs['assessment']==assessment_expected,(obs['assessment'],assessment_expected)
assert sha_bytes((ROOT/'objects'/f"{obs['object_sha256']}.json").read_bytes())==obs['object_sha256']
par=result['parquet']; pp=ROOT/par['path']
assert pp.stem==par['sha256']
table=pq.read_table(pp); assert table.num_rows==1
rec=table.to_pylist()[0]
for name,value in zip(FIELD_LIST,RAW_ROW,strict=True):
 expected=('OPT:'+value) if name=='ts_code' else value
 assert rec[name]==expected,(name,rec[name],expected)
assert rec['source_ts_code']==PARAMS['ts_code'] and rec['_api_name']=='opt_daily'
assert rec['_observation']==result['observation']

# Fixed candidate source evidence: physical bytes/SHA, observation-object chain.
source_obs_expected={
 'observations/94c825c8d73f4115b4810dcdf8ec27d9.json':'0529579a5e0224ade554eaaaf49f495eadc205de27191aac765a67ff416912da',
 'observations/a346370c87b24f39b29313db9759b8ff.json':'568f10201535d3d57e6f3d0b70fce12b0bc7be9d55c7669d4281e5e8b8ec6916',
}
verified_source=[checked_file(k,v) for k,v in sorted(SOURCE_REFS.items())]
for rel,sha in SOURCE_OBJECTS.items():
 p=ROOT/rel; meta={'bytes':p.stat().st_size,'sha256':sha}; verified_source.append(checked_file(rel,meta))
for rel,objsha in source_obs_expected.items():
 so=readj(ROOT/rel); assert so['object_sha256']==objsha
 assert sha_bytes((ROOT/'objects'/f'{objsha}.json').read_bytes())==objsha

# Verify immutable manifest identity and exact active-files membership without materializing 435 MB JSON.
manifest=ROOT/'releases'/RELEASE/'manifest.json'
assert sha_file(manifest)==MANIFEST_SHA
all_source={**SOURCE_REFS}
for rel,sha in SOURCE_OBJECTS.items(): all_source[rel]={'bytes':(ROOT/rel).stat().st_size,'sha256':sha}
manifest_membership={}; current_absence={}
with manifest.open('rb') as mf:
 mm=mmap.mmap(mf.fileno(),0,access=mmap.ACCESS_READ)
 try:
  marker=b', "files": {'; start=mm.find(marker); assert start>=0 and mm.find(marker,start+1)<0
  start+=len(marker); end=mm.find(b'}, "gaps":',start); assert end>start
  for rel,meta in sorted(all_source.items()):
   frag=(json.dumps(rel)+': '+json.dumps(meta,sort_keys=True)).encode()
   ok=mm.find(frag,start,end)>=0; assert ok,(rel,frag)
   manifest_membership[rel]=ok
  for rel,meta in sorted(CURRENT_REFS.items()):
   frag=(json.dumps(rel)+': '+json.dumps(meta,sort_keys=True)).encode()
   absent=mm.find(frag,start,end)<0; assert absent,rel
   current_absence[rel]=absent
 finally: mm.close()

current_after=(ROOT/'CURRENT.json').read_bytes()
assert current_after==current_before and sha_file(ROOT/'pipeline-config.json')==CONFIG_SHA

# Create-only independent evidence. These 3 refs were captured after de494 and await NEXT normal publication.
now=datetime.now(timezone.utc); stamp=now.strftime('%Y%m%dT%H%M%S%fZ')
outdir=ROOT/'validation'/f'opt-daily-fixed-row-sample-independent-{stamp}'
outdir.mkdir(mode=0o755,parents=False,exist_ok=False)
inventory={
 'schema_version':1,'status':'pending_next_normal_publication','generated_at':now.isoformat(),
 'captured_after_release_id':RELEASE,'captured_after_manifest_sha256':MANIFEST_SHA,
 'required_release_relation':'strictly_after_captured_release','ref_count':len(CURRENT_REFS),
 'physical_bytes':sum(x['bytes'] for x in CURRENT_REFS.values()),
 'refs':[{'path':k,**v} for k,v in sorted(CURRENT_REFS.items())],
 'source_execution_report':{'path':str(REPORT.relative_to(ROOT)),'bytes':REPORT.stat().st_size,'sha256':REPORT_SHA},
 'source_execution_receipt':{'path':str(RECEIPT.relative_to(ROOT)),'bytes':RECEIPT.stat().st_size,'sha256':RECEIPT_SHA},
 'history_complete':False,'pit_verified':False,'publication_triggered':False,
}
def create_json(path,obj):
 data=json.dumps(obj,ensure_ascii=False,sort_keys=True,indent=2).encode()+b'\n'
 with path.open('xb') as f: f.write(data); f.flush(); os.fsync(f.fileno())
 return {'path':str(path.relative_to(ROOT)),'bytes':len(data),'sha256':sha_bytes(data)}
inv_file=create_json(outdir/'exact-refs-pending-next-release.json',inventory)
closure={
 'schema_version':1,'status':'independent_strict_closure_passed','generated_at':now.isoformat(),
 'review_timing':'post_execution','review_arrived_before_execution':False,
 'authority_snapshot':{'current':json.loads(current_before),'current_pointer_sha256':CURRENT_SHA,'config_sha256':CONFIG_SHA,'manifest_bytes':manifest.stat().st_size,'manifest_sha256':MANIFEST_SHA},
 'execution_artifacts':{'report':{'path':str(REPORT.relative_to(ROOT)),'bytes':REPORT.stat().st_size,'sha256':REPORT_SHA},'receipt':{'path':str(RECEIPT.relative_to(ROOT)),'bytes':RECEIPT.stat().st_size,'sha256':RECEIPT_SHA}},
 'exact_pk_snapshot':{'task_id':TASK,'logical_key':LOGICAL,'epoch':row['epoch'],'priority':row['priority'],'group_name':row['group_name'],'state':row['state'],'tries':row['tries'],'attempt_count':len(attempts),'attempts':[{'rowid':x['rowid'],'attempt':x['attempt']} for x in attempts],'shared_lock_elapsed_seconds':round(finally_elapsed,6),'sqlite_mode':'mode=ro/query_only','query_scope':'exact task primary key only','connection_closed':True},
 'result_contract':{'http_status':200,'response_complete':True,'status':'sample_ok','row_count':1,'supplier_has_more':False,'request':obs['request'],'raw_fields':FIELD_LIST,'raw_row':RAW_ROW,'observation_assessment_equals_result_without_storage_keys':True,'observation_object_chain':True,'parquet_row_exact':True,'parquet_path_hash_equals_filename':True,'parquet_all_13_source_fields_exact':True},
 'physical_current_refs':verified_current,'physical_current_bytes':sum(x['bytes'] for x in verified_current),
 'fixed_candidate_source_evidence':{'physical_refs':sorted(verified_source,key=lambda x:x['path']),'all_in_de494_manifest':all(manifest_membership.values()),'manifest_membership':manifest_membership,'observation_object_chains':True},
 'publication_boundary':{'new_ref_count':len(CURRENT_REFS),'new_ref_bytes':sum(x['bytes'] for x in CURRENT_REFS.values()),'all_absent_from_de494_active_files':all(current_absence.values()),'absence_by_path':current_absence,'pending_inventory':inv_file,'publication_triggered':False},
 'reuse_claim':{'selected_task_was_existing_pristine_according_to_execution_report':True,'selected_task_now_has_exactly_one_attempt':True,'actual_upstream_calls':1,'reuse_without_http':False,'claim_no_equivalent_tasks_or_attempts_in_other_epochs':False,'reason':'Independent closure intentionally queried only the selected exact PK; runner duplicate gate did not prove all-epoch absence.'},
 'runner_review':{'runner_sha256':RUNNER_SHA,'review_timing':'post_execution','reusable':False,'classification':'not_reusable','blockers':['Duplicate gate did not cover equivalent pre-watermark attempts or arbitrary epochs.','Source pins omitted de494 manifest hash, fixed source-artifact verification, and tushare_intake.py.','Pre-execution result validator did not prove full observation-object-assessment-result and Parquet chain.','No hard deadline; enqueue preceded token retrieval; report and receipt could diverge by directory.']},
 'scope_limits':{'history_complete':False,'historical_versions_complete':False,'pit_verified':False,'option_universe_complete':False,'all_epoch_duplicate_absence_proven':False},
 'non_actions':{'upstream_called':False,'credentials_read':False,'services_changed':False,'configuration_changed':False,'database_mutated':False,'publication_triggered':False},
 'errors':[],
}
closure_file=create_json(outdir/'independent-closure.json',closure)
os.sync()
print(json.dumps({'status':'PASS','output_dir':str(outdir),'inventory':inv_file,'closure':closure_file,'new_ref_count':3,'new_ref_bytes':7538,'source_ref_count':6,'task_attempt_rowid':attempts[0]['rowid'],'shared_lock_elapsed_seconds':round(finally_elapsed,6)},sort_keys=True))
