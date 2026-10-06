const {test}=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs');
const {storage}=require('./helpers');

function harness(name){
 const root=path.resolve(__dirname,'..');
 for(const key of Object.keys(require.cache))if(key.startsWith(root+'/services/')||key.startsWith(root+'/pages/'))delete require.cache[key];
 const platform=storage(),requests=[],nav=[];
 Object.assign(platform,{request:o=>requests.push(o),navigateTo:o=>nav.push(o.url),reLaunch:o=>nav.push(o.url),redirectTo:o=>nav.push(o.url),navigateBack:()=>nav.push('back'),showToast(){},showModal:o=>o.success({confirm:true})});
 global.wx=platform;let def;global.Page=d=>def=d;require('../pages/'+name+'/'+name);delete global.Page;
 const p={...def,data:structuredClone(def.data),setData(patch){for(const [k,v]of Object.entries(patch)){const keys=k.split('.');let o=this.data;for(const key of keys.slice(0,-1))o=o[key];o[keys.at(-1)]=v;}}};
 const rt=require('../services/runtime').getRuntime();rt.session.set({token:'t',user:{id:'u'}});require('../services/page').selectFamily('f');rt.session.capability('f','editor');p.familyId='f';
 return {p,rt,requests,nav};
}

function batch(){return {id:'b',default_child_id:'a',items:[{id:'i1',client_id:'photo1',source:'camera',asset_id:'asset1',status:'succeeded',candidates:[{id:'c1'},{id:'c2'}]},{id:'i2',client_id:'photo2',source:'album',asset_id:'asset2',status:'running',candidates:[]}],candidates:[{id:'c1',item_id:'i1',asset_id:'asset1',selected:true,owners:[{child_id:'a',nickname:'豆子',fit:'large'}],name:'外套',category:'outerwear',state:'washing'},{id:'c2',item_id:'i1',asset_id:'asset1',selected:false,owners:[{child_id:'a',nickname:'豆子',fit:'fit'}],name:'短裤',category:'bottom',state:'ready'}]};}

test('photo queue keeps photo identity and per-photo candidate counts separate from the total',()=>{
 const {p}=harness('intake');p.batchId='b';p.update(batch());
 assert.equal(p.data.photos[0].sourceLabel,'照片 1');assert.equal(p.data.photos[0].candidateCount,2);assert.equal(p.data.photos[0].multi,true);
 assert.equal(p.data.photos[1].sourceLabel,'照片 2');assert.equal(p.data.photos[1].candidateCount,0);assert.equal(p.data.candidateCount,2);
});
test('reviewed intake entry launches its requested method once and preserves an existing batch default',async()=>{
 const {p,rt}=harness('intake');p.onLoad({child:'other',method:'camera'});p.data.ready=true;p.data.writable=true;let captures=0;p.camera=()=>captures++;p.startEntry();p.startEntry();assert.equal(captures,1);
 const existing=harness('intake');existing.p.onLoad({batch:'b',child:'other',method:'album'});existing.rt.api.request=async url=>url.endsWith('/members')?[{user_id:'u',status:'active',role:'editor'}]:[{id:'a',nickname:'豆子'},{id:'other',nickname:'妹妹'}];existing.rt.intake.get=async()=>batch();existing.p.pump=()=>{};existing.p.schedule=()=>{};existing.p.images=()=>{};let albums=0;existing.p.album=()=>albums++;await existing.p.reload();assert.equal(existing.p.data.defaultChild.id,'a');assert.equal(albums,0);
});
test('confirmation exposes source photo, each child fit, fixed batch child and actual leftovers',()=>{
 const {p}=harness('intake-confirm');p.batchId='b';p.data.children=[{id:'a',nickname:'豆子'},{id:'other',nickname:'妹妹'}];p.update(batch());
 assert.equal(p.data.candidates[0].sourceLabel,'照片 1 · 候选 1 / 2');assert.equal(p.data.candidates[0].owners[0].fitLabel,'偏大');
 assert.equal(p.data.defaultChildLabel,'豆子');assert.equal(p.data.remainingCandidates,1);assert.equal(p.data.processingPhotos,1);
});
test('fit awaiting confirmation counts each pending garment once and excludes discarded or confirmed candidates',()=>{
 const {p}=harness('intake-confirm');p.batchId='b';const b=batch();
 b.candidates[0].owners=[{child_id:'a',fit:'unknown'},{child_id:'other',fit:'unknown'}];
 b.candidates[1].owners=[{child_id:'a',fit:'unknown'}];
 b.candidates.push({...b.candidates[1],id:'confirmed',confirmed_garment_id:'g',selected:true});
 b.candidates.push({...b.candidates[1],id:'discarded',discarded:true,selected:true});
 p.update(b);assert.equal(p.data.unknownFitCount,2);assert.equal(p.data.selectedCount,1);
 p.onEditRevoked();assert.equal(p.data.unknownFitCount,0);
});
test('unknown-fit guidance permits saving reviewed possessions while ordinary defaults retain their existing note',()=>{
 const {p}=harness('intake-confirm');p.batchId='b';p.update(batch());assert.equal(p.data.unknownFitCount,0);
 const markup=fs.readFileSync(path.resolve(__dirname,'../pages/intake-confirm/intake-confirm.wxml'),'utf8');
 assert.match(markup,/wx:if="{{unknownFitCount}}"[^>]*>[^<]*本批 {{unknownFitCount}} 件合身待确认/);
 assert.match(markup,/先核对你实际拥有的实物，可以先保存资料；确认合身后用于推荐/);
 assert.match(markup,/wx:else[^>]*>勾选你实际拥有的实物。多件图默认不选；未选候选会保留。默认合身、可穿，例外可以逐件修改。/);
});
test('cancelling the unknown-fit save dialog uses the current selection and makes no request',async()=>{
 const {p,requests}=harness('intake-confirm');p.batchId='b';p.data.writable=true;const b=batch();
 b.candidates[0].owners=[{child_id:'a',fit:'unknown'},{child_id:'other',fit:'unknown'}];b.candidates[1].owners=[{child_id:'a',fit:'unknown'}];p.update(b);
 p.data.unknownFitCount=99;let modal;global.wx.showModal=o=>{modal=o;o.success({confirm:false});};const before=structuredClone(p.data.candidates);
 await p.save();assert.match(modal.content,/其中 1 件合身待确认/);assert.match(modal.content,/会保留该状态，不用于搭配/);
 assert.equal(requests.length,0);assert.deepEqual(p.data.candidates,before);
});
test('saving a selected unknown-fit garment retains its draft fit and sends no ownership replacement',async()=>{
 const {p,rt}=harness('intake-confirm');p.batchId='b';p.data.writable=true;const b=batch();b.candidates[0].owners=[{child_id:'a',fit:'unknown'}];b.candidates[0].version=3;p.update(b);p.refresh=()=>{};
 let modal;global.wx.showModal=o=>{modal=o;o.success({confirm:true});};const calls=[];
 rt.api.request=async(url,options)=>{calls.push({url,options});return {status:'completed',counts:{new:1,existing:0,failed:0},results:[{candidate_id:'c1',status:'success',kind:'new',garment:{id:'g',name:'外套',state:'washing',owners:[{child_id:'a',fit:'unknown'}]}}]};};
 await p.save();assert.match(modal.content,/其中 1 件合身待确认/);assert.equal(calls.length,1);assert.equal(calls[0].url,'/families/f/intake/batches/b/confirm');
 assert.deepEqual(calls[0].options.data.entries,[{candidate_id:'c1',expected_version:3,action:'new'}]);
 assert.equal(p.data.candidates[0].owners[0].fit,'unknown');assert.equal(p.data.result.results[0].garment.owners[0].fit,'unknown');assert.equal(p.data.candidates[0].state,'washing');
});
test('ordinary save retains the default fit and ready-state description',async()=>{
 const {p,rt}=harness('intake-confirm');p.batchId='b';p.data.writable=true;const b=batch();Object.assign(b.candidates[0],{state:'ready',owners:[{child_id:'a',fit:'fit'}],version:1});p.update(b);p.refresh=()=>{};
 let modal;global.wx.showModal=o=>{modal=o;o.success({confirm:true});};rt.intake.confirm=async()=>({status:'completed',counts:{new:1,existing:0,failed:0},results:[]});
 await p.save();assert.equal(modal.content,'本次选中的衣物按所列宝贝归属入库，默认合身、可穿；已调整的例外会保留。');assert.equal(p.data.candidates[0].owners[0].fit,'fit');assert.equal(p.data.candidates[0].state,'ready');
});
test('an unresolved original operation goes straight to query without another fit dialog',async()=>{
 const {p,rt}=harness('intake-confirm');p.batchId='b';p.data.writable=true;const b=batch();b.candidates[0].owners=[{child_id:'a',fit:'unknown'}];rt.session.write('f','intake-operation:b',{operation_id:'pending',entries:[{candidate_id:'c1'}]});p.update(b);
 let queries=0,modals=0;p.query=async()=>queries++;global.wx.showModal=()=>modals++;await p.save();assert.equal(queries,1);assert.equal(modals,0);
});
test('the single candidate review action dispatches fields, fit and explicit discard for the same candidate',async()=>{
 const {p,rt,nav}=harness('intake-confirm');p.batchId='b';p.data.ready=true;p.data.writable=true;p.update(batch());let sheet;global.wx.showActionSheet=o=>sheet=o;
 const event={currentTarget:{dataset:{id:'c1'}}};p.review(event);assert.deepEqual(sheet.itemList,['核对资料','归属与合身','明确放弃这个候选']);sheet.success({tapIndex:0});assert.equal(nav[0],'/pages/garment-edit/garment-edit?batch=b&id=c1');
 p.review(event);sheet.success({tapIndex:1});assert.equal(nav[1],'/pages/garment-owners/garment-owners?batch=b&id=c1');
 p.data.candidates[0].version=3;p.refresh=()=>{};let discard;rt.intake.candidate=async(f,b,data,id)=>{discard={f,b,data,id};};p.review(event);await sheet.success({tapIndex:2});assert.deepEqual(discard,{f:'f',b:'b',data:{expected_version:3,discarded:true,selected:false},id:'c1'});
});
test('candidate review is inert while busy, read only or already confirmed and cancellation remains reversible',()=>{
 const {p,nav}=harness('intake-confirm');p.batchId='b';p.data.ready=true;p.data.writable=true;p.update(batch());const event={currentTarget:{dataset:{id:'c1'}}};let count=0,sheet;global.wx.showActionSheet=o=>{count++;sheet=o;};
 p.data.busy=true;p.review(event);p.data.busy=false;p.data.writable=false;p.review(event);p.data.writable=true;p.data.candidates[0].confirmed_garment_id='g';p.review(event);assert.equal(count,0);
 p.data.candidates[0].confirmed_garment_id=null;p.review(event);p.review(event);assert.equal(count,1);sheet.fail({errMsg:'cancel'});p.review(event);assert.equal(count,2);assert.equal(nav.length,0);
});
test('a candidate review menu from an old family or downgraded capability cannot dispatch actions',()=>{
 const {p,rt,nav}=harness('intake-confirm');p.batchId='b';p.data.ready=true;p.data.writable=true;p.update(batch());let sheet;global.wx.showActionSheet=o=>sheet=o;const event={currentTarget:{dataset:{id:'c1'}}};
 p.review(event);rt.session.capability('f','viewer');sheet.success({tapIndex:0});assert.equal(nav.length,0);
 rt.session.capability('f','editor');p.review(event);require('../services/page').selectFamily('other');sheet.success({tapIndex:1});assert.equal(nav.length,0);
});
test('a review menu response after page hiding or candidate confirmation is discarded',()=>{
 const {p,nav}=harness('intake-confirm');p.batchId='b';p.data.ready=true;p.data.writable=true;p.update(batch());let sheet;global.wx.showActionSheet=o=>sheet=o;const event={currentTarget:{dataset:{id:'c1'}}};
 p.review(event);p.data.candidates[0].confirmed_garment_id='g';sheet.success({tapIndex:0});assert.equal(nav.length,0);p.data.candidates[0].confirmed_garment_id=null;p.review(event);p.onHide();sheet.success({tapIndex:0});assert.equal(nav.length,0);
});
test('cancelled manual filling remains visible and resumes the original photo-free item',async()=>{
 const {p,nav}=harness('intake');p.batchId='b';p.data.writable=true;const b=batch();b.items.push({id:'manual',client_id:'m',source:'manual',status:'manual',version:1,candidates:[]});p.update(b);
 assert.equal(p.data.photos.length,2);assert.equal(p.data.manualDrafts.length,1);await p.manual({currentTarget:{dataset:{id:'manual'}}});assert.equal(nav[0],'/pages/garment-edit/garment-edit?batch=b&item=manual');
});
test('result leftovers count an unfinished manual draft without describing it as a photo',()=>{
 const {p,rt}=harness('intake-confirm');p.batchId='b';rt.session.write('f','intake-result:b',{operation_id:'saved',status:'completed',counts:{new:1,existing:0,failed:0},results:[]});p.update({id:'b',items:[{id:'m',source:'manual',status:'manual',candidates:[]}],candidates:[]});
 assert.equal(p.data.processingPhotos,0);assert.equal(p.data.attentionPhotos,0);assert.equal(p.data.unfinishedManualCount,1);assert.equal(p.data.hasRemaining,true);
});
test('reopening confirmation restores identifiable original result and keeps unfinished work',()=>{
 const {p,rt}=harness('intake-confirm');p.batchId='b';const b=batch();b.candidates[0].confirmed_garment_id='g';
 rt.session.write('f','intake-result:b',{operation_id:'op',status:'completed',counts:{new:1,existing:0,failed:0},results:[{candidate_id:'c1',status:'success',kind:'new',garment:{id:'g',name:'外套',state:'washing',owners:[{child_id:'a',nickname:'豆子',fit:'large'}]}}]});
 p.update(b);assert.equal(p.data.resultMode,true);assert.equal(p.data.resultRows[0].name,'外套');assert.equal(p.data.resultRows[0].owners[0].fitLabel,'偏大');assert.equal(p.data.resultRows[0].stateLabel,'待洗');
 assert.equal(p.data.remainingCandidates,1);assert.equal(p.data.processingPhotos,1);assert.equal(p.data.hasRemaining,true);
 const candidates=structuredClone(p.data.candidates);p.continueProcessing();assert.equal(p.data.resultMode,false);assert.deepEqual(p.data.candidates,candidates);
});
test('a pending unknown operation cannot be disguised by a previous completed result',()=>{
 const {p,rt}=harness('intake-confirm');p.batchId='b';rt.session.write('f','intake-result:b',{operation_id:'old',status:'completed',counts:{new:1,existing:0,failed:0},results:[]});rt.session.write('f','intake-operation:b',{operation_id:'pending',entries:[{candidate_id:'c1'}]});p.update(batch());
 assert.equal(p.data.unknownResult,true);assert.equal(p.data.resultMode,false);
});
test('a same-photo manual candidate can inspect its full source before it exists',async()=>{
 const {p,rt}=harness('garment-edit');p.batchId='b';p.itemId='i1';p.data.candidateMode=true;p.data.newCandidate=true;
 rt.api.request=async url=>url.endsWith('/members')?[{user_id:'u',status:'active',role:'editor'}]:[{id:'a',nickname:'豆子'}];rt.intake.get=async()=>batch();let option;
 rt.media.image=async(f,id,opts)=>{assert.equal(id,'asset1');option=opts;return '/source.jpg';};
 await p.reload();assert.equal(p.data.garment.asset_id,'asset1');assert.equal(p.data.sourceLabel,'照片 1');assert.equal(p.data.image,'/source.jpg');assert.equal(option.draft,true);
});
test('field source thumbnails ignore late responses and clear when draft access is revoked',async()=>{
 const {p,rt}=harness('garment-edit');p.data.garment={asset_id:'a'};p.data.image='';rt.media.image=async()=>'/late.jpg';await p.images(()=>false);assert.equal(p.data.image,'');
 p.data.ready=true;p.data.writable=true;rt.media.image=async()=>{rt.session.capability('f','viewer');throw Object.assign(new Error('编辑权限已变化'),{code:'EDIT_ACCESS_REVOKED',familyId:'f'});};await p.images(()=>true);assert.equal(p.data.ready,false);assert.equal(p.data.image,'');assert.equal(p.data.garment,null);
});
test('viewing the full field source preserves an unresolved conflict, latest content and personal input',async()=>{
 const {p,rt}=harness('garment-edit');p.batchId='b';p.data.ready=true;p.data.writable=true;p.data.garment={asset_id:'photo'};p.data.conflict=true;p.data.error='家人已修改，请核对';p.data.latest={name:'家人最新外套',version:4,owners:[{child_id:'a',fit:'small'}]};p.data.form.name='我的旧填写';p.data.form.fit='large';const latest=structuredClone(p.data.latest),form=structuredClone(p.data.form);
 rt.media.preview=async(f,asset,options)=>{assert.equal(f,'f');assert.equal(asset,'photo');assert.equal(options.draft,true);};await p.preview();assert.equal(p.data.conflict,true);assert.equal(p.data.error,'家人已修改，请核对');assert.deepEqual(p.data.latest,latest);assert.deepEqual(p.data.form,form);
});
test('returning from the full source revalidates permission without clearing the field conflict',async()=>{
 const {p,rt}=harness('garment-edit');p.batchId='b';p.data.ready=true;p.data.writable=true;p.data.garment={asset_id:'photo'};p.data.conflict=true;p.data.error='内容已变化';p.data.latest={name:'家人新填写',version:8};p.data.form.name='本人待核对填写';const latest=structuredClone(p.data.latest),form=structuredClone(p.data.form);rt.media.preview=async()=>{};rt.api.request=async url=>url.endsWith('/members')?[{user_id:'u',status:'active',role:'editor'}]:[{id:'a',nickname:'豆子'}];
 await p.preview();p.onHide();p.onShow();await new Promise(resolve=>setImmediate(resolve));assert.equal(p.data.conflict,true);assert.equal(p.data.error,'内容已变化');assert.deepEqual(p.data.latest,latest);assert.deepEqual(p.data.form,form);assert.equal(p.data.writable,true);
});
test('field source preview still clears a revoked draft while running without form-state resets',async()=>{
 const {p,rt}=harness('garment-edit');p.batchId='b';p.data.ready=true;p.data.writable=true;p.data.garment={asset_id:'photo'};p.data.latest={name:'旧稿'};p.data.form.name='本人填写';rt.media.preview=async()=>{rt.session.capability('f','viewer');throw Object.assign(new Error('编辑权限已变化'),{code:'EDIT_ACCESS_REVOKED',familyId:'f'});};await p.preview();assert.equal(p.data.writable,false);assert.equal(p.data.ready,false);assert.equal(p.data.garment,null);assert.equal(p.data.latest,null);assert.equal(p.data.form.name,'');
});
test('cancelling the folded color picker restores its opening colors without saving the garment',()=>{
 const {p,requests}=harness('garment-edit');p.data.ready=true;p.data.writable=true;p.apply({name:'短袖',category:'top',colors:['white','blue'],owners:[{child_id:'a',fit:'fit'}]});p.openColors();assert.equal(p.data.colorSheet,true);p.colors({detail:{value:['red']}});assert.deepEqual(p.data.form.colors,['white','blue']);assert.deepEqual(p.data.colorDraft,['red']);p.cancelColors();assert.equal(p.data.colorSheet,false);assert.deepEqual(p.data.form.colors,['white','blue']);assert.equal(requests.length,0);
});
test('completing color selection changes only local input and an empty selection remains unknown',()=>{
 const {p,requests}=harness('garment-edit');p.data.ready=true;p.data.writable=true;p.apply({name:'短袖',category:'top',colors:['unknown'],owners:[{child_id:'a',fit:'fit'}]});p.openColors();p.colors({detail:{value:['red','blue']}});p.completeColors();assert.deepEqual(p.data.form.colors,['red','blue']);assert.equal(p.data.colorSummary,'红、蓝');assert.equal(p.data.colorSheet,false);assert.equal(requests.length,0);p.openColors();p.colors({detail:{value:[]}});p.completeColors();assert.deepEqual(p.data.form.colors,['unknown']);assert.equal(p.data.colorSummary,'暂不清楚');
});
test('busy and viewer editors cannot open colors and a revoked color panel cannot restore stale input',()=>{
 const {p}=harness('garment-edit');p.data.ready=true;p.data.writable=true;p.data.busy=true;p.openColors();assert.equal(p.data.colorSheet,false);p.data.busy=false;p.data.writable=false;p.openColors();assert.equal(p.data.colorSheet,false);p.data.writable=true;p.openColors();p.onEditRevoked();p.cancelColors();p.completeColors();assert.equal(p.data.colorSheet,false);assert.deepEqual(p.data.form.colors,[]);
});
test('native B flow pages use the platform navigation and render the reviewed fit and original-image actions',()=>{
 for(const name of ['intake','intake-confirm','garment-edit']){const markup=fs.readFileSync(path.resolve(__dirname,'../pages',name,name+'.wxml'),'utf8');assert.doesNotMatch(markup,/class="b-top"/);}
 const confirmation=fs.readFileSync(path.resolve(__dirname,'../pages/intake-confirm/intake-confirm.wxml'),'utf8');assert.match(confirmation,/fitLabel/);assert.match(confirmation,/继续处理这批衣物/);
 const fields=fs.readFileSync(path.resolve(__dirname,'../pages/garment-edit/garment-edit.wxml'),'utf8');assert.match(fields,/查看完整原图/);
});
