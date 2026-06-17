App({
  globalData: {
    userInfo: null,
    children: [],
    currentChildIndex: 0,
    isLoggedIn: false,
    weatherInfo: null,
    apiBaseUrl: 'http://127.0.0.1:8000',
    readyPromise: null,
    theme: null
  },

  onLaunch() {
    this.initTheme()
    this.globalData.readyPromise = this.bootstrap()
  },

  initTheme() {
    const Theme = require('./utils/theme')
    const theme = Theme.getTheme()
    this.globalData.theme = theme
    Theme.applyAllTheme(theme)
  },

  switchTheme(themeKey) {
    const Theme = require('./utils/theme')
    const theme = Theme.setTheme(themeKey)
    this.globalData.theme = theme
    Theme.applyAllTheme(theme)
    return theme
  },

  ensureReady() {
    if (!this.globalData.readyPromise) {
      this.globalData.readyPromise = this.bootstrap()
    }
    return this.globalData.readyPromise
  },

  async bootstrap() {
    const token = wx.getStorageSync('token')
    const userInfo = wx.getStorageSync('userInfo')
    const children = wx.getStorageSync('children') || []

    if (!token) {
      this.globalData.userInfo = null
      this.globalData.children = []
      this.globalData.isLoggedIn = false
      return false
    }

    // 先用本地缓存，即使接口失败也能展示
    this.globalData.userInfo = userInfo
    this.globalData.children = children
    this.globalData.isLoggedIn = true

    // refreshSessionData 内部已做降级：单个接口失败不再触发 logout
    try {
      await this.refreshSessionData()
    } catch (e) {
      // ignore: 单接口失败不应影响整体登录态
    }
    return true
  },

  async refreshSessionData() {
    const api = require('./utils/api')
    const Storage = require('./utils/storage')
    const { toCamelUser, toCamelChild } = require('./utils/model')

    let user = this.globalData.userInfo
    let children = this.globalData.children

    // /me 失败：保留本地 userInfo，不影响登录
    try {
      user = toCamelUser(await api.get('/me'))
      this.globalData.userInfo = user
      Storage.setUser(user)
    } catch (e) {
      // fallback: keep local user
    }

    // /children 失败：保留本地 children
    try {
      children = (await api.get('/children')).map(toCamelChild)
      this.globalData.children = children
      Storage.setChildren(children)
    } catch (e) {
      // fallback: keep local children
    }

    if (this.globalData.currentChildIndex >= (children ? children.length : 0)) {
      this.globalData.currentChildIndex = 0
    }
    this.globalData.isLoggedIn = true

    const onboardingOk = Boolean(
      (user && user.role && user.city) && children && children.length > 0
    )
    wx.setStorageSync('onboardingComplete', onboardingOk)
    return { user, children }
  },

  logout() {
    wx.removeStorageSync('token')
    wx.removeStorageSync('userInfo')
    wx.removeStorageSync('children')
    wx.removeStorageSync('onboardingComplete')
    this.globalData.userInfo = null
    this.globalData.children = []
    this.globalData.currentChildIndex = 0
    this.globalData.isLoggedIn = false
  },

  getCurrentChild() {
    const { children, currentChildIndex } = this.globalData
    return children[currentChildIndex] || null
  },

  switchChild(index) {
    if (index >= 0 && index < this.globalData.children.length) {
      this.globalData.currentChildIndex = index
    }
  }
})
