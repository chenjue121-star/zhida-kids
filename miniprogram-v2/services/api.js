const config = require('../config');
function apiError(code, message, status, requestId) {
  return Object.assign(new Error(message || '请求失败，请重试'), { code, status, requestId });
}
function createApi(wx, session, context) {
  return {
    request(path, options = {}) {
      const method = options.method || 'GET';
      if (!['GET', 'POST', 'PUT', 'DELETE', 'HEAD', 'OPTIONS', 'TRACE', 'CONNECT'].includes(method)) {
        return Promise.reject(apiError('UNSUPPORTED_METHOD', '不支持的请求方法'));
      }
      const generation = session.generation();
      const ticket = context.capture();
      const familyPath = path.split('?')[0].match(/^\/families\/([^/]+)(\/.*)?$/);
      const familyId = familyPath && decodeURIComponent(familyPath[1]);
      const accessEpoch = familyId ? session.capability(familyId).epoch : null;
      if (options.editScope && (!familyId || !session.canEdit(familyId))) return Promise.reject(Object.assign(apiError('EDIT_ACCESS_REVOKED','当前仅可查看衣橱，待确认草稿暂不可访问。',403),{familyId}));
      const current = () => generation === session.generation() && (options.identityOnly || context.isCurrent(ticket)) &&
        (!options.editScope || session.capability(familyId).epoch === accessEpoch);
      return new Promise((resolve, reject) => {
        const header = { 'Content-Type': 'application/json', ...options.headers };
        if (session.token() && !options.public) header.Authorization = 'Bearer ' + session.token();
        if (options.idempotencyKey) header['Idempotency-Key'] = options.idempotencyKey;
        wx.request({
          url: config.apiBase + path, method, data: options.data,
          header, timeout: options.timeout || 15000,
          success: async response => {
            if (!current()) return reject(apiError('STALE', '已切换当前档案'));
            if (response.statusCode >= 200 && response.statusCode < 300) return resolve(response.data);
            const error = response.data && response.data.error || {};
            if (response.statusCode === 403 && familyId && options.editScope) {
              session.capability(familyId,'viewer');
              return reject(Object.assign(apiError('EDIT_ACCESS_REVOKED',error.message || '编辑权限已变化，待确认草稿暂不可访问。',403),{familyId}));
            }
            const familyPath = path.split('?')[0].match(/^\/families\/([^/]+)(\/.*)?$/);
            if (response.statusCode === 404 && familyPath && !options.public) {
              const familyId = decodeURIComponent(familyPath[1]);
              if (!familyPath[2] && method === 'GET') {
                session.clearFamily(familyId);
                return reject(Object.assign(apiError('FAMILY_ACCESS_REVOKED', '此家庭已不可访问，请返回家庭列表。', 404), {
                  familyId, contextEpoch: context.capture().epoch
                }));
              }
              // A missing child/profile is not evidence that family membership was revoked.
              try { await this.request('/families/' + familyPath[1]); }
              catch (probeError) {
                if (['FAMILY_ACCESS_REVOKED', 'STALE'].includes(probeError.code) || probeError.status === 401) return reject(probeError);
              }
              if (!current()) return reject(apiError('STALE', '已切换当前档案'));
            }
            if (response.statusCode === 401 && !options.public) {
              const invitation = path.startsWith('/invitations/') ? session.pending() : null;
              session.logout();
              if (invitation) session.pending(invitation);
              wx.reLaunch({ url: '/pages/login/login' });
            }
            reject(apiError(error.code || 'HTTP_ERROR', error.message, response.statusCode, error.request_id));
          },
          fail() {
            if (!current()) return reject(apiError('STALE', '已切换当前档案'));
            reject(apiError('NETWORK', '网络连接失败，请检查网络后重试'));
          }
        });
      });
    }
  };
}
module.exports = { createApi, apiError };
