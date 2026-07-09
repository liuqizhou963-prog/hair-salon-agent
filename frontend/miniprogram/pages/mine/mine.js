Page({
  data: {
    user: {},
    balanceText: "0.00",
    appointments: [],
    hasAppointments: false,
    showEmptyAppointments: true,
    showBookingShortcut: true
  },

  onShow() {
    const app = getApp();
    this.setData({
      user: app.globalData.user,
      balanceText: Number(app.globalData.user.balance || 0).toFixed(2),
      appointments: app.globalData.appointments,
      hasAppointments: app.globalData.appointments.length > 0,
      showEmptyAppointments: app.globalData.appointments.length === 0,
      showBookingShortcut: app.globalData.appointments.length === 0
    });
  },

  goRecharge() {
    wx.navigateTo({ url: "/pages/recharge/recharge" });
  },

  scrollAppointments() {
    wx.pageScrollTo({
      selector: "#appointment-section",
      duration: 250
    });
  },

  goHistory() {
    wx.navigateTo({ url: "/pages/history/history" });
  },

  goPoints() {
    wx.navigateTo({ url: "/pages/points/points" });
  },

  goProfile() {
    wx.navigateTo({ url: "/pages/profile/profile" });
  },

  goPush() {
    wx.navigateTo({ url: "/pages/push/push" });
  },

  goPrivacy() {
    wx.navigateTo({ url: "/pages/privacy/privacy" });
  },

  goBooking() {
    wx.switchTab({ url: "/pages/booking/booking" });
  },

  goRefund() {
    wx.navigateTo({ url: "/pages/refund/refund" });
  },

  goHome() {
    wx.switchTab({ url: "/pages/mine/mine" });
  }
});
