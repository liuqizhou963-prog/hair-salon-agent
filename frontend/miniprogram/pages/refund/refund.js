Page({
  data: {
    user: {},
    amount: 0
  },

  onShow() {
    const user = getApp().globalData.user;
    this.setData({
      user,
      amount: user.balance
    });
  },

  onAmountInput(event) {
    this.setData({
      amount: Number(event.detail.value || 0)
    });
  },

  submitRefund() {
    const app = getApp();
    const amount = Number(this.data.amount);
    if (!amount || amount < 1 || amount > app.globalData.user.balance) {
      wx.showToast({ title: "请输入有效金额", icon: "none" });
      return;
    }
    app.globalData.user.balance = Math.max(0, app.globalData.user.balance - amount);
    wx.showToast({ title: "已提交", icon: "success" });
    setTimeout(() => {
      wx.switchTab({ url: "/pages/mine/mine" });
    }, 500);
  }
});
