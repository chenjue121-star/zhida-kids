const Storage = require('../../utils/storage')
const api = require('../../utils/api')
const { toCamelChild, toSnakeChild } = require('../../utils/model')
const { SKIN_TONES } = require('../../utils/constant')
const Theme = require('../../utils/theme')

Page({
  data: {
    childId: '',
    nickname: '',
    gender: '',
    birthday: '',
    height: '',
    weight: '',
    skinTone: '',
    photoUrl: '',
    avatarUrl: '',
    skinToneOptions: SKIN_TONES,
    isEdit: false,
    saving: false,
    generatingAvatar: false,
    avatarMessage: '',
    avatarPrompt: '',
    themeClass: Theme.getThemeClass(),
    themeBgString: Theme.getThemePageBg(),
    currentThemeKey: Theme.getTheme().key,
  },

  async onLoad(options) {
    const app = getApp()
    await app.ensureReady()
    this.setData({
      themeClass: Theme.getThemeClass(app.globalData.theme),
      themeBgString: Theme.getThemePageBg(app.globalData.theme),
      currentThemeKey: (app.globalData.theme || Theme.getTheme()).key
    })
    if (!app.globalData.isLoggedIn) {
      wx.navigateTo({ url: '/pages/login/login' })
      return
    }
    if (options.id) {
      this.setData({ childId: options.id, isEdit: true })

      this.loadChild(options.id)
    }
  },

  loadChild(id) {
    const child = Storage.getChildren().find(c => String(c.id) === String(id))
    if (child) {
      this.setData({
        nickname: child.nickname,
        gender: child.gender,
        birthday: child.birthday,
        height: child.height ? String(child.height) : '',
        weight: child.weight ? String(child.weight) : '',
        skinTone: child.skinTone || '',
        photoUrl: child.photoUrl || '',
        avatarUrl: child.avatarUrl || ''
      })
    }
  },

  choosePhoto() {
    wx.chooseMedia({
      count: 1,
      mediaType: ['image'],
      sourceType: ['album', 'camera'],
      success: async (res) => {
        const filePath = res.tempFiles[0].tempFilePath
        this.setData({ photoUrl: filePath })
        const uploaded = await api.uploadImage(filePath)
        this.setData({ photoUrl: uploaded.url })
      }
    })
  },

  async generateAvatar() {
    if (!this.data.photoUrl) {
      wx.showToast({ title: '请先上传宝贝照片', icon: 'none' })
      return
    }
    if (!this.data.childId) {
      wx.showToast({ title: '请先保存宝贝信息', icon: 'none' })
      return
    }
    if (this.data.generatingAvatar) return
    this.setData({ generatingAvatar: true, avatarMessage: '', avatarPrompt: '' })
    try {
      const result = await api.post(`/children/${this.data.childId}/avatar/generate`, {})
      const avatarUrl = result.avatar_url || result.avatarUrl || ''
      this.setData({
        avatarUrl,
        avatarMessage: result.message || 'AI虚拟形象已生成，请保存宝贝信息。',
        avatarPrompt: result.prompt || ''
      })
      const children = Storage.getChildren()
      const idx = children.findIndex(c => String(c.id) === String(this.data.childId))
      if (idx >= 0) {
        children[idx].avatarUrl = avatarUrl
        Storage.setChildren(children)
        getApp().globalData.children = children
      }
      wx.showToast({ title: '生成完成', icon: 'success' })
    } finally {
      this.setData({ generatingAvatar: false })
    }
  },

  onNickname(e) { this.setData({ nickname: e.detail.value }) },
  selectGender(e) { this.setData({ gender: e.currentTarget.dataset.gender }) },
  onBirthdayChange(e) { this.setData({ birthday: e.detail.value }) },
  onHeight(e) { this.setData({ height: e.detail.value }) },
  onWeight(e) { this.setData({ weight: e.detail.value }) },
  selectSkinTone(e) { this.setData({ skinTone: e.currentTarget.dataset.value }) },

  async save() {
    const { nickname, gender, birthday, height } = this.data
    if (!nickname) { wx.showToast({ title: '请输入昵称', icon: 'none' }); return }
    if (!gender) { wx.showToast({ title: '请选择性别', icon: 'none' }); return }
    if (!birthday) { wx.showToast({ title: '请选择出生日期', icon: 'none' }); return }
    if (!height) { wx.showToast({ title: '请输入身高', icon: 'none' }); return }
    if (this.data.saving) return

    const child = {
      nickname: this.data.nickname,
      gender: this.data.gender,
      birthday: this.data.birthday,
      height: parseFloat(this.data.height) || 0,
      weight: parseFloat(this.data.weight) || 0,
      skinTone: this.data.skinTone,
      photoUrl: this.data.photoUrl,
      avatarUrl: this.data.avatarUrl
    }

    this.setData({ saving: true })
    try {
      const saved = this.data.isEdit
        ? toCamelChild(await api.put(`/children/${this.data.childId}`, toSnakeChild(child)))
        : toCamelChild(await api.post('/children', toSnakeChild(child)))

      const children = Storage.getChildren()
      const idx = children.findIndex(c => String(c.id) === String(saved.id))
      if (idx >= 0) {
        children[idx] = saved
      } else {
        children.push(saved)
      }
      Storage.setChildren(children)
      getApp().globalData.children = children

      wx.showToast({ title: '保存成功', icon: 'success' })
      setTimeout(() => wx.navigateBack(), 1000)
    } finally {
      this.setData({ saving: false })
    }
  }
})
