Page({
  data: {
    visits: []
  },

  onShow() {
    this.setData({ visits: getApp().globalData.visits });
  }
});
