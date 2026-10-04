const {captureOutfitAccess,assertOutfitEdit}=require('./c-page');
const {scopedSlot,locate,clearPending}=require('./outfit-pending');
const copy=value=>value===undefined?undefined:JSON.parse(JSON.stringify(value));
function unknown(){return Object.assign(new Error('保存结果尚待确认，请查询原操作。'),{code:'RESULT_UNKNOWN'});}
function transport(payload={},kind='save'){
 const common=['child_id','target_date','scene','preference_mode','designated_member_id','city','lat','lon'];
 const draft=['draft_id','target_plan_id','expected_version','recommendation_id','locked_ids','excluded_ids','sharing_grants','weather_acknowledged','backup_needs_review'];
 const extra={context:['date_mode'],recommend:['request_id','exclude_combination'],candidates:['replace_id','usage'],backup:['mode'],review:[],sharing:['garment_id','reason','periods'],save:['input_version','operation_id']};
 const keys=[...common,...(kind==='context'?[]:draft),...(extra[kind]||[])];
 const result={};for(const key of keys)if(payload[key]!==undefined)result[key]=copy(payload[key]);
 const entry=(item,backup=false)=>({garment_id:String(item.garment_id || item.id),expected_version:item.expected_version===undefined?item.version:item.expected_version,
  ...(backup && item.replaces_garment_id?{replaces_garment_id:String(item.replaces_garment_id)}:{})});
 if(kind!=='context' && payload.main_items)result.main_items=payload.main_items.map(i=>entry(i));
 if(kind!=='context' && payload.backup)result.backup={mode:payload.backup.mode,items:(payload.backup.items || []).map(i=>entry(i,true))};
 return result;
}
function createOutfits(api,session,context){
 const base=f=>'/families/'+encodeURIComponent(f)+'/outfits';
 const runtime={session,context};
 function guard(f,edit=false){return captureOutfitAccess(runtime,f,{edit});}
 function readable(f){return !!session.user() && ['admin','editor','viewer'].includes(session.capability(f).role);}
 function resultGuard(f){
  const current=guard(f);
  const assert=()=>{current.assert();if(!readable(f))throw Object.assign(new Error('已无家庭访问权，不能查看保存结果。'),{code:'FAMILY_ACCESS_REVOKED',status:403,familyId:f,contextEpoch:context.capture().epoch});};
  assert();return {assert};
 }
 function childFor(f,childId){
  if(childId!==undefined && childId!==null)return String(childId);
  const current=context.capture().current;
  return current && String(current.familyId)===String(f)?current.childId:session.read(f,'child');
 }
 function pending(f,date,childId){if(!readable(f))return null;const found=locate(session,f,'pending',date,childFor(f,childId));return found?found.record:null;}
 function finished(f,value,current,source){
  const original=source.record;
  if(!value || value.status!=='completed')throw unknown();
  current.assert();
  if(value.operation_id && value.operation_id!==original.operation_id)throw Object.assign(new Error('原操作回执身份不一致，请继续查询'),{code:'RESULT_UNKNOWN'});
  if(value.plan && value.plan.child_id!==undefined && String(value.plan.child_id)!==String(original.payload.child_id))throw unknown();
  const record={receipt:copy(value),payload:copy(original.payload)};
  if(value.plan){const receipts=copy(session.read(f,'outfit-receipts')||{});receipts[original.mutation_slot]=record;session.write(f,'outfit-receipts',receipts);}
  // Two queries for A can complete around a new submission B. Only A's own
  // pending record may be cleared; a late A reply cannot alter B's receipt.
  const live=session.read(f,source.slot);
  if(live && live.operation_id===original.operation_id){
   session.write(f,scopedSlot('result',original.payload.target_date,original.payload.child_id),record);clearPending(session,f,source);
  }
  return copy(value);
 }
 async function post(f,name,payload){
  const current=guard(f,true),result=await api.request(base(f)+'/'+name,{method:'POST',data:transport(payload,name),editScope:true});
  current.assert();return result;
 }
 async function queryOperation(f,date,childId){
  const current=resultGuard(f),child=childFor(f,childId),source=locate(session,f,'pending',date,child);
  if(!source){const result=locate(session,f,'result',date,child);current.assert();return copy(result && result.record.receipt)||{status:'not_pending'};}
  const original=source.record;
  let result;
  try{result=await api.request(base(f)+'/operations/'+encodeURIComponent(original.operation_id),{method:'GET'});}
  catch(e){current.assert();if(e.code==='FAMILY_ACCESS_REVOKED'||e.status===401)throw e;throw unknown();}
  current.assert();return finished(f,result,current,source);
 }
 return {
  async context(f,query={}){
   const current=guard(f),parameters=Object.entries(transport(query,'context')).filter(([,v])=>v!==undefined && v!==null && v!=='').map(([k,v])=>encodeURIComponent(k)+'='+encodeURIComponent(v)).join('&');
   const result=await api.request(base(f)+'/context'+(parameters?'?'+parameters:''));current.assert();return result;
  },
  recommend:(f,payload)=>post(f,'recommend',payload),
  candidates:(f,payload)=>post(f,'candidates',payload),
  backup:(f,payload)=>post(f,'backup',payload),
  review:(f,payload)=>post(f,'review',payload),
  sharing:(f,payload)=>post(f,'sharing',payload),
  pending,queryOperation,
  async save(f,payload){
   const current=guard(f,true),date=payload.target_date,child=payload.child_id,wire=transport(payload);
   if(!date)throw new Error('请先取得搭配的实际日期');
   if(child===undefined || child===null)throw new Error('请先指定当前宝贝');
   if(pending(f,date,child))return queryOperation(f,date,child);
   const mutation_slot='outfit-save:'+date+':'+(payload.action_id||payload.draft_id);
   const previous=(session.read(f,'outfit-receipts')||{})[mutation_slot];
   if(previous && previous.receipt.plan && previous.payload){
    const comparable=copy(previous.payload);delete comparable.operation_id;
    if(JSON.stringify(comparable)===JSON.stringify(wire))return copy(previous.receipt);
    throw Object.assign(new Error('这次操作已保存。请明确修改原方案或新增另一套后重新核对。'),{code:'ACTION_COMPLETED',status:409});
   }
   const frozen=wire;
   const operation_id=session.mutationKey(f,mutation_slot,frozen);frozen.operation_id=operation_id;
   const source={slot:scopedSlot('pending',date,child),record:{operation_id,mutation_slot,payload:frozen}};
   current.assert();session.write(f,source.slot,source.record);
   try{
    const result=await api.request(base(f)+'/plans',{method:'POST',data:copy(frozen),editScope:true,idempotencyKey:operation_id});
    current.assert();return finished(f,result,current,source);
   }catch(e){
    // A request may have committed before its response or access ticket was lost.
    if(e.code==='RESULT_UNKNOWN'||e.code==='NETWORK'||e.code==='STALE'||e.status>=500)throw unknown();
    if(e.code==='FAMILY_ACCESS_REVOKED'||e.code==='EDIT_ACCESS_REVOKED'||e.status===401)throw e;
    current.assert();clearPending(session,f,source);throw e;
   }
  },
  async resolveOperation(f,date,childId){
   assertOutfitEdit(session,f);const current=guard(f,true),source=locate(session,f,'pending',date,childFor(f,childId));
   if(!source)throw new Error('没有待核实的保存操作');
   const original=source.record;
   let result;
   try{result=await api.request(base(f)+'/operations/'+encodeURIComponent(original.operation_id)+'/resolve',{method:'POST',data:copy(original.payload),editScope:true});}
   catch(e){current.assert();if(e.code==='FAMILY_ACCESS_REVOKED'||e.code==='EDIT_ACCESS_REVOKED'||e.status===401)throw e;throw unknown();}
   current.assert();return finished(f,result,current,source);
  }
 };
}
module.exports={createOutfits,transport};
