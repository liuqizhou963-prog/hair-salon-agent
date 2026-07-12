Page({
  data: {
    notifications: []
  },

  async onShow() {
    const app = getApp();
    if (!app.ensureAuthenticated()) return;
    try {
      await app.loadCurrentUser();
      this.setData({ notifications: app.globalData.notifications });
    } catch (error) {
      wx.showToast({ title: error.message || "通知加载失败", icon: "none" });
    }
  },

  async read(event) {
    const id = event.currentTarget.dataset.id;
    const app = getApp();
    try {
      await app.request(`/api/notifications/${id}/read`, { method: "POST" });
      await app.loadCurrentUser();
      this.setData({ notifications: app.globalData.notifications });
    } catch (error) {
      wx.showToast({ title: error.message || "操作失败", icon: "none" });
    }
  }
});
