// Shipped native services call real isolated HTTP; only wx.request is bridged.
const assert=require('node:assert/strict');
const {storage}=require('./helpers');
const {createContextStore}=require('../stores/context');
const {createSession}=require('../services/session');
const {createApi}=require('../services/api');
const {createOutfits}=require('../services/outfits');
const {createPlans}=require('../services/plans');
const {createOutfitStore}=require('../stores/outfit-context');
const {createIntake}=require('../services/intake');

async function main(){
 const endpoint=process.argv[2];assert.ok(endpoint);
 const platform=storage(),context=createContextStore(),session=createSession(platform,context);
 let loseCancel=false,cancelSubmissions=0;
 platform.reLaunch=()=>{};
 platform.request=options=>{
  const url=endpoint+options.url.slice(options.url.indexOf('/v2')+3);
  const cancellation=options.method==='POST' && /\/plans\/[^/]+\/cancel$/.test(url);
  if(cancellation)cancelSubmissions++;
  fetch(url,{method:options.method,headers:options.header,body:options.method==='GET'?undefined:JSON.stringify(options.data)})
   .then(async response=>{const data=await response.json();
    if(cancellation && loseCancel && response.ok){loseCancel=false;options.fail({});}
    else options.success({statusCode:response.status,data});
   }).catch(options.fail);
 };
 const api=createApi(platform,session,context),outfits=createOutfits(api,session,context);
 const plans=createPlans(api,session,context),store=createOutfitStore(session,context),intake=createIntake(api,session);
 const login=await api.request('/auth/wechat-login',{method:'POST',public:true,data:{code:'phase-d-contract'}});
 session.set(login);
 const family=await api.request('/families',{method:'POST',data:{name:'D isolated contract',city:'Shanghai'},idempotencyKey:'d-family'}),fid=family.id;
 context.select({familyId:fid,childId:null});session.capability(fid,'admin');
 const child=await api.request('/families/'+fid+'/children',{method:'POST',data:{nickname:'D固定样例',age_months:24},idempotencyKey:'d-child'}),cid=child.id;
 context.select({familyId:fid,childId:cid});session.write('_','family',fid);session.write(fid,'child',cid);
 const batch=await intake.create(fid,cid);
 for(const [index,category] of ['top','bottom','top','bottom'].entries()){
  const item=await intake.item(fid,batch.id,{client_id:'d-manual-'+index,source:'manual'});
  const candidate=await intake.candidate(fid,batch.id,{item_id:item.id,client_id:'d-piece-'+index,name:'D实物'+index,
   category,colors:['white'],pattern:'solid',thickness:'medium',state:'ready',owners:[{child_id:cid,fit:'fit'}],selected:true});
  await intake.confirm(fid,batch.id,[{candidate_id:candidate.id,expected_version:candidate.version,action:'new'}]);
 }
 const daily=await outfits.context(fid,{child_id:cid,date_mode:'today'});store.open(fid,cid,daily.target_date);
 const ticket=store.requestTicket(),suggestion=await outfits.recommend(fid,{...store.payload(),request_id:ticket.request_id});
 assert.equal(store.applyRecommendation(ticket,suggestion),true);
 store.patch({weather_acknowledged:true});
 let review=await outfits.review(fid,store.payload());assert.equal(review.valid,true);
 const first=await outfits.save(fid,{...store.payload(),input_version:review.input_version});
 store.beginEdit(first.plan,true);store.patch({weather_acknowledged:true});
 review=await outfits.review(fid,store.payload());
 const second=await outfits.save(fid,{...store.payload(),input_version:review.input_version});
 const day=daily.target_date;
 let calendar=await plans.calendar(fid,{start_date:day,end_date:day,child_id:cid,include_cancelled:true});
 assert.deepEqual(calendar.plans.map(plan=>plan.sequence),[1,2]);
 const original=await plans.detail(fid,second.plan.id);assert.equal(original.status,'selected');
 assert.ok(!('wear_count' in original));
 const feedback={event_id:'d-like-attempt',plan_id:original.id,plan_version:original.version,signal:'like',reason:'aesthetic',styles:['clean_daily']};
 const stated=await plans.feedback(fid,cid,feedback),replayed=await plans.feedback(fid,cid,feedback);
 assert.equal(stated.event.event_id,replayed.event.event_id);assert.equal(stated.target,'family');
 const profilePath='/families/'+fid+'/children/'+cid+'/profiles/family';
 const beforeTemporary=await api.request(profilePath);
 await plans.feedback(fid,cid,{...feedback,event_id:'d-washing-attempt',signal:'dislike',reason:'washing'});
 const afterTemporary=await api.request(profilePath);
 assert.deepEqual(afterTemporary.inferred_tags,beforeTemporary.inferred_tags);
 assert.deepEqual(afterTemporary.effective_weights,beforeTemporary.effective_weights);
 const explicit=await api.request(profilePath,{method:'PUT',data:{expected_version:afterTemporary.version,styles:['clean_daily']},editScope:true});
 assert.ok(explicit.styles.includes('clean_daily'));
 const tomorrow=await outfits.context(fid,{child_id:cid,date_mode:'tomorrow'});
 const reuse=await plans.reuse(fid,original.id,{expected_source_version:original.version,child_id:cid,target_date:tomorrow.target_date,
  scene:'daily',draft_id:'d-reuse-draft',preference_mode:'family'});
 assert.equal(reuse.context.target_date,tomorrow.target_date);
 assert.equal(reuse.draft.target_plan_id==null,true);
 assert.deepEqual(reuse.draft.sharing_grants,[]);
 assert.equal((await plans.calendar(fid,{start_date:tomorrow.target_date,end_date:tomorrow.target_date,child_id:cid})).plans.length,0);
 const adopted=store.adoptReusedDraft(reuse,original,true);
 assert.equal(adopted.target_date,tomorrow.target_date);assert.notEqual(adopted.action_id,original.action_id);
 assert.equal(adopted.weather_acknowledged,false);
 store.patch({weather_acknowledged:true});review=await outfits.review(fid,store.payload());assert.equal(review.valid,true);
 const reused=await outfits.save(fid,{...store.payload(),input_version:review.input_version});
 assert.notEqual(reused.plan.id,original.id);assert.equal(reused.plan.target_date,tomorrow.target_date);
 assert.deepEqual((await plans.detail(fid,original.id)).main_items,original.main_items);
 loseCancel=true;
 await assert.rejects(plans.cancel(fid,first.plan.id,first.plan.version),error=>error.code==='RESULT_UNKNOWN');
 assert.ok(plans.pendingCancel(fid,first.plan.id));
 const cancelled=await plans.queryCancel(fid,first.plan.id);
 assert.equal(cancelled.plan.status,'cancelled');assert.equal(cancelSubmissions,1);
 assert.equal(plans.pendingCancel(fid,first.plan.id),null);
 calendar=await plans.calendar(fid,{start_date:day,end_date:day,child_id:cid});
 assert.equal(calendar.plans.length,1);assert.equal(calendar.plans[0].id,second.plan.id);
 calendar=await plans.calendar(fid,{start_date:day,end_date:day,child_id:cid,include_cancelled:true});
 assert.deepEqual(calendar.plans.map(plan=>plan.status),['cancelled','selected']);
 console.log(JSON.stringify({status:'passed',steps:'manual-intake,multiplan-calendar,detail,feedback-idempotency,temporary-isolation,explicit-profile,reuse-revalidation,new-selection,history-immutable,cancel-lost-response,query-only,cancelled-history',cancelSubmissions}));
}
main().catch(error=>{console.error(error.code || error.name,error.message);process.exitCode=1;});
