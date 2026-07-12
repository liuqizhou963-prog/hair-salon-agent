function formatDate(date) {
  const d = new Date(`${date}T00:00:00`);
  const week = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"][d.getDay()];
  return `${date.slice(5)} ${week}`;
}

function slotPeriod(time) {
  const hour = Number(time.slice(0, 2));
  if (hour >= 17) return { label: "傍晚", tone: "evening" };
  if (hour >= 12) return { label: "午后", tone: "afternoon" };
  return { label: "上午", tone: "morning" };
}

Page({
  data: {
    stylist: null,
    hasStylist: false,
    showNoStylist: true,
    heroCopy: "先选择一位常用老师，再查看他的可约时间。",
    groupedSlots: [],
    hasGroupedSlots: false,
    showEmptySlots: false
  },

  async onLoad(options) {
    const app = getApp();
    if (!app.ensureAuthenticated()) return;
    try {
      if (!app.globalData.stylists.length) await app.loadStylists();
    } catch (error) {
      this.setData({ heroCopy: error.message || "老师加载失败" });
      return;
    }
    const id = options.id || app.globalData.selectedStylistId;
    app.globalData.selectedStylistId = id;
    const stylist = app.globalData.stylists.find(item => item.stylist_id === id);
    if (!stylist) {
      this.setData({
        stylist: null,
        hasStylist: false,
        showNoStylist: true,
        heroCopy: "先选择一位常用老师，再查看他的可约时间。",
        groupedSlots: [],
        hasGroupedSlots: false,
        showEmptySlots: false
      });
      return;
    }
    let slots = app.globalData.slotsByStylist[id] || [];
    if (!slots.length) {
      try {
        slots = await app.loadSlots(id);
      } catch (error) {
        slots = [];
      }
    }
    const groups = slots.reduce((acc, slot) => {
      const period = slotPeriod(slot.time);
      const group = acc.find(item => item.date === slot.date);
      const item = {
        slot_id: slot.slot_id,
        date: slot.date,
        time: slot.time,
        period: period.label,
        tone: period.tone
      };
      if (group) {
        group.slots.push(item);
        group.slotCountText = `${group.slots.length} 个时间段可选`;
      } else {
        acc.push({
          date: slot.date,
          dateText: formatDate(slot.date),
          slotCountText: "1 个时间段可选",
          slots: [item]
        });
      }
      return acc;
    }, []);
    groups.forEach(group => {
      group.slots = group.slots.map((slot, index) => ({
        slot_id: slot.slot_id,
        date: slot.date,
        time: slot.time,
        period: slot.period,
        tone: slot.tone,
        cardClass: `slot-card ${slot.tone} ${index % 2 === 0 ? "slot-left" : "slot-right"}`
      }));
    });
    this.setData({
      stylist,
      hasStylist: true,
      showNoStylist: false,
      heroCopy: `${stylist.displayName} · ${stylist.specialty}`,
      groupedSlots: groups,
      hasGroupedSlots: groups.length > 0,
      showEmptySlots: groups.length === 0
    });
  },

  goBooking() {
    wx.switchTab({ url: "/pages/booking/booking" });
  },

  async bookSlot(event) {
    const app = getApp();
    const slotId = event.currentTarget.dataset.id;
    const slot = (app.globalData.slotsByStylist[this.data.stylist.stylist_id] || [])
      .find(item => item.slot_id === slotId);
    if (!slot) return;
    try {
      await app.request("/api/appointments", {
        method: "POST",
        data: {
          stylist_id: this.data.stylist.stylist_id,
          slot_id: slotId,
          service: "洗剪吹",
          notes: "客户从小程序预约"
        }
      });
      await app.loadAppointments();
      wx.showToast({ title: "预约成功", icon: "success" });
      setTimeout(() => wx.switchTab({ url: "/pages/mine/mine" }), 500);
    } catch (error) {
      wx.showToast({ title: error.message || "预约失败", icon: "none" });
    }
  }
});
