const copy=value=>value===undefined?undefined:JSON.parse(JSON.stringify(value));
function scopedSlot(kind,date,childId){return 'outfit-'+kind+':'+JSON.stringify([String(childId),date]);}
function matches(record,date,childId,kind='pending'){
 const payload=record && (record.payload || (kind==='result' && (record.receipt || record.response) && (record.receipt || record.response).plan));
 return !!(payload && payload.child_id!==undefined && payload.child_id!==null && childId!==undefined && childId!==null && String(payload.child_id)===String(childId) && payload.target_date===date);
}
function locate(session,family,kind,date,childId){
 if(childId===undefined || childId===null)return null;
 // Date-only records remain in place. Their frozen payload identifies the child;
 // another child's new operation must never overwrite or inherit them.
 for(const slot of [scopedSlot(kind,date,childId),'outfit-'+kind+':'+date]){
  const record=session.read(family,slot);
  if(matches(record,date,childId,kind)){
   const normalized=copy(record);
   if(kind==='result' && !normalized.receipt && normalized.response)normalized.receipt=copy(normalized.response);
   return {slot,record:normalized};
  }
 }
 return null;
}
function clearPending(session,family,original){
 const live=session.read(family,original.slot),record=original.record;
 if(!live || live.operation_id!==record.operation_id || !matches(live,record.payload.target_date,record.payload.child_id))return false;
 session.remove(family,original.slot);session.completeMutation(family,record.mutation_slot);return true;
}
module.exports={scopedSlot,locate,clearPending};
