Page({
  data: {
    user: {},
    selectedAmount: 300,
    baseAmounts: [
      { value: 100, bonus: "" },
      { value: 200, bonus: "" },
      { value: 300, bonus: "送30元" },
      { value: 500, bonus: "送80元" },
      { value: 800, bonus: "送150元" },
      { value: 1000, bonus: "送220元" }
    ]
  },

  onShow() {
    const app = getApp();
    this.setData({
      user: app.globalData.user,
      selectedAmount: app.globalData.selectedAmount || 300
    });
    this.refreshAmounts();
  },

  refreshAmounts() {
    const selectedAmount = Number(this.data.selectedAmount);
    const amounts = this.data.baseAmounts.map(item => ({
      value: item.value,
      bonus: item.bonus,
      bonusText: item.bonus || "立即到账",
      selected: item.value === selectedAmount,
      className: item.value === selectedAmount ? "amount-btn selected" : "amount-btn"
    }));
    this.setData({ amounts });
  },

  selectAmount(event) {
    const selectedAmount = Number(event.currentTarget.dataset.value);
    getApp().globalData.selectedAmount = selectedAmount;
    this.setData({ selectedAmount });
    this.refreshAmounts();
  },

  onCustomInput(event) {
    const selectedAmount = Number(event.detail.value || 0);
    if (!selectedAmount) return;
    getApp().globalData.selectedAmount = selectedAmount;
    this.setData({ selectedAmount });
    this.refreshAmounts();
  },

  submitRecharge() {
    const app = getApp();
    const amount = Number(this.data.selectedAmount);
    if (!amount || amount < 1) {
      wx.showToast({ title: "请输入有效金额", icon: "none" });
      return;
    }
    app.globalData.user.balance += amount;
    app.globalData.selectedAmount = amount;
    wx.navigateTo({ url: `/pages/recharge-ok/recharge-ok?amount=${amount}` });
  }
});
