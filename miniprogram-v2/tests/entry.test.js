const {test}=require('node:test');
const assert=require('node:assert/strict');
const {resolveEntry}=require('../services/entry');

test('new account stays in simplified onboarding',async()=>{
 const result=await resolveEntry({session:{pending:()=>null,token:()=> 't',read:()=>null,write:()=>{}},
  api:{request:async path=>path==='/me'?{families:[]}:[]},context:{select:()=>{}}});
 assert.equal(result,'onboarding');
});
test('existing child restores stable family and child ids',async()=>{
 const writes=[];const selected=[];
 const runtime={session:{pending:()=>null,token:()=> 't',read:()=>null,write:(...args)=>writes.push(args)},
  api:{request:async path=>path==='/me'?{families:[{id:'10'}]}:[{id:'20',nickname:'宝贝'}]},
  context:{select:v=>selected.push(v)}};
 assert.equal(await resolveEntry(runtime),'home');
 assert.deepEqual(selected.at(-1),{familyId:'10',childId:'20'});
 assert.deepEqual(writes.at(-1),['10','child','20']);
});
test('invitation takes priority over first-child flow',async()=>{
 const result=await resolveEntry({session:{pending:()=> 'invite',token:()=> 't'}});
 assert.equal(result,'invitation');
});
test('fresh device skips empty family to show an existing child',async()=>{
 const selected=[];
 const runtime={session:{pending:()=>null,token:()=> 't',read:()=>null,write:()=>{}},
  api:{request:async path=>path==='/me'?{families:[{id:'10'},{id:'11'}]}:path.includes('/10/')?[]:[{id:'child-1'}]},
  context:{select:value=>selected.push(value)}};
 assert.equal(await resolveEntry(runtime),'home');
 assert.deepEqual(selected.at(-1),{familyId:'11',childId:'child-1'});
});
test('accessible family with no child opens the role-aware home empty state',async()=>{
 const selected=[];const writes=[];
 const runtime={session:{pending:()=>null,token:()=> 't',read:()=>null,write:(...args)=>writes.push(args),remove:()=>{}},
  api:{request:async path=>path==='/me'?{families:[{id:'10'}]}:[]},
  context:{select:value=>selected.push(value)}};
 assert.equal(await resolveEntry(runtime),'home');
 assert.deepEqual(selected.at(-1),{familyId:'10',childId:null});
 assert.deepEqual(writes.find(entry=>entry[1]==='children'),['10','children',[]]);
});
