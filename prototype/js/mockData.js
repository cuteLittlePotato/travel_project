// 模拟数据

// 景点数据
const mockAttractions = [
    {
        id: 1,
        name: '故宫博物院',
        province: '北京市',
        city: '北京市',
        category: ['历史人文', '5A景区'],
        image: 'https://images.unsplash.com/photo-1508804185872-d7badad00f7d?w=800',
        summary: '中国明清两代的皇家宫殿，是中国古代宫廷建筑之精华。',
        ticketPrice: 60,
        openingHours: '08:30-17:00',
        visitDuration: 180,
        bestSeason: ['春季', '秋季'],
        popularity: 95,
        reason: '热门历史文化景点，游客必去之地'
    },
    {
        id: 2,
        name: '长城',
        province: '北京市',
        city: '北京市',
        category: ['历史人文', '世界遗产'],
        image: 'https://images.unsplash.com/photo-1508804185872-d7badad00f7d?w=800',
        summary: '中国古代的军事防御工程，世界文化遗产。',
        ticketPrice: 40,
        openingHours: '07:00-18:00',
        visitDuration: 240,
        bestSeason: ['春季', '秋季'],
        popularity: 92,
        reason: '世界七大奇迹之一'
    },
    {
        id: 3,
        name: '张家界国家森林公园',
        province: '湖南省',
        city: '张家界市',
        category: ['自然景色', '5A景区'],
        image: 'https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=800',
        summary: '以奇峰异石、峡谷溪流为特色的自然景观。',
        ticketPrice: 228,
        openingHours: '07:00-18:00',
        visitDuration: 480,
        bestSeason: ['春季', '夏季', '秋季'],
        popularity: 88,
        reason: '中国最美自然景观之一'
    },
    {
        id: 4,
        name: '九寨沟',
        province: '四川省',
        city: '阿坝州',
        category: ['自然景色', '5A景区', '世界遗产'],
        image: 'https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=800',
        summary: '以多层次瀑布、彩色湖泊群为特色的自然保护区。',
        ticketPrice: 169,
        openingHours: '07:00-19:00',
        visitDuration: 420,
        bestSeason: ['秋季'],
        popularity: 90,
        reason: '人间仙境，秋色最美'
    },
    {
        id: 5,
        name: '西湖',
        province: '浙江省',
        city: '杭州市',
        category: ['自然景色', '5A景区', '世界遗产'],
        image: 'https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=800',
        summary: '中国著名的淡水湖，以秀丽的湖光山色著称。',
        ticketPrice: 0,
        openingHours: '全天开放',
        visitDuration: 240,
        bestSeason: ['春季', '秋季'],
        popularity: 86,
        reason: '江南美景代表'
    },
    {
        id: 6,
        name: '大雁塔',
        province: '陕西省',
        city: '西安市',
        category: ['历史人文', '5A景区'],
        image: 'https://images.unsplash.com/photo-1508804185872-d7badad00f7d?w=800',
        summary: '唐代佛教建筑，玄奘法师取经归来后翻译佛经之处。',
        ticketPrice: 40,
        openingHours: '08:00-18:00',
        visitDuration: 120,
        bestSeason: ['春季', '秋季'],
        popularity: 78,
        reason: '古都西安标志性建筑'
    },
    {
        id: 7,
        name: '黄山',
        province: '安徽省',
        city: '黄山市',
        category: ['自然景色', '5A景区', '世界遗产'],
        image: 'https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=800',
        summary: '以奇松、怪石、云海、温泉著称的名山。',
        ticketPrice: 190,
        openingHours: '06:00-17:30',
        visitDuration: 480,
        bestSeason: ['春季', '秋季'],
        popularity: 85,
        reason: '五岳归来不看山，黄山归来不看岳'
    },
    {
        id: 8,
        name: '桂林山水',
        province: '广西壮族自治区',
        city: '桂林市',
        category: ['自然景色', '5A景区'],
        image: 'https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=800',
        summary: '以喀斯特地貌为特色的山水景观。',
        ticketPrice: 0,
        openingHours: '全天开放',
        visitDuration: 360,
        bestSeason: ['春季', '秋季'],
        popularity: 82,
        reason: '桂林山水甲天下'
    }
];

// 餐厅数据
const mockRestaurants = [
    {
        id: 1,
        name: '全聚德烤鸭店',
        cuisineType: '中餐',
        avgCost: 150,
        rating: 4.5,
        image: 'https://images.unsplash.com/photo-1504674900247-0877df9cc836?w=400'
    },
    {
        id: 2,
        name: '海底捞火锅',
        cuisineType: '火锅',
        avgCost: 120,
        rating: 4.8,
        image: 'https://images.unsplash.com/photo-1504674900247-0877df9cc836?w=400'
    }
];

// 酒店数据
const mockHotels = [
    {
        id: 1,
        name: '北京饭店',
        starRating: '5星',
        priceRange: '500-800',
        rating: 4.6,
        image: 'https://images.unsplash.com/photo-1566073771259-6a8506099945?w=400'
    },
    {
        id: 2,
        name: '如家快捷酒店',
        starRating: '经济型',
        priceRange: '200-300',
        rating: 4.2,
        image: 'https://images.unsplash.com/photo-1566073771259-6a8506099945?w=400'
    }
];

// 旅游计划数据
const mockPlans = [
    {
        id: 1,
        title: '北京历史文化3日游',
        destination: '北京市',
        startDate: '2024-05-01',
        endDate: '2024-05-03',
        budget: 3000,
        status: 'planning',
        createdAt: '2024-04-15',
        days: [
            {
                date: '2024-05-01',
                attractions: [
                    { id: 1, name: '故宫博物院', timeSlot: '09:00-12:00' },
                    { id: 6, name: '天坛公园', timeSlot: '14:00-17:00' }
                ]
            }
        ]
    },
    {
        id: 2,
        title: '张家界山水探险4日游',
        destination: '张家界市',
        startDate: '2024-06-10',
        endDate: '2024-06-13',
        budget: 5000,
        status: 'pending',
        createdAt: '2024-04-20',
        days: []
    }
];

// 足迹数据
const mockFootprints = [
    {
        id: 1,
        attractionId: 1,
        attractionName: '故宫博物院',
        visitDate: '2023-10-01',
        rating: 5,
        review: '非常震撼的历史建筑，值得细细品味。',
        images: ['https://images.unsplash.com/photo-1508804185872-d7badad00f7d?w=400'],
        source: 'auto_from_plan'
    },
    {
        id: 2,
        attractionId: 5,
        attractionName: '西湖',
        visitDate: '2023-09-15',
        rating: 5,
        review: '风景如画，适合散步和拍照。',
        images: ['https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=400'],
        source: 'manual'
    }
];

// 用户数据
const mockUsers = [
    {
        id: 1,
        username: 'user001',
        nickname: '旅行者',
        phone: '138****8888',
        email: 'user@example.com',
        avatar: '',
        createdAt: '2024-01-15',
        lastLoginAt: '2024-04-20',
        status: 'active'
    }
];

// 对话历史数据
const mockChatHistory = [
    {
        id: 1,
        role: 'user',
        content: '我想五月去北京玩三天，有什么推荐吗？',
        timestamp: '2024-04-20 10:30:00'
    },
    {
        id: 2,
        role: 'assistant',
        content: '北京是个很好的选择！五月的北京天气宜人，适合游览。根据您的三天行程，我推荐以下景点：\n\n第一天：故宫博物院 → 天安门广场 → 王府井\n第二天：八达岭长城 → 明十三陵\n第三天：颐和园 → 圆明园 → 天坛公园\n\n您的预算大概是多少呢？我可以为您规划更详细的行程。',
        timestamp: '2024-04-20 10:30:15'
    }
];

// 数据看板统计数据
const mockDashboardStats = {
    userStats: {
        totalUsers: 12580,
        activeUsers: 3456,
        newUsersToday: 126,
        dauTrend: [2100, 2300, 2500, 2800, 3200, 3400, 3456]
    },
    contentStats: {
        totalAttractions: 1250,
        totalRestaurants: 3500,
        totalHotels: 2800,
        categoryDistribution: {
            '历史人文': 35,
            '自然景色': 40,
            '现代娱乐': 15,
            '其他': 10
        }
    },
    businessStats: {
        totalPlans: 8750,
        completedPlans: 6200,
        completionRate: 71,
        avgPlanDays: 3.8,
        avgBudget: 3500,
        topDestinations: [
            { city: '北京', count: 1250 },
            { city: '上海', count: 980 },
            { city: '杭州', count: 850 },
            { city: '成都', count: 720 },
            { city: '西安', count: 680 }
        ]
    },
    interactionStats: {
        totalChats: 25600,
        avgRounds: 8.5,
        topTopics: [
            { topic: '景点咨询', count: 8500 },
            { topic: '行程规划', count: 7200 },
            { topic: '交通查询', count: 5100 },
            { topic: '美食推荐', count: 4800 }
        ]
    }
};
