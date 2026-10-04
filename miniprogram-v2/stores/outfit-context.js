const {assertOutfitEdit,captureOutfitAccess}=require('../services/c-page');
const {locate}=require('../services/outfit-pending');
const copy=value=>value===undefined?undefined:JSON.parse(JSON.stringify(value));
let identitySequence=0;
function newDraftId(){identitySequence+=1;return Date.now().toString(36)+'-'+identitySequence.toString(36)+'-'+Math.random().toString(36).slice(2);}
function itemId(item){return String(item.garment_id || item.id);}
function normalizeBasis(basis={}){
 if(typeof basis==='string')basis=basis==='family'?{preference_mode:'family',preference_subject:'family'}:{preference_mode:'designated_member',designated_member_id:basis.replace(/^member:/,''),preference_subject:basis};
 const subject=basis.preference_subject;
 const mode=basis.preference_mode || basis.mode || subject && subject.mode || 'family';
 const member=mode==='designated_member'?(basis.designated_member_id || subject && subject.membership_id || null):null;
 return {preference_mode:mode,designated_member_id:member,preference_subject:basis.preference_subject || (member?'member:'+member:mode==='family'?'family':'current_member')};
}
function basisKey(basis){const b=normalizeBasis(basis),subject=b.preference_subject;return JSON.stringify([b.preference_mode,b.designated_member_id,subject && typeof subject==='object'?subject.owner_key:subject]);}
function createDraft(childId,date,basis={},scene='daily'){
 return {draft_id:newDraftId(),action_id:newDraftId(),child_id:childId,target_date:date,scene,...normalizeBasis(basis),
  main_items:[],backup:{mode:'none',items:[]},locked_ids:[],excluded_ids:[],sharing_grants:[],target_plan_id:null,expected_version:null,
  recommendation_id:null,input_version:null,weather_acknowledged:false,backup_needs_review:false,revision:0,dirty:false,
  replacement_staging:null,backup_staging:null,source_origin:null};
}
function patchDraft(draft,fields){
 if(draft.status==='completed')throw Object.assign(new Error('这次选定已完成，请明确修改原方案或再添加一套。'),{code:'ACTION_COMPLETED'});
 const next={...copy(draft),...copy(fields),revision:draft.revision+1,dirty:true,replacement_staging:null,backup_staging:null};
 const changed=key=>Object.prototype.hasOwnProperty.call(fields,key) && JSON.stringify(fields[key])!==JSON.stringify(draft[key]);
 if(['main_items','backup','scene','locked_ids','excluded_ids','weather','input_version','preference_subject','target_plan_id'].some(changed)){
  next.sharing_grants=Object.prototype.hasOwnProperty.call(fields,'sharing_grants')?copy(fields.sharing_grants):[];
  next.weather_acknowledged=Object.prototype.hasOwnProperty.call(fields,'weather_acknowledged')?!!fields.weather_acknowledged:false;
 }
 if(changed('main_items') && next.backup.items.length && !Object.prototype.hasOwnProperty.call(fields,'backup'))next.backup_needs_review=true;
 return next;
}
function manualMainChange(draft,fields){
 // Explicit parent edits discard confirmed/staged backup under C21. Provider
 // refreshes use patchDraft directly and must preserve their existing backup.
 if(JSON.stringify(fields.main_items)!==JSON.stringify(draft.main_items)){
  const hadBackup=draft.backup.mode!=='none' || draft.backup_staging && draft.backup_staging.mode!=='none';
  fields={...fields,backup:{mode:'none',items:[]},backup_needs_review:!!(draft.backup_needs_review || hadBackup)};
 }
 return patchDraft(draft,fields);
}
function setFixed(draft,id,enabled){
 id=String(id);if(enabled && !draft.main_items.some(i=>itemId(i)===id))throw new Error('请先核对要固定的单品');
 const locked=new Set(draft.locked_ids);if(enabled)locked.add(id);else locked.delete(id);
 return patchDraft(draft,{locked_ids:[...locked]});
}
function setExcluded(draft,id,enabled){
 id=String(id);if(enabled && draft.locked_ids.includes(id))throw new Error('请先明确解除固定');
 const excluded=new Set(draft.excluded_ids);if(enabled)excluded.add(id);else excluded.delete(id);
 const fields={excluded_ids:[...excluded],...(enabled?{main_items:draft.main_items.filter(i=>itemId(i)!==id)}:{})};
 return enabled?manualMainChange(draft,fields):patchDraft(draft,fields);
}
function draftPayload(draft){
 const entry=item=>({garment_id:itemId(item),expected_version:item.expected_version===undefined?item.version:item.expected_version,
  ...(item.replaces_garment_id?{replaces_garment_id:String(item.replaces_garment_id)}:{})});
 return copy({child_id:draft.child_id,target_date:draft.target_date,scene:draft.scene,preference_mode:draft.preference_mode,designated_member_id:draft.designated_member_id,
  draft_id:draft.draft_id,action_id:draft.action_id,main_items:draft.main_items.map(entry),backup:{mode:draft.backup.mode,items:draft.backup.items.map(entry)},
  locked_ids:draft.locked_ids,excluded_ids:draft.excluded_ids,target_plan_id:draft.target_plan_id,expected_version:draft.expected_version,
  recommendation_id:draft.recommendation_id,input_version:draft.input_version,sharing_grants:draft.sharing_grants,weather_acknowledged:draft.weather_acknowledged,backup_needs_review:!!draft.backup_needs_review,
  ...(draft.city?{city:draft.city}:{}),...(draft.lat!==undefined?{lat:draft.lat,lon:draft.lon}:{})});
}
function createOutfitStore(session,context){
 let active=null,navigation=0,request=0;
 const slot='outfit-drafts',completedSlot='outfit-completed-drafts';
 function authorized(){return active && session.user() && active.owner===session.user().id && active.generation===session.generation() && session.canEdit(active.family);}
 function read(){
  if(!authorized())return null;
  const drafts=session.read(active.family,slot)||{},draft=copy(drafts[active.key])||null;
  if(!draft || draft.status==='completed')return draft;
  const completed=(session.read(active.family,completedSlot)||{})[draft.draft_id];
  return completed?{...draft,dirty:false,status:'completed',...copy(completed)}:draft;
 }
 function requireDraft(mutable=true){
  if(!active)throw new Error('请先打开当前孩子与日期');assertOutfitEdit(session,active.family);const draft=read();if(!draft)throw new Error('当前草稿已失效，请重新打开');
  if(mutable && draft.status==='completed')throw Object.assign(new Error('这次选定已完成，请明确修改原方案或再添加一套。'),{code:'ACTION_COMPLETED'});
  const source=locate(session,active.family,'pending',draft.target_date,draft.child_id),pending=source && source.record;
  if(mutable && pending && pending.payload && pending.payload.draft_id===draft.draft_id)throw Object.assign(new Error('原提交结果尚待确认，提交内容已冻结，请查询原操作。'),{code:'RESULT_UNKNOWN'});
  return draft;
 }
 function write(draft){
  if(!active || !authorized())throw Object.assign(new Error('当前草稿已失效，请重新打开'),{code:'EDIT_ACCESS_REVOKED'});
  const current=captureOutfitAccess({session,context},active.family,{edit:true,navigation:false});
  const drafts=copy(session.read(active.family,slot)||{});drafts[active.key]=copy(draft);current.assert();session.write(active.family,slot,drafts);
  if(draft.scene)session.write(active.family,'outfit-scene:'+draft.child_id,draft.scene);return copy(draft);
 }
 function patch(fields){return write(patchDraft(requireDraft(),fields));}
 function invalidate(){navigation+=1;request+=1;}
 return {
  open(f,c,date,basis={}){
   invalidate();if(!/^\d{4}-\d{2}-\d{2}$/.test(date))throw new Error('需要服务端返回的实际日期');
   active={family:f,child:c,date,basis:normalizeBasis(basis),key:JSON.stringify([String(c),date,basisKey(basis)]),owner:session.user() && session.user().id,generation:session.generation()};
   if(!authorized())return null;
   const drafts=copy(session.read(f,slot)||{});
   if(!drafts[active.key]){drafts[active.key]=createDraft(c,date,basis,basis.scene || session.read(f,'outfit-scene:'+c)||'daily');session.write(f,slot,drafts);}
   return read();
  },
  get:read,patch,invalidate,
  completeSelection(plan,draftId,familyId){
   const family=familyId || active && active.family || session.read('_','family');
   if(!family || !draftId || !session.user() || !['admin','editor','viewer'].includes(session.capability(family).role))return 0;
   const current=captureOutfitAccess({session,context},family,{navigation:false});
   const drafts=copy(session.read(family,slot)||{});let count=0,completesActive=false;
   for(const key of Object.keys(drafts)){
    const draft=drafts[key];if(draft.draft_id!==draftId)continue;
    count+=1;
    if(draft.status!=='completed')drafts[key]={...draft,dirty:false,status:'completed',completed_plan_id:plan.id,completed_plan_version:plan.version};
    if(active && active.family===family && active.key===key)completesActive=true;
   }
   // The original may be nested in another draft's immutable source snapshot.
   // Record completion by identity; project it only when that identity is read.
   const completed=copy(session.read(family,completedSlot)||{});
   if(!completed[draftId]){completed[draftId]={completed_plan_id:plan.id,completed_plan_version:plan.version};current.assert();session.write(family,completedSlot,completed);}
   if(!count)return 0;
   current.assert();session.write(family,slot,drafts);if(completesActive)invalidate();return count;
  },
  refresh(){invalidate();if(active && (!session.user() || active.owner!==session.user().id || active.generation!==session.generation()))active=null;return read();},
  requestTicket(){const draft=requireDraft(),current=captureOutfitAccess({session,context},active.family,{edit:true});request+=1;return {request_id:newDraftId(),draft_id:draft.draft_id,revision:draft.revision,key:active.key,navigation,request,current};},
  applyRecommendation(ticket,result){
   const draft=read();if(!draft || draft.status==='completed' || !ticket || !ticket.current() || ticket.navigation!==navigation || ticket.request!==request || ticket.key!==active.key || ticket.draft_id!==draft.draft_id || ticket.revision!==draft.revision || (result.request_id && result.request_id!==ticket.request_id))return false;
   const fields={recommendation_id:result.recommendation_id || null,input_version:result.input_version || null,reason:result.reason || '',warnings:result.warnings || [],missing:result.missing || [],source:result.source,weather:result.weather || draft.weather};
   if(result.items && result.items.length)fields.main_items=copy(result.items);
   const next=patchDraft(draft,fields);next.dirty=draft.dirty;write(next);return true;
  },
  adoptSuggestion(result){const draft=read();if(!draft || draft.dirty || draft.main_items.length)return false;const ticket=this.requestTicket();return this.applyRecommendation(ticket,{...result,request_id:ticket.request_id});},
  beginEdit(plan,asNew=false){
   const original=requireDraft(false);if(String(plan.child_id)!==String(original.child_id)||plan.target_date!==original.target_date)throw new Error('方案与当前孩子或日期不一致');
   const subject=plan.preference_subject;
   const basis=subject?normalizeBasis({preference_mode:plan.preference_mode || (typeof subject==='object'?subject.mode:subject==='family'?'family':'designated_member'),designated_member_id:plan.designated_member_id || (typeof subject==='string' && subject.startsWith('member:')?subject.slice(7):null),preference_subject:subject}):normalizeBasis(original);
   const next={...createDraft(original.child_id,original.target_date,basis,plan.scene||original.scene),main_items:copy(plan.main_items || []),backup:copy(plan.backup || {mode:'none',items:[]}),
    target_plan_id:asNew?null:plan.id,expected_version:asNew?null:plan.version,source_plan_id:plan.id,source_sequence:plan.sequence,source_snapshot:asNew?null:copy(plan),weather:copy(plan.weather),dirty:false};
   invalidate();active.basis=basis;active.key=JSON.stringify([String(original.child_id),original.target_date,basisKey(basis)]);
   session.write(active.family,'outfit-basis:'+original.child_id,{...basis,scene:next.scene});return write(next);
  },
  adoptReusedDraft(result,source,acknowledged=false){
   const original=requireDraft(false),draft=result && result.draft,ctx=result && result.context,review=result && result.review;
   if(!source || !draft || !ctx || !review || String(source.child_id)!==String(original.child_id) || String(draft.child_id)!==String(original.child_id) || String(result.source_plan_id)!==String(source.id) || result.source_version!==source.version || ctx.target_date!==draft.target_date)throw new Error('来源方案或目标孩子已变化，请重新核对');
   if(!acknowledged && require('../services/calendar-view').reuseChanges(source,result).some(i=>i.changed))throw Object.assign(new Error('衣物资料已更新，请明确核对当前资料后继续'),{code:'GARMENT_ACK_REQUIRED'});
   const basis=normalizeBasis({...draft,preference_subject:ctx.preference_subject});
   const current=new Map((ctx.garments || []).map(g=>[itemId(g),g])),historical=new Map([...(source.main_items || []),...(source.backup && source.backup.items || [])].map(g=>[itemId(g),g]));
   const hydrate=entry=>({...copy(current.get(itemId(entry)) || historical.get(itemId(entry)) || {}),...copy(entry),version:entry.expected_version || entry.version});
   const next={...createDraft(original.child_id,draft.target_date,basis,draft.scene || source.scene || 'daily'),draft_id:draft.draft_id || newDraftId(),main_items:(draft.main_items || []).map(hydrate),backup:{...(draft.backup || {mode:'none'}),items:(draft.backup && draft.backup.items || []).map(hydrate)},
    source_plan_id:String(source.id),source_plan_version:source.version,reuse_source_snapshot:copy(source),input_version:review.input_version || null,weather:copy(ctx.weather),warnings:copy(review.warnings || []),missing:copy(review.missing || []),dirty:true};
   invalidate();active.date=draft.target_date;active.basis=basis;active.key=JSON.stringify([String(original.child_id),draft.target_date,basisKey(basis)]);
   session.write(active.family,'outfit-basis:'+original.child_id,{...basis,scene:next.scene});return write(next);
  },
  stageReplacement(id,item,usage='main'){
   const draft=requireDraft();id=String(id);if(!['main','backup'].includes(usage))throw new Error('请核对单品的主搭配或备用用途');
   if(usage==='main' && draft.locked_ids.includes(id))throw new Error('请先明确解除固定');
   const items=usage==='backup'?draft.backup.items:draft.main_items;if(!items.some(i=>itemId(i)===id))throw new Error('原单品已变化，请重新核对候选');
   invalidate();return write({...draft,replacement_staging:{replace_id:id,item:copy(item),usage,revision:draft.revision}});
  },
  cancelReplacement(){const draft=requireDraft();return write({...draft,replacement_staging:null});},
  confirmReplacement(){
   const draft=requireDraft(),staged=draft.replacement_staging;if(!staged || staged.revision!==draft.revision)throw new Error('候选暂存已变化，请重新核对');
   if(staged.usage==='backup')return patch({backup:{...draft.backup,items:draft.backup.items.map(i=>itemId(i)===staged.replace_id?{...copy(staged.item),...(i.replaces_garment_id?{replaces_garment_id:i.replaces_garment_id}:{})}:i)}});
   if(draft.locked_ids.includes(staged.replace_id))throw new Error('请先明确解除固定');return write(manualMainChange(draft,{main_items:draft.main_items.map(i=>itemId(i)===staged.replace_id?copy(staged.item):i),locked_ids:draft.locked_ids.filter(id=>id!==staged.replace_id)}));
  },
  stageBackup(backup){const draft=requireDraft();invalidate();return write({...draft,backup_staging:{...copy(backup),revision:draft.revision}});},
  cancelBackup(){const draft=requireDraft();return write({...draft,backup_staging:null});},
  confirmBackup(){const draft=requireDraft(),staged=draft.backup_staging;if(!staged || staged.revision!==draft.revision)throw new Error('备用暂存已变化，请重新核对');return patch({backup:{mode:staged.mode,items:copy(staged.items || [])},backup_needs_review:false});},
  fixed(id,enabled=true){return write(setFixed(requireDraft(),id,enabled));},
  excluded(id,enabled=true){return write(setExcluded(requireDraft(),id,enabled));},
  fromGarment(garment){const origin=requireDraft(false);const next={...createDraft(origin.child_id,origin.target_date,origin,origin.scene),main_items:[copy(garment)],locked_ids:[itemId(garment)],source_origin:origin,dirty:true};invalidate();return write(next);},
  returnOrigin(){const draft=requireDraft();if(!draft.source_origin)throw new Error('没有来源草稿');invalidate();write(copy(draft.source_origin));return read();},
  discard(){const draft=requireDraft(false),source=draft.target_plan_id && draft.source_snapshot;invalidate();const reset=createDraft(draft.child_id,draft.target_date,draft,source?source.scene:draft.scene);if(source)Object.assign(reset,{target_plan_id:source.id,expected_version:source.version,main_items:copy(source.main_items || []),backup:copy(source.backup || {mode:'none',items:[]}),source_snapshot:copy(source),source_plan_id:source.id,source_sequence:source.sequence,weather:copy(source.weather)});return write(reset);},
  payload(){return draftPayload(requireDraft(false));},
  setDateMode(f,c,mode){if(!session.user() || !['admin','editor','viewer'].includes(session.capability(f).role))throw new Error('家庭尚不可访问');if(!['today','tomorrow'].includes(mode))throw new Error('日期模式无效');session.write(f,'outfit-date-mode:'+c,mode);return mode;},
  dateMode(f,c){return session.read(f,'outfit-date-mode:'+c)||'today';}
 };
}
module.exports={createOutfitStore,createDraft,patchDraft,setFixed,setExcluded,draftPayload,newDraftId,normalizeBasis,basisKey,itemId};
