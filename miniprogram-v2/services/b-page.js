const {getRuntime}=require('./runtime');
const {membership,selectFamily,navigate}=require('./page');
async function workspace(page,valid,{edit=false}={}){
 const rt=getRuntime(),f=page.familyId || rt.session.read('_','family');
 if(!f){navigate('families');return null;}page.familyId=f;
 const info=await membership(f);if(!valid())return null;
 rt.session.capability(f,info.role);
 page.setData({role:info.role,writable:['admin','editor'].includes(info.role)});
 if(edit && !rt.session.canEdit(f))throw Object.assign(new Error('当前仅可查看衣橱，待确认草稿暂不可访问。'),{code:'EDIT_ACCESS_REVOKED',familyId:f});
 const children=await rt.api.request('/families/'+encodeURIComponent(f)+'/children');if(!valid())return null;
 rt.session.write(f,'children',children);
 page.setData({children});return {rt,f,children,role:info.role};
}
function bind(page){const rt=getRuntime();if(!rt.session.token()){wx.reLaunch({url:'/pages/login/login'});return false;}const fid=rt.session.read('_','family');if(!fid || page.familyId && page.familyId!==fid || page.owner && page.owner!==rt.session.user().id+':'+fid){navigate('families','',true);return false;}page.familyId=fid;page.owner=rt.session.user().id+':'+fid;selectFamily(fid);return true;}
module.exports={workspace,bind};
