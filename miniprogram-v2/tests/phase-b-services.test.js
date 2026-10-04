const {test}=require('node:test');
const assert=require('node:assert/strict');
const {storage}=require('./helpers');
const {createContextStore}=require('../stores/context');
const {createSession}=require('../services/session');
function setup(){const platform=storage(),context=createContextStore(),session=createSession(platform,context);session.set({token:'t',user:{id:'u'}});context.select({familyId:'f',childId:'a'});return {platform,context,session};}
test('editing scope invalidates late success on permission downgrade without clearing other families',async()=>{
 const {platform,context,session}=setup();const calls=[];platform.request=o=>calls.push(o);
 const {createApi}=require('../services/api');const api=createApi(platform,session,context);
 session.capability('f','editor');session.write('other','draft',{safe:true});
 const pending=api.request('/families/f/intake/batches/b',{editScope:true});
 session.capability('f','viewer');calls[0].success({statusCode:200,data:{secret:true}});
 await assert.rejects(pending,e=>e.code==='STALE');assert.deepEqual(session.read('other','draft'),{safe:true});
 await assert.rejects(api.request('/families/f/intake/batches/b',{editScope:true}),e=>e.code==='EDIT_ACCESS_REVOKED');
});
test('local media files are cleaned for exactly the family removed and on account switch',()=>{
 const {platform,session}=setup();const removed=[];platform.removeSavedFile=o=>removed.push(o.filePath);
 session.write('f','media-files',['/private/a']);session.write('other','media-files',['/private/b']);
 session.clearFamily('f');assert.deepEqual(removed,['/private/a']);assert.deepEqual(session.read('other','media-files'),['/private/b']);
 session.set({token:'n',user:{id:'new'}});assert.deepEqual(removed,['/private/a','/private/b']);
});
test('candidate selection counts confirmed once and bulk ownership preserves individual exceptions',()=>{
 const {bulkOwners,selectedCandidates}=require('../services/garment-forms');
 const candidates=[{id:'a',selected:true,owners:[{child_id:'old',fit:'small'}],ownership_exception:true},{id:'b',selected:true,state:'washing',owners:[{child_id:'old',fit:'fit'}]},{id:'c',selected:false,owners:[]}];
 const result=bulkOwners(candidates,'new','unknown');assert.deepEqual(result[0].owners,candidates[0].owners);assert.deepEqual(result[1].owners,[{child_id:'new',fit:'unknown'}]);assert.equal(result[1].state,'washing');assert.deepEqual(result[2].owners,[]);
 assert.equal(selectedCandidates([...candidates,{id:'d',selected:true,confirmed_garment_id:'1'}]).length,2);
});
test('lost confirmation result queries same persisted operation and never resubmits unknown',async()=>{
 const {session}=setup();session.capability('f','editor');const calls=[];let fail=true;
 const api={request:async(path,o={})=>{calls.push({path,o});if(o.method==='POST' && fail)throw Object.assign(new Error('lost'),{code:'NETWORK'});return {operation_id:'x',status:'unknown'};}};
 const {createIntake}=require('../services/intake');const intake=createIntake(api,session);
 await assert.rejects(intake.confirm('f','b',[{candidate_id:'c',expected_version:1,action:'new'}]),e=>e.code==='RESULT_UNKNOWN');
 const original=calls[0].o.data.operation_id;
 await assert.rejects(intake.confirm('f','b',[{candidate_id:'c',expected_version:1,action:'new'}]),e=>e.code==='RESULT_UNKNOWN');
 assert.equal(calls.filter(x=>x.o.method==='POST').length,1);assert.ok(calls[1].path.endsWith('/operations/'+original));
});
test('explicit completed partial result retries failed candidates only with a new operation',async()=>{
 const {session}=setup();session.capability('f','editor');const calls=[];
 const api={request:async(path,o)=>{calls.push({path,o});return {status:'completed',results:[{candidate_id:'a',status:'success'},{candidate_id:'b',status:'failed',error:{code:'VALIDATION_ERROR'}}]};}};
 const intake=require('../services/intake').createIntake(api,session);
 const entries=[{candidate_id:'a',expected_version:1,action:'new'},{candidate_id:'b',expected_version:2,action:'new'}];
 await intake.confirm('f','b',entries);await intake.retryFailed('f','b',entries);
 assert.deepEqual(calls[1].o.data.entries,[entries[1]]);assert.notEqual(calls[0].o.data.operation_id,calls[1].o.data.operation_id);
});
test('lost single restore queries its operation and resolve uses the original payload',async()=>{
 const {session}=setup();session.capability('f','editor');const calls=[];
 const api={request:async(path,o={})=>{calls.push({path,o});if(path.endsWith('/restore'))throw Object.assign(new Error('lost'),{code:'NETWORK'});if(path.endsWith('/resolve'))return {status:'completed',results:[{status:'failed',error:{code:'NOT_EXECUTED',message:'已核实未执行'}}]};return {status:'unknown'};}};
 const wardrobe=require('../services/wardrobe').createWardrobe(api,session),payload={expected_version:4,owners:[{child_id:'a',fit:'unknown'}]};
 await assert.rejects(wardrobe.action('f','g','restore',payload),e=>e.code==='RESULT_UNKNOWN');
 await assert.rejects(wardrobe.action('f','g','restore',payload),e=>e.code==='RESULT_UNKNOWN');
 assert.equal(calls.filter(c=>c.path.endsWith('/restore')).length,1);
 const operation=calls[0].o.data.operation_id;await wardrobe.resolveAction('f','g','restore');
 assert.equal(calls.at(-1).o.data.operation_id,operation);assert.equal(calls.at(-1).o.data.expected_version,4);
});
test('photo capture does not claim durable saving when saveFile fails and raw upload stays scoped',async()=>{
 const {platform,session,context}=setup();session.capability('f','editor');
 platform.chooseMedia=o=>o.success({tempFiles:[{tempFilePath:'/temp/photo'}]});platform.saveFile=o=>o.fail({errMsg:'quota'});
 const bytes=new Uint8Array([255,216,255,0]).buffer;platform.getFileSystemManager=()=>({readFile:o=>o.success({data:bytes})});
 const calls=[],api={request:async(path,options)=>{calls.push({path,options});return {asset_id:'asset',status:'queued'};}};
 const media=require('../services/media').createMedia(platform,api,session,context);const photos=await media.choose('f','camera');
 assert.equal(photos[0].local_saved,false);assert.ok(photos[0].error.includes('丢失'));assert.equal(session.read('f','media-files'),undefined);
 await media.upload('f','b','i',photos[0].local_path);assert.equal(calls[0].options.method,'PUT');assert.equal(calls[0].options.headers['Content-Type'],'image/jpeg');assert.equal(calls[0].options.editScope,true);
});
test('late private download after account switch is deleted and never reused',async()=>{
 const {platform,session,context}=setup();session.capability('f','editor');let reply;const deleted=[];
 platform.downloadFile=o=>reply=o;platform.getFileSystemManager=()=>({unlink:o=>deleted.push(o.filePath)});
 const media=require('../services/media').createMedia(platform,{},session,context);const pending=media.image('f','a',{draft:true});
 session.set({token:'new',user:{id:'new'}});reply.success({statusCode:200,tempFilePath:'/temp/private'});
 await assert.rejects(pending,e=>e.code==='STALE');assert.deepEqual(deleted,['/temp/private']);assert.equal(session.read('f','media-tempfiles'),undefined);
});
test('a single-operation query never turns into a write when its pending receipt is already cleared',async()=>{
 const {session}=setup();session.capability('f','editor');const calls=[];const api={request:async(path,o={})=>{calls.push({path,o});throw new Error('must not request a new write');}};
 const wardrobe=require('../services/wardrobe').createWardrobe(api,session);const result=await wardrobe.queryAction('f','g','archive');assert.equal(result.status,'not_pending');assert.equal(calls.length,0);
});
