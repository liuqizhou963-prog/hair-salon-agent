Page({
  data: {
    user: {},
    records: []
  },

  onShow() {
    const app = getApp();
    this.setData({
      user: app.globalData.user,
      records: app.globalData.pointsRecords
    });
  }
});
