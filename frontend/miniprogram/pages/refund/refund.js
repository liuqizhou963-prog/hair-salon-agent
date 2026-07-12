Page({
  data: {
    user: {},
    amount: 0
  },

  async onShow() {
    const app = getApp();
    if (!app.ensureAuthenticated()) return;
    try {
      await app.loadCurrentUser();
    } catch (error) {
      wx.showToast({ title: error.message || "钱包加载失败", icon: "none" });
      return;
    }
    const user = app.globalData.user;
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

  async submitRefund() {
    const app = getApp();
    const amount = Number(this.data.amount);
    if (!amount || amount < 1 || amount > app.globalData.user.balance) {
      wx.showToast({ title: "请输入有效金额", icon: "none" });
      return;
    }
    try {
      await app.request("/api/refunds", {
        method: "POST",
        data: { amount, reason: "客户小程序申请退款" }
      });
      wx.showToast({ title: "已提交，待审批", icon: "success" });
      setTimeout(() => wx.switchTab({ url: "/pages/mine/mine" }), 500);
    } catch (error) {
      wx.showToast({ title: error.message || "申请失败", icon: "none" });
    }
  }
});
