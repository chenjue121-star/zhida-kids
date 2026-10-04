function createWardrobe(api,session){
 const base=f=>'/families/'+encodeURIComponent(f);
 const json=(method,data)=>({method,data,editScope:true});
 const unknown=()=>Object.assign(new Error('保存结果尚待核实，请查询原操作。'),{code:'RESULT_UNKNOWN'});
 function finishAction(f,slot,result){
  session.remove(f,slot);session.completeMutation(f,slot);
  const item=(result.results||[])[0];
  if(item && item.status==='success')return item.garment;
  throw Object.assign(new Error(item && item.error && item.error.message || '操作已核实未执行，请重新核对后操作'),{code:item && item.error && item.error.code || 'NOT_EXECUTED'});
 }
 return {
  list(f,filters={}){const query=Object.entries(filters).filter(([,v])=>v!==null && v!==undefined && v!=='').map(([k,v])=>encodeURIComponent(k)+'='+encodeURIComponent(v)).join('&');return api.request(base(f)+'/garments'+(query?'?'+query:''));},
  get(f,id){return api.request(base(f)+'/garments/'+encodeURIComponent(id));},
  update(f,id,payload){return api.request(base(f)+'/garments/'+encodeURIComponent(id),json('PUT',payload));},
  owners(f,id,payload){return api.request(base(f)+'/garments/'+encodeURIComponent(id)+'/owners',json('PUT',payload));},
  transfer(f,id,payload){return api.request(base(f)+'/garments/'+encodeURIComponent(id)+'/transfer',json('POST',payload));},
  async action(f,id,action,payload){
   const slot='wardrobe-action:'+action+':'+id,pending=session.read(f,slot);
   if(pending){const result=await api.request(base(f)+'/wardrobe-operations/'+encodeURIComponent(pending.operation_id),json('GET'));if(result.status!=='completed')throw unknown();return finishAction(f,slot,result);}
   const operation_id=session.mutationKey(f,slot,payload),body={...payload,operation_id};session.write(f,slot,body);
   try{const result=await api.request(base(f)+'/garments/'+encodeURIComponent(id)+'/'+action,{...json('POST',body),idempotencyKey:operation_id});session.remove(f,slot);session.completeMutation(f,slot);session.write(f,slot+':result',{operation_id,status:'completed',results:[{id,status:'success',kind:'existing',garment:result,error:null}]});return result;}
   catch(e){if(['NETWORK','STALE'].includes(e.code) || e.status>=500)throw unknown();if(['OPERATION_NOT_EXECUTED','NOT_EXECUTED'].includes(e.code)){const result=await api.request(base(f)+'/wardrobe-operations/'+encodeURIComponent(operation_id),json('GET'));if(result.status==='completed')return finishAction(f,slot,result);throw unknown();}session.remove(f,slot);session.completeMutation(f,slot);throw e;}
  },
  async queryAction(f,id,action){const slot='wardrobe-action:'+action+':'+id,pending=session.read(f,slot);if(!pending)return session.read(f,slot+':result') || {status:'not_pending',results:[]};const result=await api.request(base(f)+'/wardrobe-operations/'+encodeURIComponent(pending.operation_id),json('GET'));if(result.status!=='completed')throw unknown();session.remove(f,slot);session.completeMutation(f,slot);session.write(f,slot+':result',result);return result;},
  async resolveAction(f,id,action){const slot='wardrobe-action:'+action+':'+id,pending=session.read(f,slot);if(!pending)throw new Error('没有待核实操作');const result=await api.request(base(f)+'/garments/'+encodeURIComponent(id)+'/'+action+'/resolve',json('POST',pending));if(result.status!=='completed')throw unknown();session.remove(f,slot);session.completeMutation(f,slot);return result;},
  async bulk(f,action,items,state){
   const slot='wardrobe-pending';let pending=session.read(f,slot);
   if(pending){const result=await api.request(base(f)+'/wardrobe-operations/'+encodeURIComponent(pending.operation_id));if(result.status!=='completed')throw Object.assign(new Error('提交结果尚待核实，请继续查询。'),{code:'RESULT_UNKNOWN'});session.remove(f,slot);session.write(f,'wardrobe-result',result);return result;}
   const payload={operation_id:session.mutationKey(f,'wardrobe-bulk:'+Date.now(),{action,items,state}),action,items,...(state?{state}:{})};
   session.write(f,slot,payload);
   try{const result=await api.request(base(f)+'/garments/bulk',json('POST',payload));session.remove(f,slot);session.write(f,'wardrobe-result',result);return result;}
   catch(e){if(['NETWORK','STALE'].includes(e.code) || e.status>=500)throw Object.assign(new Error('提交结果尚待核实，请查询原操作。'),{code:'RESULT_UNKNOWN'});session.remove(f,slot);throw e;}
  },
  async resolveBulk(f){const slot='wardrobe-pending',pending=session.read(f,slot);if(!pending)throw new Error('没有待核实操作');const result=await api.request(base(f)+'/wardrobe-operations/'+encodeURIComponent(pending.operation_id)+'/resolve',json('POST',pending));if(result.status!=='completed')throw unknown();session.remove(f,slot);session.write(f,'wardrobe-result',result);return result;}
  ,async queryBulk(f){const slot='wardrobe-pending',pending=session.read(f,slot);if(!pending)throw new Error('没有待核实操作');const result=await api.request(base(f)+'/wardrobe-operations/'+encodeURIComponent(pending.operation_id),json('GET'));if(result.status!=='completed')throw unknown();session.remove(f,slot);session.write(f,'wardrobe-result',result);return result;}
 };
}
module.exports={createWardrobe};
