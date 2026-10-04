const {test}=require('node:test');
const assert=require('node:assert/strict');
const {storage}=require('./helpers');
const {createSession}=require('../services/session');
const {createContextStore}=require('../stores/context');
const {createOutfitStore}=require('../stores/outfit-context');

const item=(id,category='top')=>({id,garment_id:id,version:1,expected_version:1,category,name:id});
function setup(){
 const context=createContextStore(),session=createSession(storage(),context);
 session.set({token:'fixture-token',user:{id:'fixture-user'}});
 session.capability('family','editor');context.select({familyId:'family',childId:'child'});
 const store=createOutfitStore(session,context);store.open('family','child','2026-10-03');
 store.patch({main_items:[item('top'),item('bottom','bottom')],
  backup:{mode:'partial',items:[{...item('spare'),replaces_garment_id:'top'}]},
  sharing_grants:[{token:'fixture-grant'}]});
 return store;
}

test('confirmed manual main replacement clears confirmed and staged backup but leaves shared source unchanged',()=>{
 const store=setup();
 const source={id:'selected',version:1,child_id:'child',target_date:'2026-10-03',
  main_items:store.get().main_items,backup:store.get().backup,scene:'daily'};
 store.beginEdit(source);
 const frozen=JSON.stringify(source),draftId=store.get().draft_id;
 store.stageBackup({mode:'full',items:[item('staged')]});
 store.stageReplacement('top',item('new-top'));store.confirmReplacement();
 const draft=store.get();
 assert.deepEqual(draft.main_items.map(i=>i.id),['new-top','bottom']);
 assert.deepEqual(draft.backup,{mode:'none',items:[]});
 assert.equal(draft.backup_staging,null);assert.equal(draft.replacement_staging,null);
 assert.equal(draft.backup_needs_review,true);assert.equal(store.payload().backup_needs_review,true);
 assert.equal(draft.draft_id,draftId);assert.equal(draft.target_plan_id,'selected');
 assert.equal(JSON.stringify(source),frozen);
});

test('excluding a main garment clears draft backup and staging while preserving the other main garment',()=>{
 const store=setup();store.stageBackup({mode:'partial',items:[item('staged')]});
 store.excluded('top',true);
 assert.deepEqual(store.get().main_items.map(i=>i.id),['bottom']);
 assert.deepEqual(store.get().backup,{mode:'none',items:[]});
 assert.equal(store.get().backup_staging,null);assert.equal(store.get().backup_needs_review,true);
 assert.deepEqual(store.get().sharing_grants,[]);
 store.excluded('top',false);
 assert.deepEqual(store.get().backup,{mode:'none',items:[]});
 assert.equal(store.get().backup_needs_review,true);
 store.stageBackup({mode:'none',items:[]});store.confirmBackup();
 assert.equal(store.get().backup_needs_review,false);
});

test('cancelling a staged main replacement preserves previously confirmed backup',()=>{
 const store=setup(),backup=store.get().backup;
 store.stageReplacement('top',item('new-top'));store.cancelReplacement();
 assert.deepEqual(store.get().backup,backup);assert.equal(store.get().backup_needs_review,false);
});

test('backup-only replacement preserves its mode and compatibility target',()=>{
 const store=setup();store.stageReplacement('spare',item('other-spare'),'backup');store.confirmReplacement();
 assert.equal(store.get().backup.mode,'partial');
 assert.equal(store.get().backup.items[0].id,'other-spare');
 assert.equal(store.get().backup.items[0].replaces_garment_id,'top');
 assert.equal(store.get().backup_needs_review,false);
});

test('scene weather and preference refreshes preserve confirmed backup',()=>{
 const store=setup(),backup=store.get().backup;
 store.patch({scene:'outdoor'});
 store.patch({weather:{status:'unknown',target_date:'2026-10-03'}});
 store.patch({preference_subject:{mode:'family',owner_key:'family',profile_version:2}});
 assert.deepEqual(store.get().backup,backup);assert.equal(store.get().backup_needs_review,false);
});

test('successful recommendation preserves existing backup rather than treating it as a manual replacement',()=>{
 const store=setup(),backup=store.get().backup,ticket=store.requestTicket();
 assert.equal(store.applyRecommendation(ticket,{request_id:ticket.request_id,
  items:[item('recommended-top'),item('bottom','bottom')],input_version:'conditions'}),true);
 assert.deepEqual(store.get().backup,backup);
});

test('no alternative or failed provider fallback preserves main fixed exclusions and confirmed backup',()=>{
 const store=setup();store.fixed('top',true);store.excluded('not-current-main',true);
 const before=store.get(),ticket=store.requestTicket();
 assert.equal(store.applyRecommendation(ticket,{request_id:ticket.request_id,items:[],
  warnings:[{code:'PROVIDER_UNAVAILABLE'}],missing:[{code:'NO_ALTERNATIVE'}]}),true);
 const after=store.get();
 for(const key of ['main_items','locked_ids','excluded_ids','backup'])assert.deepEqual(after[key],before[key]);
});

test('manual change without existing backup does not add a mandatory backup step',()=>{
 const store=setup();store.stageBackup({mode:'none',items:[]});store.confirmBackup();
 store.stageReplacement('top',item('new-top'));store.confirmReplacement();
 assert.deepEqual(store.get().backup,{mode:'none',items:[]});assert.equal(store.get().backup_needs_review,false);
});
