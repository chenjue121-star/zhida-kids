const AUTH = 'v2:auth';
const PENDING = 'v2:pending-invitation';
function createSession(storage, context) {
  let identity = storage.getStorageSync(AUTH) || null;
  let generation = 0;
  const capabilities = new Map();
  function cleanFiles(k) {
    if (!k.endsWith(':media-files') && !k.endsWith(':media-tempfiles')) return;
    const paths = storage.getStorageSync(k) || [];
    for (const filePath of paths) {
      if(k.endsWith(':media-files') && storage.removeSavedFile)storage.removeSavedFile({filePath,fail(){}});
      if(k.endsWith(':media-tempfiles') && storage.getFileSystemManager)storage.getFileSystemManager().unlink({filePath,fail(){}});
    }
  }
  function purge(id) {
    if (!id) return;
    const prefix = 'v2:' + id + ':';
    storage.getStorageInfoSync().keys.filter(k => k.startsWith(prefix)).forEach(k => {cleanFiles(k);storage.removeStorageSync(k);});
  }
  function key(family, name) {
    if (!identity) throw new Error('尚未登录');
    return 'v2:' + identity.user.id + ':' + (family || '_') + ':' + name;
  }
  return {
    token: () => identity ? identity.token : undefined,
    user: () => identity ? identity.user : null,
    generation: () => generation,
    set(value) {
      if (!value.token || !value.user || typeof value.user.id !== 'string') throw new Error('登录响应格式错误');
      if (identity && identity.user.id !== value.user.id) {
        purge(identity.user.id); storage.removeStorageSync(PENDING);
      }
      identity = { token: value.token, user: value.user, expires_at: value.expires_at };
      storage.setStorageSync(AUTH, identity); generation += 1; capabilities.clear(); context.clear();
    },
    logout() {
      purge(identity && identity.user.id); identity = null; generation += 1;
      storage.removeStorageSync(AUTH); storage.removeStorageSync(PENDING); capabilities.clear(); context.clear();
    },
    pending(value) {
      if (arguments.length) {
        if (value) storage.setStorageSync(PENDING, value);
        else storage.removeStorageSync(PENDING);
      }
      return storage.getStorageSync(PENDING);
    },
    read(family, name) { return identity ? storage.getStorageSync(key(family, name)) : undefined; },
    write(family, name, value) { storage.setStorageSync(key(family, name), value); },
    remove(family, name) { if (identity) storage.removeStorageSync(key(family, name)); },
    capability(family, role) {
      const previous = capabilities.get(family) || {role:null,epoch:0};
      if (arguments.length > 1 && previous.role !== role) {
        capabilities.set(family,{role,epoch:previous.epoch+1});
        if(identity && ['admin','editor'].includes(previous.role) && !['admin','editor'].includes(role)){
          const prefix=key(family,'');
          storage.getStorageInfoSync().keys.filter(k=>k.startsWith(prefix) && (k===prefix+'media-files' || k.startsWith(prefix+'intake-local:') || k.startsWith(prefix+'duplicate-choices:'))).forEach(k=>{cleanFiles(k);storage.removeStorageSync(k);});
        }
      }
      return capabilities.get(family) || previous;
    },
    canEdit(family) {return ['admin','editor'].includes(this.capability(family).role);},
    clearFamily(family) {
      if (!identity) return;
      const prefix = key(family, '');
      storage.getStorageInfoSync().keys.filter(k => k.startsWith(prefix)).forEach(k => {cleanFiles(k);storage.removeStorageSync(k);});
      this.capability(family, null);
      const families = this.read('_', 'families');
      if (families) this.write('_', 'families', families.filter(f => f.id !== family));
      if (this.read('_', 'family') === family) this.remove('_', 'family');
      if (context.capture().current && context.capture().current.familyId === family) context.clear();
    },
    mutationKey(family, operation, payload) {
      const k = key(family, 'mutation:' + operation);
      const signature = JSON.stringify(payload);
      const previous = storage.getStorageSync(k);
      if (previous && previous.signature === signature) return previous.value;
      const value = Date.now().toString(36) + '-' + Math.random().toString(36).slice(2) + '-' + Math.random().toString(36).slice(2);
      storage.setStorageSync(k, { signature, value });
      return value;
    },
    completeMutation(family, operation) { storage.removeStorageSync(key(family, 'mutation:' + operation)); }
  };
}
module.exports = { createSession };
