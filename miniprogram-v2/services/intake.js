function createIntake(api,session){
 const base=(f,b)=>'/families/'+encodeURIComponent(f)+'/intake/batches'+(b?'/'+encodeURIComponent(b):'');
 const edit=(method='GET',data)=>({method,data,editScope:true});
 const unknown=()=>Object.assign(new Error('保存结果暂时无法核实。进度已保留，请继续查询原操作。'),{code:'RESULT_UNKNOWN'});
 return {
  list:f=>api.request(base(f),edit()),get:(f,b)=>api.request(base(f,b),edit()),
  create(f,child){const data={default_child_id:child};return api.request(base(f),{...edit('POST',data),idempotencyKey:session.mutationKey(f,'create-batch',data)}).then(r=>{session.completeMutation(f,'create-batch');return r;});},
  item:(f,b,data)=>api.request(base(f,b)+'/items',edit('POST',data)),
  retry:(f,b,id)=>api.request(base(f,b)+'/items/'+encodeURIComponent(id)+'/recognition',edit('POST',{})),
  discardItem:(f,b,id,version)=>api.request(base(f,b)+'/items/'+encodeURIComponent(id),edit('PUT',{expected_version:version,discarded:true})),
  candidate:(f,b,data,id)=>api.request(base(f,b)+'/candidates'+(id?'/'+encodeURIComponent(id):''),edit(id?'PUT':'POST',data)),
  async confirm(f,b,entries){
   const slot='intake-operation:'+b;let pending=session.read(f,slot);
   if(pending){const result=await api.request(base(f,b)+'/operations/'+encodeURIComponent(pending.operation_id),edit());if(result.status!=='completed')throw unknown();session.remove(f,slot);session.write(f,'intake-result:'+b,result);return result;}
   if(!entries.length)throw new Error('请先选择要入库的衣物');
   const operation_id=session.mutationKey(f,'confirm:'+b+':'+Date.now(),entries);pending={operation_id,entries};session.write(f,slot,pending);
   try{const result=await api.request(base(f,b)+'/confirm',edit('POST',pending));session.remove(f,slot);session.write(f,'intake-result:'+b,result);return result;}
   catch(e){if(['NETWORK','STALE'].includes(e.code) || e.status>=500)throw unknown();session.remove(f,slot);throw e;}
  },
  retryFailed(f,b,entries){const result=session.read(f,'intake-result:'+b);const failed=(result && result.results || []).filter(r=>r.status==='failed' && !['FORBIDDEN','VERSION_CONFLICT','OWNER_REVIEW_REQUIRED','RESTORE_REQUIRED'].includes(r.error && r.error.code)).map(r=>r.candidate_id);return this.confirm(f,b,entries.filter(e=>failed.includes(e.candidate_id)));}
  ,async query(f,b){const slot='intake-operation:'+b,pending=session.read(f,slot);if(!pending)return session.read(f,'intake-result:'+b) || {status:'not_pending',results:[],counts:{new:0,existing:0,failed:0}};const result=await api.request(base(f,b)+'/operations/'+encodeURIComponent(pending.operation_id),edit());if(result.status!=='completed')throw unknown();session.remove(f,slot);session.write(f,'intake-result:'+b,result);return result;}
  ,async resolve(f,b){const slot='intake-operation:'+b,pending=session.read(f,slot);if(!pending)throw new Error('没有待核实操作');const result=await api.request(base(f,b)+'/operations/'+encodeURIComponent(pending.operation_id)+'/resolve',edit('POST',pending));if(result.status!=='completed')throw unknown();session.remove(f,slot);session.write(f,'intake-result:'+b,result);return result;}
 };
}
module.exports={createIntake};
