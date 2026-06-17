const Storage = require('../../utils/storage')
const api = require('../../utils/api')
const Theme = require('../../utils/theme')
const { STYLE_TAGS } = require('../../utils/constant')
const { toCamelClothing, toCamelDiary, toSnakeUserProfile } = require('../../utils/model')

function buildTodayText() {
  const now = new Date()
  const weekdayList = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
  return `${now.getMonth() + 1}月${now.getDate()}日 · ${weekdayList[now.getDay()]}`
}

Page({
  data: {
    userInfo: { nickname: '智搭用户', avatar: '', role: '', city: '', stylePreference: [] },
    userInitial: '智',
    children: [],
    experienceStats: {
      childCount: 0,
      clothingCount: 0,
      diaryCount: 0,
      wornCount: 0
    },
    themeClass: Theme.getThemeClass(),
    themeBgString: Theme.getThemePageBg(),
    themes: Theme.listThemes(),
    currentThemeKey: Theme.getTheme().key,
    todayText: buildTodayText(),
    // 穿搭偏好编辑态
    preferenceVisible: false,
    styleOptions: [],
    selectedStyles: {}
  },

  async onShow() {
    const app = getApp()
    await app.ensureReady()
    Theme.applyAllTheme(app.globalData.theme)
    if (!app.globalData.isLoggedIn) {
      wx.navigateTo({ url: '/pages/login/login' })
      return
    }
    const userInfo = Storage.getUser() || this.data.userInfo
    const children = Storage.getChildren()
    // 初始化 style 选项: 根据用户当前偏好选中
    const currentPref = (userInfo.stylePreference || []).reduce((acc, k) => {
      acc[k] = true
      return acc
    }, {})
    const styleOptions = STYLE_TAGS.map(s => ({ ...s, selected: currentPref[s.value] || false }))
    this.setData({
      userInfo,
      userInitial: (userInfo.nickname || '智').slice(0, 1),
      children,
      themeClass: Theme.getThemeClass(app.globalData.theme),
      themeBgString: Theme.getThemePageBg(app.globalData.theme),
      currentThemeKey: (app.globalData.theme || Theme.getTheme()).key,
      styleOptions,
      selectedStyles: currentPref
    })
    this.loadExperienceStats(children)
  },

  async loadExperienceStats(children) {
    const stats = {
      childCount: children.length,
      clothingCount: 0,
      diaryCount: 0,
      wornCount: 0
    }
    if (!children.length) {
      this.setData({ experienceStats: stats })
      return
    }
    try {
      const results = await Promise.all(children.map(async child => {
        const clothing = (await api.get('/clothing', { child_id: child.id })).map(toCamelClothing)
        const diaries = (await api.get('/diaries', { child_id: child.id })).map(toCamelDiary)
        return { clothing, diaries }
      }))
      results.forEach(({ clothing, diaries }) => {
        stats.clothingCount += clothing.length
        stats.diaryCount += diaries.length
        stats.wornCount += clothing.reduce((sum, item) => sum + (Number(item.wearCount) || 0), 0)
      })
      this.setData({ experienceStats: stats })
    } catch (e) {
      this.setData({ experienceStats: stats })
    }
  },

  switchTheme(e) {
    const key = e.currentTarget.dataset.key
    const app = getApp()
    const theme = app.switchTheme(key)
    this.setData({
      currentThemeKey: theme.key,
      themeClass: Theme.getThemeClass(theme),
      themeBgString: Theme.getThemePageBg(theme)
    })
    wx.showToast({ title: `已切换为${theme.name}`, icon: 'none' })
  },

  editChild(e) {
    const id = e.currentTarget.dataset.id
    wx.navigateTo({ url: `/pages/child-profile/child-profile?id=${id}` })
  },

  addChild() {
    wx.navigateTo({ url: '/pages/child-profile/child-profile' })
  },

  deleteChild(e) {
    const id = e.currentTarget.dataset.id
    wx.showModal({
      title: '确认删除',
      content: '删除宝贝后，关联的本地衣物记录也会一并移除。',
      confirmColor: '#E17055',
      success: async (res) => {
        if (!res.confirm) return
        await api.del(`/children/${id}`)
        Storage.deleteChild(id)
        const app = getApp()
        app.globalData.children = Storage.getChildren()
        app.globalData.currentChildIndex = 0
        this.setData({ children: app.globalData.children })
        wx.showToast({ title: '已删除', icon: 'success' })
      }
    })
  },

  onMenuTap(e) {
    const menu = e.currentTarget.dataset.menu
    if (menu === 'preference') {
      this.openPreferenceEditor()
    } else if (menu === 'notification') {
      wx.showToast({ title: '通知设置即将上线', icon: 'none' })
    } else if (menu === 'help') {
      wx.showToast({ title: '帮助反馈即将上线', icon: 'none' })
    }
  },

  openPreferenceEditor() {
    const userInfo = Storage.getUser() || this.data.userInfo
    const currentPref = (userInfo.stylePreference || []).reduce((acc, k) => {
      acc[k] = true
      return acc
    }, {})
    const styleOptions = STYLE_TAGS.map(s => ({ ...s, selected: currentPref[s.value] || false }))
    this.setData({
      preferenceVisible: true,
      styleOptions,
      selectedStyles: currentPref
    })
  },

  closePreferenceEditor() {
    this.setData({ preferenceVisible: false })
  },

  toggleStyleChip(e) {
    const value = e.currentTarget.dataset.value
    const selectedStyles = { ...this.data.selectedStyles }
    selectedStyles[value] = !selectedStyles[value]
    if (!selectedStyles[value]) delete selectedStyles[value]
    const styleOptions = this.data.styleOptions.map(s => ({
      ...s,
      selected: selectedStyles[s.value] || false
    }))
    this.setData({ selectedStyles, styleOptions })
  },

  async savePreference() {
    const chosen = Object.keys(this.data.selectedStyles).filter(k => this.data.selectedStyles[k])
    const user = Storage.getUser() || {}
    const payload = {
      role: user.role || '',
      city: user.city || '',
      style_preference: chosen
    }
    wx.showLoading({ title: '保存中...', mask: true })
    try {
      const saved = await api.put('/me', payload)
      const normalized = {
        ...user,
        role: saved.role,
        city: saved.city,
        stylePreference: saved.style_preference || []
      }
      Storage.setUser(normalized)
      const app = getApp()
      app.globalData.userInfo = normalized
      this.setData({
        userInfo: normalized,
        preferenceVisible: false
      })
      wx.showToast({ title: '已保存，下次推荐生效', icon: 'success' })
    } catch (e) {
      wx.showToast({ title: '保存失败，请重试', icon: 'none' })
    } finally {
      wx.hideLoading()
    }
  },

  logout() {
    wx.showModal({
      title: '退出登录',
      content: '退出后需要重新微信登录。',
      confirmText: '退出',
      confirmColor: '#E17055',
      success: (res) => {
        if (!res.confirm) return
        getApp().logout()
        wx.navigateTo({ url: '/pages/login/login' })
      }
    })
  }
})
