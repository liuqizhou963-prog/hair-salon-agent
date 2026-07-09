Page({
  data: {
    notifications: {}
  },

  onShow() {
    this.setData({ notifications: getApp().globalData.notifications });
  },

  toggle(event) {
    const key = event.currentTarget.dataset.key;
    const app = getApp();
    app.globalData.notifications[key] = event.detail.value;
    this.setData({ notifications: app.globalData.notifications });
  }
});
