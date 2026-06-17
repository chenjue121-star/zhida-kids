const Storage = require('../../utils/storage')
const api = require('../../utils/api')
const { toCamelChild, toSnakeChild, toSnakeUserProfile } = require('../../utils/model')
const { STYLE_TAGS, SKIN_TONES } = require('../../utils/constant')
const Theme = require('../../utils/theme')

Page({
  data: {
    step: 1,
    // Step 1
    role: '',
    city: '',
    styleOptions: STYLE_TAGS.map(s => ({ ...s, selected: false })),
    selectedStyles: {},
    // Step 2
    childName: '',
    childGender: '',
    childBirthday: '',
    childHeight: '',
    childWeight: '',
    childSkinTone: '',
    childPhoto: '',
    skinToneOptions: SKIN_TONES,
    // Step 3
    firstClothingAdded: false,
    saving: false,
    themeClass: Theme.getThemeClass(),
    themeBgString: Theme.getThemePageBg(),
    currentThemeKey: Theme.getTheme().key,
  },

  onLoad() {
    const user = Storage.getUser() || {}
    const selectedStyles = (user.stylePreference || []).reduce((acc, item) => {
      acc[item] = true
      return acc
    }, {})
    const styleOptions = STYLE_TAGS.map(s => ({ ...s, selected: selectedStyles[s.value] || false }))
    this.setData({
      role: user.role || '',
      city: user.city || '',
      selectedStyles,
      styleOptions,
      themeClass: Theme.getThemeClass(getApp().globalData.theme),
      themeBgString: Theme.getThemePageBg(getApp().globalData.theme),
      currentThemeKey: (getApp().globalData.theme || Theme.getTheme()).key
    })
  },

  // Step 1 handlers
  selectRole(e) {
    this.setData({ role: e.currentTarget.dataset.role })
  },

  chooseLocation() {
    wx.chooseLocation({
      success: (res) => {
        this.setData({ city: res.name || res.address })
      },
      fail: () => {
        // 手动输入
        wx.showModal({
          title: '输入城市',
          editable: true,
          placeholderText: '请输入你所在的城市',
          success: (res) => {
            if (res.confirm && res.content) {
              this.setData({ city: res.content })
            }
          }
        })
      }
    })
  },

  toggleStyle(e) {
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

  // Step 2 handlers
  onChildName(e) {
    this.setData({ childName: e.detail.value })
  },

  selectGender(e) {
    this.setData({ childGender: e.currentTarget.dataset.gender })
  },

  onBirthdayChange(e) {
    this.setData({ childBirthday: e.detail.value })
  },

  onChildHeight(e) {
    this.setData({ childHeight: e.detail.value })
  },

  onChildWeight(e) {
    this.setData({ childWeight: e.detail.value })
  },

  selectSkinTone(e) {
    this.setData({ childSkinTone: e.currentTarget.dataset.value })
  },

  chooseChildPhoto() {
    wx.chooseMedia({
      count: 1,
      mediaType: ['image'],
      sourceType: ['album', 'camera'],
      success: async (res) => {
        const filePath = res.tempFiles[0].tempFilePath
        this.setData({ childPhoto: filePath })
        const uploaded = await api.uploadImage(filePath)
        this.setData({ childPhoto: uploaded.url })
      }
    })
  },

  // Step 3 handlers
  takePhoto() {
    wx.navigateTo({
      url: '/pages/add-clothing/add-clothing?mode=camera&from=onboarding',
      events: {
        clothingAdded: () => {
          this.setData({ firstClothingAdded: true })
        }
      }
    })
  },

  manualAdd() {
    wx.navigateTo({
      url: '/pages/add-clothing/add-clothing?mode=manual&from=onboarding',
      events: {
        clothingAdded: () => {
          this.setData({ firstClothingAdded: true })
        }
      }
    })
  },

  // Navigation
  async nextStep() {
    const { step } = this.data

    if (step === 1) {
      if (!this.validateUserProfile()) return
      await this.saveUserInfo()
      this.setData({ step: 2 })
    } else if (step === 2) {
      if (!this.validateChild()) return
      await this.saveChild()
      this.setData({ step: 3 })
    } else if (step === 3) {
      await this.finishOnboarding()
    }
  },

  onSkip() {
    const { step } = this.data
    if (step === 1) {
      this.setData({ step: 2 })
    } else if (step === 2) {
      this.setData({ step: 3 })
    }
  },

  validateUserProfile() {
    if (!this.data.role) {
      wx.showToast({ title: '请选择你的角色', icon: 'none' })
      return false
    }
    if (!this.data.city) {
      wx.showToast({ title: '请选择或输入城市', icon: 'none' })
      return false
    }
    return true
  },

  validateChild() {
    const { childName, childGender, childBirthday, childHeight } = this.data
    if (!childName) {
      wx.showToast({ title: '请输入宝贝昵称', icon: 'none' })
      return false
    }
    if (!childGender) {
      wx.showToast({ title: '请选择性别', icon: 'none' })
      return false
    }
    if (!childBirthday) {
      wx.showToast({ title: '请选择出生日期', icon: 'none' })
      return false
    }
    if (!childHeight) {
      wx.showToast({ title: '请输入身高', icon: 'none' })
      return false
    }
    return true
  },

  async saveUserInfo() {
    if (this.data.saving) return
    this.setData({ saving: true })
    const user = Storage.getUser() || {}
    user.role = this.data.role
    user.city = this.data.city
    user.stylePreference = Object.keys(this.data.selectedStyles).filter(k => this.data.selectedStyles[k])
    try {
      const saved = await api.put('/me', toSnakeUserProfile(user))
      const app = getApp()
      const normalized = {
        id: saved.id,
        nickname: saved.nickname,
        avatar: saved.avatar,
        role: saved.role,
        city: saved.city,
        stylePreference: saved.style_preference || []
      }
      Storage.setUser(normalized)
      app.globalData.userInfo = normalized
    } finally {
      this.setData({ saving: false })
    }
  },

  async saveChild() {
    if (this.data.saving) return
    this.setData({ saving: true })
    const child = {
      nickname: this.data.childName,
      gender: this.data.childGender,
      birthday: this.data.childBirthday,
      height: parseFloat(this.data.childHeight) || 0,
      weight: parseFloat(this.data.childWeight) || 0,
      skinTone: this.data.childSkinTone,
      photoUrl: this.data.childPhoto,
      avatarUrl: ''
    }
    try {
      const saved = toCamelChild(await api.post('/children', toSnakeChild(child)))
      const app = getApp()
      const children = [...Storage.getChildren(), saved]
      Storage.setChildren(children)
      app.globalData.children = children
      app.globalData.currentChildIndex = 0
    } finally {
      this.setData({ saving: false })
    }
  },

  async finishOnboarding() {
    const app = getApp()
    await app.refreshSessionData()
    wx.setStorageSync('onboardingComplete', true)
    wx.switchTab({ url: '/pages/index/index' })
  }
})
