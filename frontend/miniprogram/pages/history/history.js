Page({
  data: {
    visits: []
  },

  async onShow() {
    const app = getApp();
    if (!app.ensureAuthenticated()) return;
    try {
      const appointments = await app.loadAppointments();
      this.setData({ visits: appointments
        .filter(item => item.status === "completed")
        .map(item => ({
          date: item.appointment_datetime,
          service: item.service,
          stylist: item.stylist_name,
          status: "已完成"
        })) });
    } catch (error) {
      wx.showToast({ title: error.message || "记录加载失败", icon: "none" });
    }
  }
});
