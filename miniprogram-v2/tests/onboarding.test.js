const {test}=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const {storage}=require('./helpers');

function page(name){
 const root=path.resolve(__dirname,'..');
 for(const key of Object.keys(require.cache))if(key.startsWith(root+'/services/') || key.startsWith(root+'/pages/'))delete require.cache[key];
 const wx=storage(),requests=[],routes=[];
 Object.assign(wx,{request:o=>requests.push(o),login:o=>o.success({code:'live-code'}),reLaunch:o=>routes.push(o.url),
  navigateBack:()=>{},navigateTo:o=>routes.push(o.url),getLocation:o=>o.success({latitude:31.23,longitude:121.47})});
 global.wx=wx;let definition;global.Page=d=>definition=d;require('../pages/'+name+'/'+name);delete global.Page;
 const instance={...definition,data:structuredClone(definition.data),setData(patch){for(const [key,value] of Object.entries(patch)){
  const parts=key.split('.');let target=this.data;for(const part of parts.slice(0,-1))target=target[part];target[parts.at(-1)]=value;
 }}};
 return {instance,wx,requests,routes,reply(data,statusCode=200){assert.ok(requests.length);requests.shift().success({data,statusCode});},
  runtime:require('../services/runtime').getRuntime()};
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));

test('first-child draft survives login cancellation and resumes save',async()=>{
 const h=page('onboarding'),p=h.instance;p.onLoad();
 await p.start();assert.match(p.data.error,/年龄/);
 p.yearChange({detail:{value:'2'}});p.nicknameInput({detail:{value:'小豆'}});
 await p.start();assert.equal(p.data.loginSheet,true);
 p.closeLogin();assert.equal(p.data.loginSheet,false);
 assert.equal(h.wx.getStorageSync('v2:first-child-draft').nickname,'小豆');
 await p.start();const login=p.loginAndSave();
 await tick();assert.ok(h.requests[0].url.endsWith('/auth/wechat-login'));
 h.reply({token:'token',user:{id:'1',nickname:'家长'}});await tick();
 assert.ok(h.requests[0].url.endsWith('/onboarding/child'));
 assert.deepEqual(h.requests[0].data,{nickname:'小豆',age_months:24,styles:[]});
 h.reply({family:{id:'10'},child:{id:'20',nickname:'小豆'}},201);await login;
 assert.equal(h.runtime.session.read('10','child'),'20');
 assert.equal(h.wx.getStorageSync('v2:first-child-draft'),undefined);
 assert.equal(h.routes.at(-1),'/pages/home/home');
});
test('failed first-use login keeps the draft and shows the error inside the sheet',async()=>{
 const h=page('onboarding'),p=h.instance;p.onLoad();
 p.yearChange({detail:{value:'2'}});p.nicknameInput({detail:{value:'小豆'}});
 await p.start();assert.equal(p.data.loginSheet,true);
 h.wx.login=o=>o.fail({});
 await p.loginAndSave();
 assert.equal(p.data.loginSheet,true);
 assert.match(p.data.loginError,/登录失败/);
 assert.equal(h.wx.getStorageSync('v2:first-child-draft').nickname,'小豆');
});

test('home uses authorized target day forecast and never substitutes a fake temperature',async()=>{
 const h=page('home');h.runtime.session.set({token:'t',user:{id:'1'}});h.runtime.session.write('_','family','10');h.runtime.session.write('10','child','20');h.runtime.context.select({familyId:'10',childId:'20'});h.runtime.session.capability('10','viewer');h.instance.familyId='10';
 const pending=h.instance.loadWeather();await tick();
 assert.ok(h.requests[0].url.includes('/families/10/outfits/context?'));assert.ok(h.requests[0].url.includes('date_mode=today'));assert.ok(h.requests[0].url.includes('lat=31.23'));
 h.reply({target_date:'2026-10-03',today:'2026-10-03',timezone:'Asia/Shanghai',role:'viewer',weather:{status:'unknown'},plans:[],suggestion:null});await pending;
 assert.equal(h.instance.data.weather.status,'unknown');assert.equal(h.instance.data.weather.temp_max,undefined);
 assert.match(h.instance.data.weatherMessage,/未知/);
});

test('revoked family clears the home child display',async()=>{
 const h=page('home');h.runtime.session.set({token:'t',user:{id:'1'}});
 h.runtime.session.write('_','family','10');h.runtime.context.select({familyId:'10',childId:'20'});
 h.instance.setData({child:{id:'20',nickname:'Private'},children:[{id:'20'}]});
 const pending=h.instance.reload();
 h.reply({error:{code:'NOT_FOUND',message:'missing'}},404);await pending;
 assert.equal(h.instance.data.child,null);
 assert.deepEqual(h.instance.data.children,[]);
 assert.equal(h.instance.data.accessRevoked,true);
 assert.equal(h.runtime.session.read('_','family'),undefined);
});
test('old weather response cannot overwrite a newly selected family',async()=>{
 const h=page('home');h.runtime.session.set({token:'t',user:{id:'1'}});
 h.runtime.session.write('_','family','10');h.runtime.session.write('10','child','20');h.runtime.session.capability('10','viewer');h.instance.familyId='10';h.runtime.context.select({familyId:'10',childId:'20'});
 const pending=h.instance.loadWeather();await tick();
 require('../services/page').selectFamily('30');
 h.instance.setData({weatherMessage:'新家庭天气',locationLabel:'新城市'});
 h.reply({city:'旧城市',temp:20,weather:'晴',humidity:50});await pending;
 assert.equal(h.instance.data.weatherMessage,'新家庭天气');
 assert.equal(h.instance.data.locationLabel,'新城市');
 assert.equal(h.instance.data.weather,null);
});
test('home loads viewer role without fetching weather for an empty family',async()=>{
 const h=page('home');h.runtime.session.set({token:'t',user:{id:'1'}});
 h.runtime.session.write('_','family','10');h.runtime.context.select({familyId:'10',childId:null});
 const pending=h.instance.reload();
 h.reply({id:'10',name:'外婆的小院'});await tick();
 h.reply([]);await tick();
 assert.ok(h.requests[0].url.endsWith('/members'));
 h.reply([{id:'m',user_id:'1',role:'viewer',status:'active'}]);await pending;
 assert.equal(h.instance.data.role,'viewer');
 assert.equal(h.instance.data.child,null);
 assert.equal(h.requests.length,0);
});
test('home child switch sheet selects a stable child id',()=>{
 const h=page('home');h.runtime.session.set({token:'t',user:{id:'1'}});
 h.runtime.session.write('_','family','10');h.runtime.context.select({familyId:'10',childId:'20'});
 h.instance.setData({ready:true,role:'admin',child:{id:'20'},children:[{id:'20',nickname:'豆豆'},{id:'21',nickname:'小花'}]});
 h.instance.openChildSwitch();assert.equal(h.instance.data.switchSheet,true);
 h.instance.choose({currentTarget:{dataset:{id:'21'}}});
 assert.equal(h.instance.data.switchSheet,false);
 assert.equal(h.instance.data.child.id,'21');
 assert.equal(h.runtime.session.read('10','child'),'21');
});
