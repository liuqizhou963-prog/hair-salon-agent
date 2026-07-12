Page({
  data: {
    registerMode: false,
    name: "",
    phone: "",
    password: "",
    loading: false,
    error: ""
  },

  onInput(event) {
    const field = event.currentTarget.dataset.field;
    this.setData({ [field]: event.detail.value, error: "" });
  },

  toggleMode() {
    this.setData({ registerMode: !this.data.registerMode, error: "" });
  },

  async submit() {
    const { registerMode, name, phone, password } = this.data;
    if (registerMode && !name.trim()) {
      this.setData({ error: "请输入姓名" });
      return;
    }
    if (!phone.trim() || password.length < 8) {
      this.setData({ error: "请输入手机号和至少 8 位密码" });
      return;
    }
    this.setData({ loading: true, error: "" });
    try {
      const app = getApp();
      if (registerMode) await app.register(phone.trim(), name.trim(), password);
      else await app.login(phone.trim(), password);
      wx.switchTab({ url: "/pages/mine/mine" });
    } catch (error) {
      this.setData({ error: error.message || "操作失败，请稍后重试" });
    } finally {
      this.setData({ loading: false });
    }
  }
});
