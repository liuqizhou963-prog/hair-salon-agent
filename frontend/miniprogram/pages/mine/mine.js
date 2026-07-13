Page({
  data: {
    user: {},
    balanceText: "0.00",
    appointments: [],
    hasAppointments: false,
    showEmptyAppointments: true,
    showBookingShortcut: true
  },

  async onShow() {
    const app = getApp();
    if (!app.ensureAuthenticated()) return;
    try {
      await Promise.all([app.loadCurrentUser(), app.loadAppointments()]);
    } catch (error) {
      wx.showToast({ title: error.message || "数据加载失败", icon: "none" });
      return;
    }
    const user = app.globalData.user || {};
    this.setData({
      user,
      balanceText: Number(user.balance || 0).toFixed(2),
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

  logout() {
    getApp().logout();
  },

  goBooking() {
    wx.switchTab({ url: "/pages/booking/booking" });
  },

  goRefund() {
    wx.navigateTo({ url: "/pages/refund/refund" });
  },

  cancelAppointment(event) {
    const id = event.currentTarget.dataset.id;
    const app = getApp();
    wx.showModal({
      title: "取消预约",
      content: "确定取消这次预约吗？",
      success: async result => {
        if (!result.confirm) return;
        try {
          await app.request("/api/appointments/" + encodeURIComponent(id), {
            method: "DELETE"
          });
          await app.loadAppointments();
          this.setData({
            appointments: app.globalData.appointments,
            hasAppointments: app.globalData.appointments.length > 0,
            showEmptyAppointments: app.globalData.appointments.length === 0,
            showBookingShortcut: app.globalData.appointments.length === 0
          });
          wx.showToast({ title: "预约已取消", icon: "success" });
        } catch (error) {
          wx.showToast({ title: error.message || "取消预约失败", icon: "none" });
        }
      }
    });
  },

  goHome() {
    wx.switchTab({ url: "/pages/mine/mine" });
  }
});
