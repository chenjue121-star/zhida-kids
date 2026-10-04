const {getRuntime}=require('../../services/runtime');
const {definePage}=require('../../services/page');
const {styles,ageMonths}=require('../../services/forms');
const {resolveEntry}=require('../../services/entry');

const DRAFT='v2:first-child-draft';
function go(name) {wx.reLaunch({url:'/pages/'+name+'/'+name});}
function wxCode() {return new Promise((resolve,reject)=>wx.login({
  success:r=>r.code?resolve(r.code):reject(new Error('微信登录未完成，请重试')),
  fail:()=>reject(new Error('微信登录失败，请重试'))
}));}

Page(definePage({
  data:{nickname:'宝贝',yearIndex:-1,monthIndex:-1,years:[0,1,2,3,4,5,6],months:[0,1,2,3,4,5,6,7,8,9,10,11],
    selectedStyles:[],styleOptions:styles,loginSheet:false,loginError:''},
  onLoad(){
    const draft=wx.getStorageSync(DRAFT);
    if(draft)this.setData({nickname:draft.nickname || '宝贝',yearIndex:draft.yearIndex,
      monthIndex:draft.monthIndex,selectedStyles:draft.selectedStyles || [],
      styleOptions:styles.map(s=>({...s,selected:(draft.selectedStyles || []).includes(s.key)}))});
  },
  onShow(){
    this._visible=true;
    const runtime=getRuntime();
    if(runtime.session.pending())return go(runtime.session.token()?'invitation':'login');
    if(runtime.session.token())this.resume();
  },
  async resume(){
    this.setData({loading:true,error:''});
    try{const target=await resolveEntry(getRuntime());if(target!=='onboarding')go(target);}
    catch(e){this.setData({error:e.message || '读取资料失败，请重试'});}
    finally{this.setData({loading:false});}
  },
  nicknameInput(e){this.setData({nickname:e.detail.value});this.remember();},
  yearChange(e){this.setData({yearIndex:Number(e.detail.value),monthIndex:this.data.monthIndex<0?0:this.data.monthIndex});this.remember();},
  monthChange(e){this.setData({monthIndex:Number(e.detail.value)});this.remember();},
  chooseStyle(e){
    const key=e.currentTarget.dataset.key;
    const chosen=this.data.selectedStyles.includes(key)?this.data.selectedStyles.filter(s=>s!==key):[...this.data.selectedStyles,key];
    this.setData({selectedStyles:chosen,styleOptions:styles.map(s=>({...s,selected:chosen.includes(s.key)}))});this.remember();
  },
  chooseForMe(){
    this.setData({selectedStyles:[],styleOptions:styles.map(s=>({...s,selected:false}))});this.remember();
  },
  remember(){wx.setStorageSync(DRAFT,{nickname:this.data.nickname,yearIndex:this.data.yearIndex,
    monthIndex:this.data.monthIndex,selectedStyles:this.data.selectedStyles});},
  async start(){
    if(this.data.busy)return;
    try{ageMonths(this.data.yearIndex<0?'':this.data.years[this.data.yearIndex],
      this.data.monthIndex<0?'':this.data.months[this.data.monthIndex]);}
    catch(e){this.setData({error:e.message});return;}
    this.remember();this.setData({error:''});
    if(!getRuntime().session.token())return this.setData({loginSheet:true,loginError:''});
    return this.saveFirst();
  },
  closeLogin(){if(!this.data.busy)this.setData({loginSheet:false,loginError:''});},
  noop(){},
  async loginAndSave(){
    if(this.data.busy)return;
    this.setData({busy:true,error:'',loginError:''});
    try{
      const runtime=getRuntime();const generation=runtime.session.generation();
      const code=await wxCode();
      const identity=await runtime.api.request('/auth/wechat-login',{method:'POST',public:true,data:{code}});
      if(generation!==runtime.session.generation())return;
      runtime.session.set(identity);
      this.setData({loginSheet:false});
    }catch(e){this.setData({loginError:e.message || '登录失败，请重试'});return;}
    finally{this.setData({busy:false});}
    return this.saveFirst();
  },
  async saveFirst(){
    if(this.data.busy)return;
    this.setData({busy:true,error:''});
    const runtime=getRuntime();
    const payload={nickname:this.data.nickname.trim() || '宝贝',
      age_months:ageMonths(this.data.years[this.data.yearIndex],this.data.months[this.data.monthIndex]),
      styles:this.data.selectedStyles};
    try{
      const key=runtime.session.mutationKey('_','first-child',payload);
      const result=await runtime.api.request('/onboarding/child',{method:'POST',data:payload,idempotencyKey:key});
      runtime.session.completeMutation('_','first-child');
      runtime.session.write('_','family',result.family.id);
      runtime.session.write(result.family.id,'child',result.child.id);
      runtime.session.write(result.family.id,'children',[result.child]);
      runtime.context.select({familyId:result.family.id,childId:result.child.id});
      wx.removeStorageSync(DRAFT);go('home');
    }catch(e){
      if(e.code==='CHILD_EXISTS')return this.resume();
      this.setData({error:e.message || '保存失败，请重试'});
    }finally{this.setData({busy:false});}
  }
}));
