const Storage = require('../../utils/storage')
const api = require('../../utils/api')
const { toCamelUser } = require('../../utils/model')
const Theme = require('../../utils/theme')

Page({
  data: {
    loggingIn: false,
    themeClass: Theme.getThemeClass(),
    themeBgString: Theme.getThemePageBg(),
    currentThemeKey: Theme.getTheme().key
  },

  onLoad() {
  },

  async onLogin() {
    if (this.data.loggingIn) return
    this.setData({ loggingIn: true })

    try {
      const [loginRes, profile] = await Promise.all([
        this.wxLogin(),
        this.getProfileSafely()
      ])

      const res = await api.post('/auth/wechat-login', {
        code: loginRes.code,
        nickname: profile.nickname,
        avatar: profile.avatar
      })

      const userInfo = toCamelUser(res.user)
      wx.setStorageSync('token', res.token)
      Storage.setUser(userInfo)
      Storage.setChildren([])

      const app = getApp()
      app.globalData.userInfo = userInfo
      app.globalData.children = []
      app.globalData.isLoggedIn = true
      app.globalData.readyPromise = app.refreshSessionData()
      await app.globalData.readyPromise

      if (res.onboarding_complete) {
        wx.switchTab({ url: '/pages/index/index' })
      } else {
        wx.redirectTo({ url: '/pages/onboarding/onboarding' })
      }
    } catch (e) {
      wx.showToast({ title: e.message || '登录失败', icon: 'none' })
    } finally {
      this.setData({ loggingIn: false })
    }
  },

  wxLogin() {
    return new Promise((resolve, reject) => {
      wx.login({
        success: resolve,
        fail: reject
      })
    })
  },

  getProfileSafely() {
    return new Promise((resolve) => {
      wx.getUserProfile({
        desc: '用于完善用户资料',
        success: (res) => {
          resolve({
            nickname: res.userInfo.nickName,
            avatar: res.userInfo.avatarUrl
          })
        },
        fail: () => {
          resolve({ nickname: '智搭用户', avatar: '' })
        }
      })
    })
  }
})
