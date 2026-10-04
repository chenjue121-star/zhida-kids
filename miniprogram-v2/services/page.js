const { getRuntime } = require('./runtime');
const roles = { admin: '管理员', editor: '可编辑', viewer: '仅查看' };
function navigate(name, query = '', replace = false) {
  wx[replace ? 'redirectTo' : 'navigateTo']({ url: '/pages/' + name + '/' + name + query });
}
function requireLogin() {
  if (getRuntime().session.token()) return true;
  wx.reLaunch({ url: '/pages/login/login' }); return false;
}
function selectFamily(id) {
  const {session,context} = getRuntime();
  const current = context.capture().current;
  if (!current || current.familyId !== id) {
    context.select({ familyId: id, childId: session.read(id, 'child') || null });
  }
  session.write('_', 'family', id);
}
function selectChild(id) {
  const {session,context} = getRuntime(); const current = context.capture().current;
  context.select({ ...current, childId: id });
  session.write(current.familyId, 'child', id);
}
function confirmation(title, content) {
  const { session, context } = getRuntime();
  const generation = session.generation();
  const ticket = context.capture();
  return new Promise(resolve => wx.showModal({ title, content, confirmText: '确认', confirmColor: '#23734b',
    success: r => resolve(!!r.confirm && generation === session.generation() && context.isCurrent(ticket)),
    fail: () => resolve(false) }));
}
function definePage(definition) {
  const { data, ...methods } = definition;
  const result = {
    data: { loading: false, busy: false, error: '', conflict: false, cached: false, ready: false, accessRevoked: false, ...data },
    onHide() { this._visible = false; this._load = (this._load || 0) + 1; },
    onUnload() { this._visible = false; this._load = (this._load || 0) + 1; },
    handleAccessError(e, generation) {
      const runtime=getRuntime();
      if(generation!==runtime.session.generation() || this.familyId!==e.familyId)return false;
      if(e.code==='FAMILY_ACCESS_REVOKED' && e.contextEpoch===runtime.context.capture().epoch){
        this.setData({...JSON.parse(JSON.stringify(data)),loading:false,busy:false,ready:false,hasCache:false,cached:false,conflict:false,accessRevoked:true,error:e.message});
        if(this.onEditRevoked)this.onEditRevoked();
        return true;
      }
      if(e.code==='EDIT_ACCESS_REVOKED'){
        this.setData({role:'viewer',writable:false,busy:false,loading:false,error:e.message});
        if(this.onEditRevoked)this.onEditRevoked();
        return true;
      }
      return false;
    },
    async run(work, mutation = false, { background = false } = {}) {
      if (mutation && this.data.busy) return;
      const runtime = getRuntime(); const ticket = runtime.context.capture();
      const generation = runtime.session.generation(); const load = this._load || 0;
      const readEpoch = mutation || background ? this._readEpoch : (this._readEpoch = (this._readEpoch || 0) + 1);
      const valid = () => this._visible !== false && load === (this._load || 0) &&
        generation === runtime.session.generation() && runtime.context.isCurrent(ticket) &&
        (mutation || readEpoch === this._readEpoch);
      if (!background) this.setData({ [mutation ? 'busy' : 'loading']: true, error: '', conflict: false, accessRevoked: false });
      try { return await work(valid); }
      catch (e) {
        if(this.handleAccessError(e,generation))return;
        if (e.code === 'EDIT_ACCESS_REVOKED' && generation === runtime.session.generation() && this.familyId === e.familyId) {
          this.setData({role:'viewer',writable:false,busy:false,loading:false,error:e.message});
          if(this.onEditRevoked)this.onEditRevoked();
          return;
        }
        if (e.code === 'FAMILY_ACCESS_REVOKED' && generation === runtime.session.generation() &&
          e.contextEpoch === runtime.context.capture().epoch && this.familyId === e.familyId) {
          this.setData({ ...JSON.parse(JSON.stringify(data)), loading: false, busy: false,
            ready: false, hasCache: false, cached: false, conflict: false, accessRevoked: true, error: e.message });
          return;
        }
        if (!background && valid() && e.code !== 'STALE') this.setData({
          error: e.status === 409 ? '内容已发生变化。你的填写已保留，请重新加载后核对。' : e.message || '操作失败，请重试',
          conflict: e.status === 409,
          cached: e.code === 'NETWORK' && !!this.data.hasCache,
          ...(this.errorState?this.errorState(e):{})
        });
      } finally {
        if (!background && valid()) this.setData({ [mutation ? 'busy' : 'loading']: false });
      }
    },
    input(e) { this.setData({ ['form.' + e.currentTarget.dataset.field]: e.detail.value }); },
    goFamilies() { navigate('families'); },
    ...methods
  };
  if(methods.onShow){const show=methods.onShow;result.onShow=function(...args){this.setData({busy:false});return show.apply(this,args);};}
  return result;
}
async function membership(familyId) {
  const {api,session}=getRuntime();
  const members=await api.request('/families/'+encodeURIComponent(familyId)+'/members');
  const own=members.find(m=>m.user_id===session.user().id && m.status==='active');
  return { members, role: own ? own.role : null, own };
}
module.exports = { definePage, navigate, requireLogin, selectFamily, selectChild, confirmation, membership, roles };
