Page({
  data: {
    balance: 328,
    points: 1280,
    preferredStylist: {
      name: "张三",
      specialty: "烫、染、护理",
      availableText: "今天可约"
    },
    availableSlots: [
      { period: "上午", time: "10:00", status: "余 2 位", tone: "warm" },
      { period: "午后", time: "14:30", status: "推荐", tone: "primary" },
      { period: "傍晚", time: "18:00", status: "紧俏", tone: "cool" }
    ]
  },

  openMenu() {
    wx.showActionSheet({
      itemList: ["个人资料", "推送通知", "隐私政策"],
      success: (res) => {
        const routes = [
          "/pages/profile/index",
          "/pages/push/index",
          "/pages/privacy/index"
        ];
        wx.navigateTo({ url: routes[res.tapIndex] });
      }
    });
  },

  goBooking() {
    wx.navigateTo({
      url: "/pages/booking/index"
    });
  },

  goFavorite() {
    wx.navigateTo({
      url: "/pages/booking/index?preferred=1"
    });
  },

  goOrders() {
    wx.navigateTo({
      url: "/pages/orders/index"
    });
  },

  goAppointments() {
    wx.navigateTo({
      url: "/pages/appointments/index"
    });
  },

  goWallet() {
    wx.navigateTo({
      url: "/pages/wallet/index"
    });
  },

  stayHome() {
    wx.pageScrollTo({
      scrollTop: 0,
      duration: 200
    });
  }
});
