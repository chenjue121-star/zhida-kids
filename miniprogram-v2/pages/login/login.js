const { getRuntime } = require('../../services/runtime');
const { definePage, navigate } = require('../../services/page');
const { resolveEntry } = require('../../services/entry');
Page(definePage({
  data: { hasInvitation: false },
  onShow() {
    this._visible = true; this.setData({ busy: false });
    const {session} = getRuntime();
    this.setData({ hasInvitation: !!session.pending() });
    if (session.token()) this.next();
  },
  async next() {
    try {
      const target=await resolveEntry(getRuntime());
      navigate(target, '', true);
    } catch(e) { this.setData({error:e.message || '登录后读取资料失败，请重试'}); }
  },
  async login() {
    return this.run(async valid => {
      const result = await new Promise((resolve,reject) => wx.login({
        success: r => r.code ? resolve(r) : reject(new Error('微信登录未完成，请重试')),
        fail: () => reject(new Error('微信登录失败，请重试'))
      }));
      if (!valid()) return;
      const {api,session} = getRuntime();
      const identity = await api.request('/auth/wechat-login', { method: 'POST', public: true, data: {code:result.code} });
      if (!valid()) return;
      session.set(identity); await this.next();
    },true);
  }
}));
