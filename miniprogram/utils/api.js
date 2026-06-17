const DEFAULT_API_BASE_URL = 'http://127.0.0.1:8000'

function getApiBaseUrl() {
  const app = typeof getApp === 'function' ? getApp() : null
  return (app && app.globalData && app.globalData.apiBaseUrl) || DEFAULT_API_BASE_URL
}

function request(url, method, data) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: `${getApiBaseUrl()}${url}`,
      method,
      data,
      header: {
        'content-type': 'application/json',
        'Authorization': `Bearer ${wx.getStorageSync('token') || ''}`
      },
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data)
        } else if (res.statusCode === 401) {
          wx.removeStorageSync('token')
          wx.removeStorageSync('userInfo')
          wx.removeStorageSync('children')
          wx.redirectTo({ url: '/pages/login/login' })
          reject(new Error('未授权'))
        } else {
          const message = (res.data && (res.data.detail || res.data.message)) || '请求失败'
          // 仅 reject（不做全局 toast，让调用方自己决定提示方式
          reject(new Error(message))
        }
      },
      fail(err) {
        // 网络层错误
        reject(err)
      }
    })
  })
}

function getUploadCache() {
  return wx.getStorageSync('uploadCache') || {}
}

function setUploadCache(cache) {
  wx.setStorageSync('uploadCache', cache || {})
}

function getFileDigest(filePath) {
  return new Promise((resolve) => {
    if (!wx.getFileInfo) {
      resolve('')
      return
    }
    wx.getFileInfo({
      filePath,
      success(res) {
        resolve(res.digest || '')
      },
      fail() {
        resolve('')
      }
    })
  })
}

module.exports = {
  get: (url, data) => request(url, 'GET', data),
  post: (url, data) => request(url, 'POST', data),
  put: (url, data) => request(url, 'PUT', data),
  del: (url, data) => request(url, 'DELETE', data),

  async uploadImage(filePath) {
    const digest = await getFileDigest(filePath)
    if (digest) {
      const cache = getUploadCache()
      if (cache[digest] && cache[digest].url) {
        return { ...cache[digest], reused: true }
      }
    }

    return new Promise((resolve, reject) => {
      wx.uploadFile({
        url: `${getApiBaseUrl()}/upload`,
        filePath,
        name: 'file',
        formData: digest ? { file_hash: digest } : {},
        header: {
          'Authorization': `Bearer ${wx.getStorageSync('token') || ''}`
        },
        success(res) {
          const data = JSON.parse(res.data)
          if (digest && data && data.url) {
            const cache = getUploadCache()
            cache[digest] = data
            setUploadCache(cache)
          }
          resolve(data)
        },
        fail: reject
      })
    })
  }
}
