App({
  globalData: {
    // 真机或微信开发者工具中可把这里改成后端的局域网地址。
    apiBase: "http://127.0.0.1:8000",
    token: "",
    user: null,
    selectedAmount: 300,
    selectedStylistId: "",
    preferredOnly: false,
    notifications: [],
    appointments: [],
    visits: [],
    pointsRecords: [],
    walletTransactions: [],
    stylists: [],
    slotsByStylist: {},
    customerStylistDisplayLimit: 4
  },

  onLaunch() {
    this.globalData.token = wx.getStorageSync("hengyi_access_token") || "";
  },

  request(path, options) {
    const config = options || {};
    const app = this;
    const header = Object.assign(
      { "Content-Type": "application/json" },
      app.globalData.token ? { Authorization: "Bearer " + app.globalData.token } : {},
      config.header || {}
    );

    return new Promise((resolve, reject) => {
      wx.request({
        url: app.globalData.apiBase + path,
        method: config.method || "GET",
        data: config.data || {},
        header,
        success(response) {
          if (response.statusCode === 401 && !config.skipAuthRedirect) {
            app.logout();
            reject(new Error("登录已失效"));
            return;
          }
          if (response.statusCode < 200 || response.statusCode >= 300) {
            const detail = response.data && response.data.detail;
            reject(new Error(detail || "请求失败"));
            return;
          }
          resolve(response.data);
        },
        fail(error) {
          reject(error);
        }
      });
    });
  },

  ensureAuthenticated() {
    if (this.globalData.token) return true;
    wx.redirectTo({ url: "/pages/login/login" });
    return false;
  },

  async login(phone, password) {
    const result = await this.request("/api/auth/login", {
      method: "POST",
      data: { phone, password },
      skipAuthRedirect: true
    });
    this.globalData.token = result.access_token;
    wx.setStorageSync("hengyi_access_token", result.access_token);
    await this.loadCurrentUser();
    return result;
  },

  async register(phone, name, password) {
    await this.request("/api/auth/register", {
      method: "POST",
      data: { phone, name, password },
      skipAuthRedirect: true
    });
    return this.login(phone, password);
  },

  async loadCurrentUser() {
    const user = await this.request("/api/auth/me");
    const results = await Promise.all([
      this.request("/api/members"),
      this.request("/api/wallet"),
      this.request("/api/points/transactions"),
      this.request("/api/notifications")
    ]);
    const members = results[0];
    const wallet = results[1];
    const pointRecords = results[2];
    const notifications = results[3];
    const member = members[0] || {};
    this.globalData.user = Object.assign({
      name: user.name,
      phone: user.phone,
      level: "silver",
      balance: Number(wallet.balance || 0),
      points: 0
    }, user, {
      level: member.level || "silver",
      points: Number(member.points || 0),
      birthday: member.birthday || ""
    });
    this.globalData.walletTransactions = wallet.transactions || [];
    this.globalData.pointRecords = (pointRecords || []).map(item => ({
      value: (item.amount > 0 ? "+" : "") + item.amount,
      desc: item.reason,
      date: String(item.created_at || "").slice(5, 10)
    }));
    this.globalData.notifications = notifications || [];
    return this.globalData.user;
  },

  async loadStylists() {
    const data = await this.request("/api/stylists");
    const photos = [
      "/assets/stylists/chen-yu-portrait.png",
      "/assets/stylists/li-si-portrait.png",
      "/assets/stylists/sophie-portrait.png",
      "/assets/stylists/zhou-ran-portrait.png"
    ];
    this.globalData.stylists = data.slice(0, this.globalData.customerStylistDisplayLimit).map((item, index) => Object.assign({}, item, {
      displayName: item.name + " 老师",
      photo: photos[index % photos.length],
      bookings: 0,
      works: 0
    }));
    return this.globalData.stylists;
  },

  async loadSlots(stylistId) {
    const slots = await this.request(
      "/api/stylists/" + encodeURIComponent(stylistId) + "/slots"
    );
    this.globalData.slotsByStylist[stylistId] = slots;
    return slots;
  },

  async loadAppointments() {
    const appointments = await this.request("/api/appointments");
    this.globalData.appointments = appointments.map(item => ({
      ...item,
      time_text: String(item.appointment_datetime || "").replace("T", " ").slice(0, 16),
      photo: "/assets/stylists/chen-yu-portrait.png"
    }));
    return this.globalData.appointments;
  },

  logout() {
    this.globalData.token = "";
    this.globalData.user = null;
    this.globalData.appointments = [];
    this.globalData.stylists = [];
    this.globalData.slotsByStylist = {};
    wx.removeStorageSync("hengyi_access_token");
    wx.redirectTo({ url: "/pages/login/login" });
  }
});
