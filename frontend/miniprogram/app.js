App({
  globalData: {
    user: {
      name: "测试客户",
      phone: "13800000000",
      birthday: "08-18",
      level: "GOLD",
      balance: 328,
      points: 1280
    },
    selectedAmount: 300,
    selectedStylistId: "",
    preferredOnly: false,
    notifications: {
      revisit: true,
      birthday: true,
      points: true
    },
    appointments: [],
    visits: [
      { date: "2026-06-28", service: "修复护理", stylist: "Ada", amount: 198 },
      { date: "2026-05-30", service: "洗剪吹", stylist: "Leo", amount: 88 },
      { date: "2026-04-28", service: "烫发", stylist: "Cici", amount: 598 },
      { date: "2026-03-10", service: "染发", stylist: "Nora", amount: 298 }
    ],
    pointsRecords: [
      { value: "+198", desc: "修复护理消费积分", date: "06-28" },
      { value: "+88", desc: "洗剪吹消费积分", date: "05-30" },
      { value: "-500", desc: "积分兑换抵扣", date: "05-10" }
    ],
    stylists: [
      {
        stylist_id: "demo-sophie",
        name: "苏菲",
        displayName: "苏菲 老师",
        specialty: "短发层次、法式刘海、轻盈造型",
        experience_years: 8,
        rating: 4.9,
        bio: "擅长根据脸型做轻盈短发与空气感刘海，风格干净、自然、好打理。",
        photo: "/assets/stylists/sophie-portrait.png",
        bookings: 312,
        works: 48
      },
      {
        stylist_id: "demo-li-si",
        name: "李四",
        displayName: "李四 老师",
        specialty: "男士裁剪、商务造型、纹理烫",
        experience_years: 8,
        rating: 4.8,
        bio: "主打利落男士发型和商务质感造型，适合想要清爽、有型的顾客。",
        photo: "/assets/stylists/li-si-portrait.png",
        bookings: 286,
        works: 42
      },
      {
        stylist_id: "demo-chen-yu",
        name: "陈宇",
        displayName: "陈宇 老师",
        specialty: "韩系男发、蓬松纹理、轮廓修饰",
        experience_years: 6,
        rating: 4.9,
        bio: "擅长韩系层次和头顶蓬松感处理，能把发型轮廓做得更显脸小。",
        photo: "/assets/stylists/chen-yu-portrait.png",
        bookings: 268,
        works: 36
      },
      {
        stylist_id: "demo-zhou-ran",
        name: "周然",
        displayName: "周然 老师",
        specialty: "日系清爽、自然微分、少年感造型",
        experience_years: 5,
        rating: 4.7,
        bio: "偏自然、干净的日系审美，适合第一次尝试微分或轻纹理的顾客。",
        photo: "/assets/stylists/zhou-ran-portrait.png",
        bookings: 241,
        works: 31
      }
    ],
    slotsByStylist: {
      "demo-sophie": [
        { slot_id: "demo-sophie-1", date: "2026-07-10", time: "10:00" },
        { slot_id: "demo-sophie-2", date: "2026-07-10", time: "14:30" },
        { slot_id: "demo-sophie-3", date: "2026-07-11", time: "18:00" }
      ],
      "demo-li-si": [
        { slot_id: "demo-li-si-1", date: "2026-07-10", time: "11:00" },
        { slot_id: "demo-li-si-2", date: "2026-07-11", time: "15:30" },
        { slot_id: "demo-li-si-3", date: "2026-07-11", time: "19:00" }
      ],
      "demo-chen-yu": [
        { slot_id: "demo-chen-yu-1", date: "2026-07-10", time: "13:00" },
        { slot_id: "demo-chen-yu-2", date: "2026-07-12", time: "16:00" },
        { slot_id: "demo-chen-yu-3", date: "2026-07-12", time: "18:30" }
      ],
      "demo-zhou-ran": [
        { slot_id: "demo-zhou-ran-1", date: "2026-07-11", time: "10:30" },
        { slot_id: "demo-zhou-ran-2", date: "2026-07-11", time: "14:00" },
        { slot_id: "demo-zhou-ran-3", date: "2026-07-13", time: "17:30" }
      ]
    }
  }
});
