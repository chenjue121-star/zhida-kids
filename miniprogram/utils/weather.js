const api = require('./api')
const Storage = require('./storage')

function fallbackWeather() {
  return { city: '当前位置', temp: 25, humidity: 50, weather: '晴', suggestion: '适宜出行' }
}

function getWeather() {
  return new Promise((resolve) => {
    wx.getLocation({
      type: 'gcj02',
      async success(locRes) {
        try {
          const weather = await api.get('/weather/current', {
            lat: locRes.latitude,
            lon: locRes.longitude
          })
          resolve(weather || fallbackWeather())
        } catch (e) {
          resolve(fallbackWeather())
        }
      },
      async fail() {
        try {
          const user = Storage.getUser() || {}
          const weather = await api.get('/weather/current', { city: user.city || '北京' })
          resolve(weather || fallbackWeather())
        } catch (e) {
          resolve(fallbackWeather())
        }
      }
    })
  })
}

function getThicknessRecommendation(temp) {
  if (temp >= 28) return 'thin'
  if (temp >= 20) return 'normal'
  if (temp >= 10) return 'thick'
  return 'fleece'
}

module.exports = { getWeather, getThicknessRecommendation }
