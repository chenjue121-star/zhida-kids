const {test}=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs');
const {storage}=require('./helpers');
function harness(name){
 const root=path.resolve(__dirname,'..');
 for(const key of Object.keys(require.cache))if(key.startsWith(root+'/services/')||key.startsWith(root+'/pages/'))delete require.cache[key];
 const platform=storage(),patches=[];global.wx=platform;let def;global.Page=d=>def=d;require('../pages/'+name+'/'+name);delete global.Page;
 const p={...def,data:structuredClone(def.data),setData(patch){patches.push(patch);for(const [k,v] of Object.entries(patch)){const keys=k.replace(/\[(\d+)\]/g,'.$1').split('.');let o=this.data;for(const key of keys.slice(0,-1))o=o[key];o[keys.at(-1)]=v;}}};
 const rt=require('../services/runtime').getRuntime();rt.session.set({token:'test',user:{id:'u'}});require('../services/page').selectFamily('f');rt.session.capability('f','editor');p.familyId='f';p.batchId='b';p._visible=true;p.data.writable=true;p.data.ready=true;
 return {p,rt,patches};
}
function batch(count=75){return {id:'b',default_child_id:'child',items:Array.from({length:count},(_,i)=>({id:'item-'+i,client_id:'source-'+i,source:'album',asset_id:'asset-'+i,status:'succeeded',discarded:false,version:1})),candidates:Array.from({length:count},(_,i)=>({id:'candidate-'+i,item_id:'item-'+i,asset_id:'asset-'+i,name:'单品 '+i,version:1,category:'top',colors:['green'],owners:[{child_id:'child',fit:'unknown'}],selected:false,discarded:false,confirmed_garment_id:null}))};}
for(const [name,list,visible,page,change] of [['intake','photos','visiblePhotos','photoPage','changePhotoPage'],['intake-confirm','candidates','visibleCandidates','candidatePage','changeCandidatePage']]){
 test(name+' renders and downloads at most 12 thumbnails for a large batch',async()=>{
  const {p,rt,patches}=harness(name),calls=[];p.update(batch());assert.equal(p.data[list].length,75);assert.equal(p.data[visible].length,12);rt.media.image=async(f,id,opts)=>{calls.push({id,opts});return '/thumb/'+id;};patches.length=0;await p.images(()=>true);
  assert.equal(calls.length,12);assert.ok(calls.every(c=>c.opts.draft===true&&c.opts.thumbnail===true));assert.equal(patches.some(x=>Object.hasOwn(x,list)||Object.hasOwn(x,visible)),false);assert.equal(p.data[visible][0].image,'/thumb/asset-0');assert.equal(p.data[list][0].image,'/thumb/asset-0');
 });
 test(name+' stops pending image loop immediately after hiding',async()=>{
  const {p,rt}=harness(name);p.update(batch());let release,calls=0;rt.media.image=()=>{calls++;return calls===1?new Promise(r=>release=r):Promise.resolve('/unexpected');};const loading=p.images(()=>true);p.onHide();release('/late');await loading;assert.equal(calls,1);assert.equal(p.data[list][0].image,undefined);
 });
 test(name+' ignores a prior page response and only loads the new page',async()=>{
  const {p,rt}=harness(name);p.update(batch(30));assert.equal(typeof p[change],'function');let release;const calls=[];rt.media.image=async(f,id)=>{calls.push(id);if(id==='asset-0')return new Promise(r=>release=r);return '/thumb/'+id;};const old=p.images(()=>true);p[change]({currentTarget:{dataset:{step:1}}});await new Promise(r=>setImmediate(r));release('/stale');await old;await new Promise(r=>setImmediate(r));assert.equal(p.data[page],1);assert.equal(p.data[visible][0].id,name==='intake'?'item-12':'candidate-12');assert.equal(p.data[visible][0].image,'/thumb/asset-12');assert.equal(p.data[list][0].image,undefined);assert.equal(calls.length,13);
 });
 test(name+' retains loaded thumbnails when batch details refresh',async()=>{
  const {p,rt}=harness(name),b=batch(15);p.update(b);let calls=0;rt.media.image=async(f,id)=>{calls++;return '/thumb/'+id;};await p.images(()=>true);p.update(b);await p.images(()=>true);assert.equal(calls,12);assert.equal(p.data[visible][0].image,'/thumb/asset-0');
 });
 test(name+' never requests another image after edit access changes',async()=>{
  const {p,rt}=harness(name);p.update(batch());let calls=0;rt.media.image=async()=>{calls++;rt.session.capability('f','viewer');return '/stale';};await p.images(()=>true);assert.equal(calls,1);assert.equal(p.data[list][0].image,undefined);
 });
 test(name+' list binds only its visible page',()=>{
  const source=fs.readFileSync(path.resolve(__dirname,'../pages/'+name+'/'+name+'.wxml'),'utf8');assert.ok(source.includes('wx:for="{{'+visible+'}}"'));assert.ok(source.includes('bindtap="'+change+'"'));
 });
}
test('empty local upload queue does not refresh or start a second image loop',async()=>{const {p}=harness('intake');let refreshed=0;p.refresh=async()=>{refreshed++;};await p.pump();assert.equal(refreshed,0);});
test('checkbox change only updates its current page and preserves hidden selected candidates',async()=>{
 const {p,rt}=harness('intake-confirm'),b=batch(30);b.candidates[20].selected=true;p.update(b);const calls=[];rt.intake.candidate=async(f,id,fields,cid)=>calls.push({fields,cid});p.refresh=()=>{};await p.select({detail:{value:['candidate-0']}});assert.deepEqual(calls.map(x=>x.cid),['candidate-0']);assert.equal(p.data.candidates[20].selected,true);
});
test('confirmation entries and fit warnings still use the complete batch across pages',()=>{
 const {p}=harness('intake-confirm'),b=batch(30);b.candidates[0].selected=true;b.candidates[20].selected=true;p.update(b);assert.equal(p.data.selectedCount,2);assert.equal(p.data.unknownFitCount,30);assert.deepEqual(p.entries().map(x=>x.candidate_id),['candidate-0','candidate-20']);
});
