Page({
  data: {
    amount: 0
  },

  onLoad(options) {
    this.setData({ amount: Number(options.amount || getApp().globalData.selectedAmount || 0) });
  },

  finish() {
    wx.switchTab({ url: "/pages/mine/mine" });
  }
});
