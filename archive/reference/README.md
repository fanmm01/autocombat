# autocombat v0.9.0 — 运行指导

CoC魔法少女半自动战斗系统。包含 Sealdice JS 插件 + Python 训练/模拟/锦标赛三引擎统一。

---

## 文件结构

```
autocombat/
├── autocombat.js          # Sealdice 插件（JS源）
├── battle_engine.py       # 统一战斗引擎（Python） ← 核心
│   ├── Character          # 角色数据类
│   ├── CombatEngine       # 基础引擎（状态/HP/法术/效果/tick-down）
│   ├── FullBattleEngine   # 详细模式（COC7攻击+反应+召唤物+zone）
│   └── FastBattleEngine   # 训练模式（快速攻击+Q-learning优化）
├── ai_trainer.py          # Q-Learning 自训练系统
├── ai_battle.py           # HTTP锦标赛服务器 + 自定义比赛
├── test_harness.py        # [已废弃] 旧版基础引擎
├── characters_data.py     # 12角色 + 5召唤物模板定义
├── spell_catalog.py       # 生成 spells_catalog.md
├── reference/cards/       # 12角色 .st/.xlsx 卡片
└── ai_weights.json        # 训练输出（Q表+反应权重）
```

---

## 快速开始

### 1. 安装依赖
```bash
pip install openpyxl  # 仅生成Excel卡片需要
```

```bash
python ai_trainer.py
python ai_battle.py
```


### 2. 训练AI（可选，推荐先训练）
```bash
cd d:\Datastruct\logai\autocombat
python ai_trainer.py
```
- 50代 × 100场 = 5000场自对战
- 12核并行（ProcessPoolExecutor）
- 输出 `ai_weights.json`（Q表 + 反应权重）
- 约需 5-15 分钟

### 3. 启动锦标赛服务器
```bash
python ai_battle.py
```
- 监听 `http://0.0.0.0:8888`（局域网可访问）
- 自动加载 `ai_weights.json`（如存在）
- 启动后自动开始锦标赛

---

## HTTP 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 状态页（角色数、战斗数、AI模式） |
| GET | `/log` | 最近100条日志 |
| GET | `/log/stream` | **SSE实时日志流**（保持连接，逐条推送） |
| GET | `/results` | result.txt 比赛结果 |
| POST | `/start` | 手动开始锦标赛（未自动启动时） |
| GET | `/game/Y1&Y2_vs_Y3&num=7&map=10x10` | 自定义比赛 |

### 自定义比赛格式
```
/game/<队伍A>_vs_<队伍B>&num=<局数>&map=<地图>
```
示例：
```
/game/Y10&Y2&Y6_vs_Y8&Y12&num=7       → Y10+Y2+Y6 vs Y8+Y12, Bo7
/game/Y1_vs_Y9&num=3&map=6x6           → Y1 vs Y9, Bo3, 6x6地图
```

### 其他设备实时查看
浏览器打开 `http://<服务器IP>:8888/log/stream` — SSE自动推送每条日志。

---

## 训练系统

### 超参数
| 参数 | 默认值 | 说明 |
|------|--------|------|
| GENERATIONS | 50 | 训练代数 |
| BATTLES_PER_GEN | 100 | 每代对战数 |
| ALPHA | 0.1 | Q-learning学习率 |
| GAMMA | 0.9 | 折扣因子 |
| EPSILON_START | 0.20 | 初始探索率 |
| EPSILON_MIN | 0.03 | 最小探索率 |

### 训练内容
- **行动选择**: 法术1-4（含目标选择T0最低HP/T1最近/T2最高威胁）、普攻、前进、结束
- **目标选择**: 最低HP优先 / 最近优先 / 最高威胁优先
- **反应选择**: 闪避 vs 反击（每战更新权重）
- **召唤物技能**: SUMMON_Q表独立训练

### 奖励函数
```
即时奖励 = Δ(我方有效HP - 敌方有效HP) / maxHP
终局奖励 = 胜+3.0 / 败-3.0
有效HP = HP + 护盾值
```

---

## 12角色

| 序号 | 角色 | HP | MP | 核心机制 |
|------|------|----|----|----------|
| Y1 | 炎焱 | 14→140 | 16→72 | 斗殴奖励骰 + 火焰附魔DOT |
| Y2 | 达尼厄斯 | 12→84 | 15→45 | 火球3发 + 召唤使魔 |
| Y3 | 灵牛 | 13→143 | 12→60 | 斗殴奖励骰 + 附魔(伤害+1d3) |
| Y4 | 星闪 | 11→99 | 17→68 | 奖励骰远程 + 演唱惩罚骰 + 普攻限1次 |
| Y5 | 血天使 | 8→72 | 14→56 | MOV+4+奖励骰 + 吸血 |
| Y6 | 雪人 | 7→77 | 13→65 | 雪带zone(DOT+MOV减半) + 雪球 |
| Y7 | 环花暖 | 10→110 | 15→75 | 治愈领域(HP+MP每回合) + 战意值 |
| Y8 | 比哈米 | 7→56 | 15→52 | 蛋糕制造(HP/MP回复) + 上限12 |
| Y9 | 木落 | 120 | 65 | 召唤生灵 + 生之矛 + 领域·生 + 阶段转换 |
| Y10 | 春晌 | 10→120 | 14→77 | 屏障+治疗+藤蔓+蜂鸟 |
| Y11 | 蓝 | 12→156 | 12→72 | 镰刀 + 黑雾zone(进入SAN CHECK+MP吸收) |
| Y12 | 斯瑞提卡 | 8→120 | 18→126 | 空间扭曲/压缩/扩张 + 随机召唤(玄武/朱雀/龙虎) |

## 5召唤物

| 名称 | HP | DEX | 特殊 |
|------|-----|-----|------|
| 使魔 | 24 | 70 | 斗殴65% 1d6+1d4 |
| 生灵 | 6 | 85 | 斗殴40% 1d4 |
| 藤蔓 | 24 | 15 | 鞭50% 2d4, MOV0 |
| 蜂鸟 | 12 | 90 | 爪击60% 1d6+1d4, 行动次数2 |
| 玄武 | 80 | 30 | 2×2占据, 盾格挡100HP |
| 朱雀 | 90 | 90 | 飞行, 爪击+俯冲, 行动次数2 |
| 龙虎 | 140 | 60 | 水火弹双发, 积雨云引导群攻 |

---

## 生成角色卡片

```bash
cd reference\cards
python generate_cards.py        # 生成12个 .st.txt 文件
python generate_excel_cards.py  # 生成12个 .xlsx 文件
```

---

## 测试

```bash
python spell_catalog.py     # 生成 spells_catalog.md（12角色全部法术执行效果）
python test_all.py          # 全角色测试
python ai_trainer.py        # 训练1代快速验证
```
