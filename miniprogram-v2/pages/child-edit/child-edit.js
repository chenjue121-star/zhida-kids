const {getRuntime}=require('../../services/runtime');
const {definePage,navigate,requireLogin,selectFamily,selectChild,confirmation,membership}=require('../../services/page');
const {styles,measurement,childPayload,ageMonths,ageValue}=require('../../services/forms');
const ageText=(years,months)=>years==null || months==null?'年龄待完善':years+'岁'+months+'个月';
Page(definePage({
  data:{
    childId:null,role:null,version:null,styleOptions:styles,selectedStyles:[],
    years:[0,1,2,3,4,5,6],months:[0,1,2,3,4,5,6,7,8,9,10,11],ageYearIndex:-1,ageMonthIndex:-1,hasBirthday:false,ageChanged:false,
    skinOptions:[{key:'',label:'未知 / 暂不填写'},{key:'light',label:'浅肤色'},{key:'medium',label:'中等肤色'},{key:'deep',label:'深肤色'}],
    skinIndex:0,form:{nickname:'宝贝',birthday:'',skin_tone:'',height_cm:'',weight_kg:'',measured_on:'',age_years:'',age_extra_months:''},
    latestMeasurement:null,measurementSaved:false,measurementOpen:false,childInitial:'宝',ageLabel:'年龄待完善',conflictSheet:false,archiveSheet:false
  },
  onLoad(options) {
    this.childId=options.id || null;
    this.familyId=getRuntime().session.read('_','family');
    this.setData({childId:this.childId});
    if(wx.setNavigationBarTitle)wx.setNavigationBarTitle({title:this.childId?'编辑宝贝':'添加宝贝'});
  },
  onShow() {
    this._visible=true;this.setData({busy:false});
    if(!requireLogin())return;
    const {session}=getRuntime();
    if(!this.familyId || session.read('_','family')!==this.familyId)return navigate('families','',true);
    const owner=session.user().id+':'+this.familyId;
    if(this.owner && this.owner!==owner)return navigate('families','',true);
    this.owner=owner;selectFamily(this.familyId);
    if(!this.data.ready)this.reload();
  },
  path() { return '/families/'+encodeURIComponent(this.familyId)+'/children'+(this.childId?'/'+encodeURIComponent(this.childId):''); },
  reload() {
    this.setData({ready:false});
    return this.run(async valid=>{
      const info=await membership(this.familyId);
      const child=this.childId ? await getRuntime().api.request(this.path()) : null;
      if(!valid())return;
      const patch={role:info.role,ready:true};
      if(child) {
        patch.version=child.version;patch.childInitial=(child.nickname || '宝').slice(0,1);
        const age=ageValue(child);
        patch.ageLabel=age===null?'年龄待完善':ageText(Math.floor(age/12),age%12);
        patch.form={nickname:child.nickname,birthday:child.birthday || '',skin_tone:child.skin_tone || '',height_cm:'',weight_kg:'',measured_on:'',
          age_years:age===null?'':Math.floor(age/12),age_extra_months:age===null?'':age%12};
        patch.ageYearIndex=age===null?-1:Math.min(6,Math.floor(age/12));
        patch.ageMonthIndex=age===null?-1:age%12;
        patch.hasBirthday=!!child.birthday;patch.ageChanged=false;
        patch.skinIndex=this.data.skinOptions.findIndex(o=>o.key===(child.skin_tone || ''));
        patch.latestMeasurement=child.latest_measurement ? {
          ...child.latest_measurement,
          heightLabel:child.latest_measurement.height_cm==null?'未知':child.latest_measurement.height_cm+' cm',
          weightLabel:child.latest_measurement.weight_kg==null?'未知':child.latest_measurement.weight_kg+' kg'
        }:null;
      }
      this.setData({...patch,measurementOpen:false,conflictSheet:false,archiveSheet:false});
    });
  },
  async reloadConfirm() {
    if(await confirmation('重新加载','将丢弃未保存的填写，获取最新孩子资料。'))this.reload();
  },
  skin(e) {const index=Number(e.detail.value);this.setData({skinIndex:index,'form.skin_tone':this.data.skinOptions[index].key});},
  nicknameInput(e){const name=e.detail.value;this.setData({'form.nickname':name,childInitial:(name || '宝').slice(0,1)});},
  ageYear(e){const index=Number(e.detail.value);this.setData({ageYearIndex:index,ageMonthIndex:this.data.ageMonthIndex<0?0:this.data.ageMonthIndex,
    'form.age_years':this.data.years[index],'form.age_extra_months':this.data.ageMonthIndex<0?0:this.data.months[this.data.ageMonthIndex],
    ageLabel:ageText(this.data.years[index],this.data.ageMonthIndex<0?0:this.data.months[this.data.ageMonthIndex]),ageChanged:true});},
  ageMonth(e){const index=Number(e.detail.value);this.setData({ageMonthIndex:index,'form.age_extra_months':this.data.months[index],
    ageLabel:ageText(this.data.ageYearIndex<0?null:this.data.years[this.data.ageYearIndex],this.data.months[index]),ageChanged:true});},
  toggleMeasurement(){if(this.childId && this.data.ready && ['admin','editor'].includes(this.data.role))this.setData({measurementOpen:!this.data.measurementOpen});},
  styles(e) {const selected=e.detail.value;this.setData({selectedStyles:selected,styleOptions:styles.map(s=>({...s,checked:selected.includes(s.key)}))});},
  noStyles() {this.setData({selectedStyles:[],styleOptions:styles.map(s=>({...s,checked:false}))});},
  async save() {
    if(!this.data.ready || !['admin','editor'].includes(this.data.role))return;
    await this.run(async valid=>{
      const {api,session}=getRuntime();
      const form=this.data.form;
      if(!form.nickname.trim())throw new Error('请填写昵称');
      if(this.childId) {
        const payload={nickname:form.nickname.trim(),skin_tone:form.skin_tone || null,expected_version:this.data.version};
        if(form.birthday)payload.birthday=form.birthday;
        else if(this.data.ageChanged)payload.age_months=ageMonths(form.age_years,form.age_extra_months);
        const child=await api.request(this.path(),{method:'PUT',data:payload});
        if(valid()){this.setData({version:child.version,childInitial:child.nickname.slice(0,1)});wx.showToast({title:'资料已保存',icon:'success'});}
      } else {
        const payload=childPayload(form,this.data.selectedStyles);
        const result=await api.request(this.path(),{method:'POST',data:payload,idempotencyKey:session.mutationKey(this.familyId,'create-child',payload)});
        if(!valid())return;
        session.completeMutation(this.familyId,'create-child');
        selectChild(result.id);wx.reLaunch({url:'/pages/home/home'});
      }
    },true);
    if(this.data.conflict)this.setData({conflictSheet:true});
  },
  saveMeasurement() {
    if(!this.childId || !this.data.ready || !['admin','editor'].includes(this.data.role))return;
    return this.run(async valid=>{
      const payload=measurement(this.data.form);
      if(!payload)throw new Error('请至少填写一项测量数据');
      const {api,session}=getRuntime();const op='measurement:'+this.childId;
      await api.request(this.path()+'/measurements',{method:'POST',data:payload,
        idempotencyKey:session.mutationKey(this.familyId,op,payload)});
      if(!valid())return;
      session.completeMutation(this.familyId,op);
      this.setData({measurementSaved:true,'form.height_cm':'','form.weight_kg':'','form.measured_on':''});
      const child=await api.request(this.path());
      if(!valid())return;
      const latest=child.latest_measurement;
      this.setData({latestMeasurement:latest ? {
        ...latest,heightLabel:latest.height_cm==null?'未知':latest.height_cm+' cm',
        weightLabel:latest.weight_kg==null?'未知':latest.weight_kg+' kg'
      }:null,measurementOpen:false});
      wx.showToast({title:'测量已保存',icon:'success'});
    },true);
  },
  preferences() {if(this.childId)navigate('preferences','?id='+encodeURIComponent(this.childId));},
  closeConflict(){this.setData({conflictSheet:false});},
  closeArchive(){if(!this.data.busy)this.setData({archiveSheet:false});},
  noop(){},
  archive() {
    if(!this.childId || !this.data.ready || !['admin','editor'].includes(this.data.role) || this.data.busy || this.data.conflict)return;
    this.setData({archiveSheet:true});
  },
  async confirmArchive() {
    if(!this.data.archiveSheet || !this.childId || !this.data.ready || !['admin','editor'].includes(this.data.role) || this.data.busy)return;
    await this.run(async valid=>{
      await getRuntime().api.request(this.path()+'?expected_version='+this.data.version,{method:'DELETE'});
      if(!valid())return;
      const {session}=getRuntime();session.remove(this.familyId,'child');session.remove(this.familyId,'children');
      this.setData({archiveSheet:false});wx.reLaunch({url:'/pages/home/home'});
    },true);
    if(this.data.conflict)this.setData({archiveSheet:false,conflictSheet:true});
    else if(this.data.error)this.setData({archiveSheet:false});
  }
}));
