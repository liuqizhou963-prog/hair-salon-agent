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

  async save() {
    const app = getApp();
    try {
      await app.request("/api/profile", {
        method: "PATCH",
        data: {
          name: this.data.name,
          birthday: this.data.birthday || null
        }
      });
      await app.loadCurrentUser();
      wx.showToast({ title: "已保存", icon: "success" });
      setTimeout(() => wx.switchTab({ url: "/pages/mine/mine" }), 500);
    } catch (error) {
      wx.showToast({ title: error.message || "保存失败", icon: "none" });
    }
  }
});
