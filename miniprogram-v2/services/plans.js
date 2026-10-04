const {captureOutfitAccess}=require('./c-page');
const copy=value=>value===undefined?undefined:JSON.parse(JSON.stringify(value));
function unknown(){return Object.assign(new Error('撤销结果尚待确认，请查询原操作。'),{code:'RESULT_UNKNOWN'});}
function createPlans(api,session,context){
 const base=f=>'/families/'+encodeURIComponent(f)+'/outfits',guard=(f,edit=false)=>captureOutfitAccess({session,context},f,{edit});
 const slot=p=>'outfit-cancel:'+String(p),readable=f=>session.user() && ['admin','editor','viewer'].includes(session.capability(f).role);
 function pendingCancel(f,p){return readable(f)?copy(session.read(f,slot(p))) || null:null;}
 async function request(f,url,options={},edit=false){const current=guard(f,edit);const result=await api.request(url,{...options,...(edit?{editScope:true}:{})});current.assert();return result;}
 function finish(f,p,record,result,current){
  current.assert();
  if(!result || result.status!=='completed' || result.operation_id!==record.payload.operation_id ||
   !(result.plan && String(result.plan.id)===String(p) && result.plan.status==='cancelled' || result.error && result.error.code==='NOT_EXECUTED'))throw unknown();
  const live=pendingCancel(f,p);if(live && live.payload.operation_id===record.payload.operation_id){session.write(f,slot(p)+':receipt',copy(result));session.remove(f,slot(p));if(result.error && result.error.code==='NOT_EXECUTED')session.completeMutation(f,'outfit-cancel:'+p+':'+record.payload.expected_version);}
  return copy(result);
 }
 async function recover(f,p,resolve=false){
  const current=guard(f,resolve),record=pendingCancel(f,p);if(!record)return {status:'not_pending'};
  try{const result=await api.request(resolve?base(f)+'/plans/'+encodeURIComponent(p)+'/cancel/resolve':base(f)+'/operations/'+encodeURIComponent(record.payload.operation_id),
   resolve?{method:'POST',data:copy(record.payload),editScope:true}:{method:'GET'});return finish(f,p,record,result,current);
  }catch(e){if(e.code==='FAMILY_ACCESS_REVOKED'||e.code==='EDIT_ACCESS_REVOKED'||e.status===401)throw e;current.assert();throw unknown();}
 }
 return {
  async calendar(f,query){
   const start=new Date(query.start_date+'T00:00:00Z'),end=new Date(query.end_date+'T00:00:00Z'),days=(end-start)/86400000+1;
   if(!/^\d{4}-\d{2}-\d{2}$/.test(query.start_date || '') || !/^\d{4}-\d{2}-\d{2}$/.test(query.end_date || '') || !Number.isInteger(days) || days<1 || days>62 || start.toISOString().slice(0,10)!==query.start_date || end.toISOString().slice(0,10)!==query.end_date)throw new Error('请选择不超过62天的有效日期范围');
   const keys=['start_date','end_date','child_id','include_cancelled'];const qs=keys.filter(k=>query[k]!==undefined && query[k]!==null && query[k]!=='').map(k=>encodeURIComponent(k)+'='+encodeURIComponent(query[k])).join('&');
   return request(f,base(f)+'/calendar?'+qs);
  },
  detail:(f,p)=>request(f,base(f)+'/plans/'+encodeURIComponent(p)),
  pendingCancel,queryCancel:(f,p)=>recover(f,p),resolveCancel:(f,p)=>recover(f,p,true),
  async cancel(f,p,version){
   const current=guard(f,true);if(pendingCancel(f,p))return recover(f,p);
   const payload={expected_version:version},operation_id=session.mutationKey(f,'outfit-cancel:'+p+':'+version,payload);payload.operation_id=operation_id;
   const record={plan_id:String(p),payload:copy(payload)};session.write(f,slot(p),record);
   try{const result=await api.request(base(f)+'/plans/'+encodeURIComponent(p)+'/cancel',{method:'POST',data:copy(payload),editScope:true,idempotencyKey:operation_id});return finish(f,p,record,result,current);}
   catch(e){if(e.code==='FAMILY_ACCESS_REVOKED'||e.code==='EDIT_ACCESS_REVOKED'||e.status===401)throw e;if(e.code==='NETWORK'||e.code==='STALE'||e.code==='RESULT_UNKNOWN'||e.status>=500)throw unknown();current.assert();const live=pendingCancel(f,p);if(live && live.payload.operation_id===operation_id)session.remove(f,slot(p));throw e;}
  },
  reuse(f,p,payload){const keys=['expected_source_version','child_id','target_date','scene','draft_id','preference_mode','designated_member_id'];const wire={};for(const key of keys)if(payload[key]!==undefined && payload[key]!==null)wire[key]=copy(payload[key]);return request(f,base(f)+'/plans/'+encodeURIComponent(p)+'/reuse',{method:'POST',data:wire},true);},
  feedback(f,c,payload){const wire={};for(const key of ['event_id','plan_id','plan_version','signal','reason','styles'])if(payload[key]!==undefined)wire[key]=copy(payload[key]);return request(f,'/families/'+encodeURIComponent(f)+'/children/'+encodeURIComponent(c)+'/feedback',{method:'POST',data:wire},true);},
  tag(f,c,target,style,payload){if(!['family','me'].includes(target))throw new Error('只能管理共同偏好或自己的偏好');return request(f,'/families/'+encodeURIComponent(f)+'/children/'+encodeURIComponent(c)+'/profiles/'+target+'/tags/'+encodeURIComponent(style),{method:'POST',data:{expected_version:payload.expected_version,action:payload.action}},true);}
 };
}
module.exports={createPlans};
