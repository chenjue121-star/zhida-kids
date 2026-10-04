const {test}=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const {storage}=require('./helpers');

function harness(){
 const root=path.resolve(__dirname,'..');
 for(const key of Object.keys(require.cache))if(['/services/','/pages/','/stores/'].some(part=>key.startsWith(root+part)))delete require.cache[key];
 const platform=storage(),nav=[];
 Object.assign(platform,{request(){},navigateBack:()=>nav.push('back'),navigateTo:o=>nav.push(o.url),reLaunch:o=>nav.push(o.url),showModal:o=>o.success({confirm:false})});
 global.wx=platform;
 let definition;global.Page=d=>definition=d;require('../pages/outfit-edit/outfit-edit');delete global.Page;
 const p={...definition,data:structuredClone(definition.data),setData(fields){Object.assign(this.data,fields);}};
 const rt=require('../services/runtime').getRuntime();
 rt.session.set({token:'t',user:{id:'u'}});
 require('../services/page').selectFamily('f');require('../services/page').selectChild('c');
 rt.session.capability('f','editor');rt.outfitStore.open('f','c','2026-10-03');
 rt.outfitStore.patch({main_items:[{id:'internal-a',version:1,name:'奶白T恤',category:'top',state:'ready',fit:'fit',asset_id:'photo-a'},{id:'b',version:1,name:'灰色长裤',category:'bottom',state:'ready',fit:'fit'}]});
 p.familyId='f';p._visible=true;p.data.ready=true;p.data.writable=true;p.data.targetDate='2026-10-03';
 p.data.draft=require('../services/outfit-view').draftView(rt.outfitStore.get());
 return {p,rt,nav};
}
const tap=(id,usage='main')=>({currentTarget:{dataset:{id,usage}}});
const mode=value=>({currentTarget:{dataset:{mode:value}}});

test('single garment operations are inspection only until an explicit action',async()=>{
 const {p,rt}=harness();const before=rt.outfitStore.get();
 p.openItem(tap('internal-a'));
 assert.equal(p.data.operationOpen,true);assert.equal(p.data.operationItem.name,'奶白T恤');
 assert.deepEqual(rt.outfitStore.get(),before);
 let asset;rt.media.preview=async(f,id)=>{asset=id;};await p.previewOperation();assert.equal(asset,'photo-a');
 p.closeItem();assert.equal(p.data.operationOpen,false);assert.deepEqual(rt.outfitStore.get(),before);
});

test('fixed and excluded summaries use garment names and preserve explicit unlocking',()=>{
 const {p,rt}=harness();p.openItem(tap('internal-a'));p.fix(tap('internal-a'));
 assert.equal(p.data.operationItem.fixed,true);assert.equal(p.data.lockedItems[0].name,'奶白T恤');
 p.exclude(tap('internal-a'));assert.deepEqual(rt.outfitStore.get().excluded_ids,[]);
 p.fix(tap('internal-a'));p.exclude(tap('internal-a'));
 assert.equal(p.data.excludedItems[0].name,'奶白T恤');
 const retained=rt.outfitStore.get().main_items;p.undoExclude(tap('internal-a'));
 assert.deepEqual(rt.outfitStore.get().main_items,retained);assert.deepEqual(p.data.excludedItems,[]);
});

test('full backup is one staged composition and cancel preserves confirmed backup',async()=>{
 const {p,rt}=harness();rt.outfitStore.patch({backup:{mode:'partial',items:[{id:'old',version:1,name:'原备用'}]}});
 p.syncDraft();const before=rt.outfitStore.get();p.openBackup();
 rt.outfits.backup=async()=>({items:[{id:'new-top',version:1,name:'备用上衣'},{id:'new-bottom',version:1,name:'备用裤子'},{id:'b',version:1,name:'灰色长裤'}]});
 await p.backupMode(mode('full'));
 assert.deepEqual(p.data.stagedBackup.items.map(i=>i.id),['new-top','new-bottom','b']);
 p.chooseBackup(tap('new-top'));assert.equal(p.data.stagedBackup.items.length,3);
 assert.deepEqual(rt.outfitStore.get().backup,before.backup);p.cancelBackup();assert.deepEqual(rt.outfitStore.get().backup,before.backup);
 p.openBackup();await p.backupMode(mode('full'));p.confirmBackup();
 assert.equal(rt.outfitStore.get().backup.mode,'full');assert.equal(rt.outfitStore.get().backup.items.length,3);
 assert.equal(p.data.packingCount,4);
});

test('partial backup remains independently selectable and mode cancellation rejects late choices',async()=>{
 const {p,rt}=harness();p.openBackup();rt.outfits.backup=async()=>({items:[{id:'x',version:1,name:'备用上衣'},{id:'y',version:1,name:'备用下装'}]});
 await p.backupMode(mode('partial'));assert.equal(p.data.stagedBackup.items.length,0);
 p.chooseBackup(tap('y'));p.confirmBackup();assert.deepEqual(rt.outfitStore.get().backup.items.map(i=>i.id),['y']);
 p.openBackup();let resolve;rt.outfits.backup=()=>new Promise(r=>resolve=r);
 const pending=p.backupMode(mode('full'));p.cancelBackup();resolve({items:[{id:'late',version:1}]});await pending;
 assert.equal(p.data.backupOpen,false);assert.deepEqual(p.data.backupChoices,[]);assert.deepEqual(rt.outfitStore.get().backup.items.map(i=>i.id),['y']);
});

test('readonly inspection cannot mutate and revoked access closes private operations',()=>{
 const {p,rt}=harness();p.openItem(tap('internal-a'));const before=rt.outfitStore.get();
 rt.session.capability('f','viewer');p.data.writable=false;p.fix(tap('internal-a'));p.exclude(tap('internal-a'));
 p.onEditRevoked();assert.equal(p.data.operationOpen,false);assert.equal(p.data.operationItem,null);
 assert.deepEqual(p.data.excludedItems,[]);assert.equal(p.data.draft.main_items[0].name,before.main_items[0].name);
});

test('closing item inspection precedes dirty leaving confirmation and preserves the draft',async()=>{
 const {p,rt,nav}=harness();const before=rt.outfitStore.get();p.openItem(tap('internal-a'));
 await p.back();assert.equal(p.data.operationOpen,false);assert.deepEqual(nav,[]);
 await p.back();assert.deepEqual(nav,[]);assert.deepEqual(rt.outfitStore.get(),before);
});

test('candidate photos arriving after cancel never repopulate the closed overlay',async()=>{
 const {p,rt}=harness();let resolve;
 rt.outfits.candidates=async()=>({items:[{id:'candidate',version:1,name:'备用T恤',asset_id:'candidate-image'}]});
 rt.media.image=()=>new Promise(r=>resolve=r);
 await p.replace(tap('internal-a'));await new Promise(r=>setImmediate(r));
 p.cancelCandidates();resolve('private-photo');await new Promise(r=>setImmediate(r));
 assert.deepEqual(p.data.candidates,[]);assert.equal(p.data.candidateOpen,false);
});

test('discarding an edit shows the latest shared plan rather than its old source snapshot',async()=>{
 const {p,rt}=harness();
 const source={id:'plan',child_id:'c',target_date:'2026-10-03',version:1,scene:'daily',main_items:[{id:'old',version:1,name:'此前共享单品'}],backup:{mode:'none',items:[]}};
 rt.outfitStore.beginEdit(source);rt.outfitStore.patch({main_items:[{id:'my-change',version:1}]});p.syncDraft();
 global.wx.showModal=o=>o.success({confirm:true});
 const latest={...source,version:2,main_items:[{id:'latest',version:2,name:'家人最新单品'}]};
 rt.outfits.context=async()=>({plans:[latest]});await p.discard();
 assert.equal(rt.outfitStore.get().expected_version,2);assert.equal(p.data.draft.main_items[0].name,'家人最新单品');
 assert.equal(rt.outfitStore.get().dirty,false);assert.deepEqual(rt.outfitStore.get().sharing_grants,[]);
});

test('failed latest-plan lookup leaves the edit intact after discard confirmation',async()=>{
 const {p,rt}=harness();
 rt.outfitStore.beginEdit({id:'plan',version:1,child_id:'c',target_date:'2026-10-03',main_items:[{id:'old',version:1}],backup:{mode:'none',items:[]}});
 rt.outfitStore.patch({main_items:[{id:'my-change',version:1}]});p.syncDraft();const before=rt.outfitStore.get();
 global.wx.showModal=o=>o.success({confirm:true});rt.outfits.context=async()=>{throw new Error('网络暂不可用');};await p.discard();
 assert.deepEqual(rt.outfitStore.get(),before);assert.match(p.data.error,/网络/);
});

test('a requested garment opens only after fresh context restores the corresponding draft',async()=>{
 const {p,rt}=harness();p.onLoad({date:'2026-10-03',item:'internal-a',usage:'main'});
 rt.api.request=async()=>[{id:'member',user_id:'u',status:'active',role:'editor'}];
 rt.outfits.context=async()=>({target_date:'2026-10-03',today:'2026-10-03',role:'editor',garments:[],plans:[],weather:{status:'unknown'},preference_subject:{mode:'family',owner_key:'family'}});
 rt.media.image=async()=>'';await p.reload();
 assert.equal(p.data.operationOpen,true);assert.equal(p.data.operationItem.name,'奶白T恤');assert.equal(p.requestedItem,null);
});

test('temporary exclusion displays its vacated garment position and offers explicit refill',()=>{
 const {p}=harness();p.exclude(tap('internal-a'));
 assert.equal(p.data.emptySlots[0].categoryLabel,'上衣');assert.equal(p.data.emptySlots[0].name,'奶白T恤');
 p.undoExclude(tap('internal-a'));assert.equal(p.data.emptySlots[0].categoryLabel,'上衣');
});

test('wardrobe navigation protects dirty changes and a delayed confirmation cannot leave another context',async()=>{
 const {p,rt,nav}=harness();await p.wardrobe();assert.deepEqual(nav,[]);
 let answer;global.wx.showModal=o=>answer=o.success;const leaving=p.wardrobe();
 require('../services/page').selectChild('other');answer({confirm:true});await leaving;assert.deepEqual(nav,[]);
});

test('permission loss during discard confirmation keeps the original draft and does not throw',async()=>{
 const {p,rt}=harness();const before=p.data.draft;
 let answer;global.wx.showModal=o=>answer=o.success;const discarding=p.discard();
 rt.session.capability('f','viewer');answer({confirm:true});await assert.doesNotReject(()=>discarding);
 assert.equal(p.data.draft.draft_id,before.draft_id);assert.equal(p.data.error,'');
});

test('unlocking clears the obsolete locked-action error',()=>{
 const {p}=harness();p.fix(tap('internal-a'));p.exclude(tap('internal-a'));assert.match(p.data.error,/解除固定/);
 p.fix(tap('internal-a'));assert.equal(p.data.error,'');
});

test('no alternative recommendation preserves the visible vacant position and fixed piece',async()=>{
 const {p,rt}=harness();p.fix(tap('b'));p.exclude(tap('internal-a'));
 rt.outfits.recommend=async()=>({items:[],missing:[{code:'MISSING_BODY',message:'缺少适合本次场景的主体衣物'}]});await p.generate();
 assert.equal(p.data.emptySlots[0].categoryLabel,'上衣');assert.deepEqual(rt.outfitStore.get().locked_ids,['b']);
 assert.match(p.data.error,/主体衣物/);
});

test('partial backup distinguishes replacement positions while selecting each physical item once',async()=>{
 const {p,rt}=harness();rt.outfitStore.patch({main_items:[...rt.outfitStore.get().main_items,{id:'second-top',version:1,name:'条纹上衣',category:'top'}]});p.syncDraft();p.openBackup();
 rt.outfits.backup=async()=>({items:[{id:'shared-backup',version:1,name:'备用上衣',replaces_garment_id:'internal-a'},{id:'shared-backup',version:1,name:'备用上衣',replaces_garment_id:'second-top'}]});
 await p.backupMode(mode('partial'));
 assert.notEqual(p.data.backupChoices[0].choiceKey,p.data.backupChoices[1].choiceKey);
 assert.match(p.data.backupChoices[0].backupUseLabel,/奶白T恤/);assert.match(p.data.backupChoices[1].backupUseLabel,/条纹上衣/);
 p.chooseBackup({currentTarget:{dataset:{id:'shared-backup',key:p.data.backupChoices[0].choiceKey}}});
 assert.equal(p.data.stagedBackup.items.length,1);assert.equal(p.data.stagedBackup.items[0].replaces_garment_id,'internal-a');
 p.chooseBackup({currentTarget:{dataset:{id:'shared-backup',key:p.data.backupChoices[1].choiceKey}}});
 assert.deepEqual(p.data.backupChoices.map(i=>i.selected),[false,true]);assert.equal(p.data.stagedBackup.items.length,1);
 p.confirmBackup();assert.equal(rt.outfitStore.get().backup.items[0].replaces_garment_id,'second-top');
});
