Page({
  data: {
    name: "",
    phone: "",
    birthday: ""
  },

  onShow() {
    const user = getApp().globalData.user;
    this.setData({
      name: user.name,
      phone: user.phone,
      birthday: user.birthday
    });
  },

  onNameInput(event) {
    this.setData({ name: event.detail.value });
  },

  onPhoneInput(event) {
    this.setData({ phone: event.detail.value });
  },

  onBirthdayInput(event) {
    this.setData({ birthday: event.detail.value });
  },

  save() {
    const app = getApp();
    app.globalData.user.name = this.data.name;
    app.globalData.user.phone = this.data.phone;
    app.globalData.user.birthday = this.data.birthday;
    wx.showToast({ title: "已保存", icon: "success" });
    setTimeout(() => wx.switchTab({ url: "/pages/mine/mine" }), 500);
  }
});
