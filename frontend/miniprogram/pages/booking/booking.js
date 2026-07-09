Page({
  data: {
    stylists: [],
    displayStylists: [],
    selectedStylistId: "",
    preferredOnly: false,
    canTogglePreferred: false,
    disablePreferredToggle: true,
    sectionLabel: "全部老师",
    toggleText: "只看常用老师",
    hasDisplayStylists: false,
    showEmptyStylists: false
  },

  onShow() {
    this.refreshStylists();
  },

  refreshStylists() {
    var app = getApp();
    var stylists = app.globalData.stylists || [];
    var selectedStylistId = app.globalData.selectedStylistId || "";
    var preferredOnly = Boolean(app.globalData.preferredOnly);
    var baseStylists = [];
    var displayStylists = [];

    for (var i = 0; i < stylists.length; i += 1) {
      if (!preferredOnly || !selectedStylistId || stylists[i].stylist_id === selectedStylistId) {
        baseStylists.push(stylists[i]);
      }
    }

    for (var j = 0; j < baseStylists.length; j += 1) {
      var item = baseStylists[j];
      var selected = item.stylist_id === selectedStylistId;
      displayStylists.push({
        stylist_id: item.stylist_id,
        name: item.name,
        displayName: item.displayName,
        specialty: item.specialty,
        experience_years: item.experience_years,
        rating: item.rating,
        bio: item.bio,
        photo: item.photo,
        bookings: item.bookings,
        works: item.works,
        selected: selected,
        cardClass: (selected ? "stylist-card selected" : "stylist-card") + (j % 2 === 0 ? " card-left" : " card-right"),
        followClass: selected ? "follow-btn active" : "follow-btn",
        followText: selected ? "已常用" : "设为常用 +"
      });
    }

    this.setData({
      stylists: stylists,
      displayStylists: displayStylists,
      selectedStylistId: selectedStylistId,
      preferredOnly: preferredOnly,
      canTogglePreferred: Boolean(selectedStylistId),
      disablePreferredToggle: !selectedStylistId,
      sectionLabel: preferredOnly ? "常用老师" : "全部老师",
      toggleText: preferredOnly ? "查看全部老师" : "只看常用老师",
      hasDisplayStylists: displayStylists.length > 0,
      showEmptyStylists: displayStylists.length === 0
    });
  },

  openSchedule(event) {
    var id = event.currentTarget.dataset.id;
    getApp().globalData.selectedStylistId = id;
    wx.navigateTo({
      url: "/pages/teacher-schedule/teacher-schedule?id=" + id
    });
  },

  preferStylist(event) {
    var id = event.currentTarget.dataset.id;
    var app = getApp();
    app.globalData.selectedStylistId = id;
    this.refreshStylists();
    wx.navigateTo({
      url: "/pages/teacher-schedule/teacher-schedule?id=" + id
    });
  },

  togglePreferredOnly() {
    var app = getApp();
    if (!app.globalData.selectedStylistId) return;
    app.globalData.preferredOnly = !app.globalData.preferredOnly;
    this.refreshStylists();
  },

  goMine() {
    wx.switchTab({ url: "/pages/mine/mine" });
  },

  goHome() {
    wx.switchTab({ url: "/pages/mine/mine" });
  }
});
