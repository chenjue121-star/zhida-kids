function generateId() {
  return Date.now().toString(36) + Math.random().toString(36).substr(2, 9)
}

const Storage = {
  // --- User ---
  getUser() {
    return wx.getStorageSync('userInfo') || null
  },
  setUser(info) {
    wx.setStorageSync('userInfo', info)
  },
  clearUser() {
    wx.removeStorageSync('token')
    wx.removeStorageSync('userInfo')
    wx.removeStorageSync('children')
    wx.removeStorageSync('onboardingComplete')
  },

  // --- Children ---
  getChildren() {
    return wx.getStorageSync('children') || []
  },
  setChildren(children) {
    wx.setStorageSync('children', children || [])
  },
  saveChild(child) {
    const children = this.getChildren()
    if (child.id) {
      const idx = children.findIndex(c => c.id === child.id)
      if (idx >= 0) children[idx] = child
    } else {
      child.id = generateId()
      child.createdAt = new Date().toISOString()
      children.push(child)
    }
    wx.setStorageSync('children', children)
    return child
  },
  deleteChild(id) {
    const children = this.getChildren().filter(c => c.id !== id)
    wx.setStorageSync('children', children)
    this.getClothingByChild(id).forEach(c => this.deleteClothing(c.id))
  },

  // --- Clothing ---
  getAllClothing() {
    return wx.getStorageSync('clothing') || []
  },
  getClothingByChild(childId) {
    return this.getAllClothing().filter(c => c.childId === childId)
  },
  getClothingById(id) {
    return this.getAllClothing().find(c => c.id === id) || null
  },
  saveClothing(item) {
    const all = this.getAllClothing()
    if (item.id) {
      const idx = all.findIndex(c => c.id === item.id)
      if (idx >= 0) all[idx] = item
    } else {
      item.id = generateId()
      item.createdAt = new Date().toISOString()
      item.wearCount = 0
      item.lastWornAt = null
      item.status = item.status || 'active'
      all.push(item)
    }
    wx.setStorageSync('clothing', all)
    return item
  },
  deleteClothing(id) {
    const all = this.getAllClothing().filter(c => c.id !== id)
    wx.setStorageSync('clothing', all)
  },
  updateClothingStatus(id, status) {
    const item = this.getClothingById(id)
    if (item) {
      item.status = status
      this.saveClothing(item)
    }
  },

  // --- Outfits ---
  getOutfits() {
    return wx.getStorageSync('outfits') || []
  },
  getOutfitsByChild(childId) {
    return this.getOutfits().filter(o => o.childId === childId)
  },
  saveOutfit(outfit) {
    const all = this.getOutfits()
    if (outfit.id) {
      const idx = all.findIndex(o => o.id === outfit.id)
      if (idx >= 0) all[idx] = outfit
    } else {
      outfit.id = generateId()
      outfit.createdAt = new Date().toISOString()
      all.push(outfit)
    }
    wx.setStorageSync('outfits', all)
    return outfit
  },

  // --- Diary ---
  getDiaries() {
    return wx.getStorageSync('diaries') || []
  },
  getDiariesByChild(childId) {
    return this.getDiaries().filter(d => d.childId === childId)
  },
  getDiaryByDate(childId, date) {
    return this.getDiaries().find(d => d.childId === childId && d.date === date) || null
  },
  saveDiary(diary) {
    const all = this.getDiaries()
    if (diary.id) {
      const idx = all.findIndex(d => d.id === diary.id)
      if (idx >= 0) all[idx] = diary
    } else {
      diary.id = generateId()
      diary.createdAt = new Date().toISOString()
      all.push(diary)
    }
    wx.setStorageSync('diaries', all)
    return diary
  }
}

module.exports = Storage
