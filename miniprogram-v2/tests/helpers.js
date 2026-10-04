function storage() {
  const data = new Map();
  return { getStorageSync: k => data.get(k), setStorageSync: (k,v) => data.set(k,v),
    removeStorageSync: k => data.delete(k), getStorageInfoSync: () => ({ keys: [...data.keys()] }) };
}
module.exports = { storage };
