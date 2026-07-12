Page({
  data: {
    user: {},
    records: []
  },

  async onShow() {
    const app = getApp();
    if (!app.ensureAuthenticated()) return;
    try {
      await app.loadCurrentUser();
    } catch (error) {
      wx.showToast({ title: error.message || "积分加载失败", icon: "none" });
      return;
    }
    this.setData({
      user: app.globalData.user,
      records: app.globalData.pointsRecords || []
    });
  }
});
