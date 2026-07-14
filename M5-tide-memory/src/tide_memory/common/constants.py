"""
潮汐记忆系统 - 全局常量集中管理

所有魔法数字和配置默认值集中在此处，避免硬编码散落在各处。
分类：记忆层常量、检索常量、巩固常量、向量常量、安全常量、情绪常量、
      缓存常量、潮汐相位常量、数据库常量等。
"""

from __future__ import annotations

# ============================================================
# 记忆层常量 (Memory Layer Constants)
# ============================================================

# L0 沙滩层 - 瞬时记忆
L0_MAX_ITEMS = 100                 # L0 最大记忆条目数
L0_RETENTION_HOURS = 1              # L0 保留时长（小时）
L0_ACCESS_PRIORITY = 10             # L0 访问优先级（1-10，越高越优先）

# L1 浅水层 - 短期记忆
L1_MAX_ITEMS = 1000                 # L1 最大记忆条目数
L1_RETENTION_DAYS = 1               # L1 保留天数
L1_ACCESS_PRIORITY = 7              # L1 访问优先级
L1_DEFAULT_QUALITY_SCORE = 50.0     # L1 默认质量评分

# L2 深水层 - 中期记忆
L2_MAX_ITEMS = 10000                # L2 最大记忆条目数
L2_RETENTION_DAYS = 30              # L2 保留天数
L2_ACCESS_PRIORITY = 4              # L2 访问优先级
L2_COMPRESS_QUALITY_THRESHOLD = 30  # L2 压缩的质量分阈值

# L3 深海层 - 长期记忆
L3_MAX_ITEMS = 100000               # L3 最大记忆条目数
L3_RETENTION_DAYS = -1              # L3 保留天数（-1 表示永久）
L3_ACCESS_PRIORITY = 1              # L3 访问优先级

# 记忆层名称
LAYER_L0_BEACH = "l0_beach"
LAYER_L1_SHALLOW = "l1_shallow"
LAYER_L2_DEEP = "l2_deep"
LAYER_L3_ABYSS = "l3_abyss"

# 默认检索层级
DEFAULT_SEARCH_LAYERS = [LAYER_L1_SHALLOW, LAYER_L2_DEEP]
ALL_LAYERS = [LAYER_L0_BEACH, LAYER_L1_SHALLOW, LAYER_L2_DEEP, LAYER_L3_ABYSS]

# 质量等级
QUALITY_LEVEL_EXCELLENT = "excellent"
QUALITY_LEVEL_GOOD = "good"
QUALITY_LEVEL_NORMAL = "normal"
QUALITY_LEVEL_LOW = "low"
QUALITY_LEVEL_POOR = "poor"
QUALITY_LEVEL_DISTILLED = "distilled"
QUALITY_LEVEL_DISTILLED_MASTER = "distilled_master"
QUALITY_LEVEL_COMPRESSED = "compressed"

# 记忆 ID 前缀
MEMORY_ID_PREFIX = "mem_"
MEMORY_ID_LENGTH = 16               # UUID hex 截取长度

# ============================================================
# 检索常量 (Recall Constants)
# ============================================================

# RRF 融合参数
RRF_K = 60                          # Reciprocal Rank Fusion 的 k 值

# 相似度阈值
DEFAULT_SIMILARITY_THRESHOLD = 0.7   # 默认相似度阈值
TFIDF_SIMILARITY_THRESHOLD = 0.2     # TF-IDF 模式下的相似度阈值（偏低）
MIN_SCORE_VARIANCE = 0.05           # 动态阈值的最小分数方差
DYNAMIC_THRESHOLD_STD_FACTOR = 0.5   # 动态阈值标准差系数
DYNAMIC_THRESHOLD_MIN_RATIO = 0.7    # 动态阈值最低为基础阈值的比例
DYNAMIC_THRESHOLD_MAX = 0.95         # 动态阈值上限

# 检索结果数量
DEFAULT_TOP_K = 10                   # 默认返回结果数
RECALL_EXPAND_MULTIPLIER = 5        # 检索时扩大召回的倍数
FILTER_EXPAND_MULTIPLIER = 3        # 过滤前多取的倍数
FUSION_RESULT_MULTIPLIER = 2        # 融合后保留结果的倍数（相对 top_k）

# MMR 去重
DEFAULT_ENABLE_MMR = True            # 是否默认启用 MMR
DEFAULT_MMR_LAMBDA = 0.7             # MMR 默认 lambda 值（相关性 vs 多样性权衡）

# 混合检索
DEFAULT_ENABLE_HYBRID = True         # 是否默认启用混合检索
DEFAULT_HYBRID_ALPHA = 0.7           # 混合检索向量权重（关键词权重 = 1 - alpha）
KEYWORD_MATCH_MAX_TF_FACTOR = 3      # 关键词匹配中 TF 的最大放大倍数
TAG_MATCH_SCORE = 0.5                # 标签匹配的基础分数

# 查询扩展
DEFAULT_ENABLE_QUERY_EXPANSION = True  # 是否默认启用查询扩展
QUERY_EXPANSION_MAX_VARIANTS = 5       # 查询扩展最大变体数

# 关键词检索权重
DEFAULT_KEYWORD_WEIGHT = 0.5         # 关键词检索权重（向量检索权重为 1 - keyword_weight）

# 预加载
DEFAULT_PRELOAD_TOP_K = 3            # recall 结果前 N 个预加载到 L0

# 检索超时
DEFAULT_SEARCH_TIMEOUT_MS = 5000     # 默认检索超时时间（毫秒）

# ============================================================
# 巩固常量 (Consolidation Constants)
# ============================================================

# 遗忘得分权重（多维评估，总和应为 1.0）
FORGET_WEIGHT_QUALITY = 0.30         # 质量分权重
FORGET_WEIGHT_ACCESS = 0.30          # 访问频率权重
FORGET_WEIGHT_TIME = 0.20            # 时间衰减权重
FORGET_WEIGHT_EMOTION = 0.20         # 情绪强度权重

# 遗忘阈值
FORGET_THRESHOLD_DELETE = 0.80       # 立即删除阈值
FORGET_THRESHOLD_DEMOTE = 0.60       # 降级到下一层阈值
FORGET_THRESHOLD_MARK = 0.40         # 标记为"正在遗忘"阈值

# 遗忘计算参数
FORGET_ACCESS_LOG_FACTOR = 0.5       # 访问频率对数衰减因子
FORGET_HALF_LIFE_DAYS = 30.0         # 时间衰减半衰期（天）
FORGET_MAX_SCORE = 1.0               # 遗忘得分上限
FORGET_MIN_SCORE = 0.0               # 遗忘得分下限
QUALITY_SCORE_MAX = 100.0            # 质量分最大值
QUALITY_SCORE_DEFAULT = 50.0        # 质量分默认值
QUALITY_SCORE_DIVISOR = 6.0          # 相似度计算中的质量分除数
LOW_QUALITY_THRESHOLD = 30.0         # 低质量阈值

# L0 → L1 迁移条件
PROMOTE_L0_ACCESS_THRESHOLD = 2      # L0→L1 访问次数阈值
PROMOTE_L0_QUALITY_THRESHOLD = 60    # L0→L1 质量分阈值

# L1 → L2 迁移条件
PROMOTE_L1_ACCESS_THRESHOLD = 3      # L1→L2 访问次数阈值
PROMOTE_L1_QUALITY_THRESHOLD = 70    # L1→L2 质量分阈值
PROMOTE_L1_EI_THRESHOLD = 0.6        # L1→L2 EI 情绪强度阈值

# L2 → L3 迁移条件
PROMOTE_L2_QUALITY_THRESHOLD = 85    # L2→L3 质量分阈值
PROMOTE_L2_ACCESS_FOR_QUALITY = 5    # L2→L3 质量路径访问次数要求
PROMOTE_L2_EI_THRESHOLD = 0.8        # L2→L3 EI 情绪强度阈值
PROMOTE_L2_ACCESS_FOR_EI = 3         # L2→L3 情绪路径访问次数要求
PROMOTE_L2_LONG_TERM_DAYS = 30       # L2→L3 长期记忆天数阈值
PROMOTE_L2_ACCESS_FOR_LONG_TERM = 10  # L2→L3 长期路径访问次数要求

# 语义蒸馏
DISTILL_TAG_OVERLAP_THRESHOLD = 0.8  # 语义蒸馏标签重合度阈值（Jaccard）
DISTILL_QUALITY_BOOST = 1.1          # 蒸馏后质量分提升倍数
DISTILL_QUALITY_DROP_RATIO = 0.3     # 被合并记忆的质量分下降比例
DISTILL_CONFIDENCE = 0.7             # 蒸馏记忆的情绪置信度

# 巩固调度
DEFAULT_CONSOLIDATION_SCHEDULE = "0 3 * * *"  # 默认巩固调度 cron（每天凌晨3点）
DEFAULT_CONSOLIDATION_BATCH_SIZE = 100       # 单次巩固批处理大小
DEFAULT_PROMOTION_RATIO = 0.1                # 每次巩固晋升比例
DEFAULT_MIN_QUALITY_SCORE = 30.0             # 晋升最低质量评分

# 巩固模式
CONSOLIDATION_MODE_QUICK = "quick"     # 快速模式（仅 L0→L1）
CONSOLIDATION_MODE_NORMAL = "normal"   # 标准模式（L0→L1→L2 + 降级）
CONSOLIDATION_MODE_FULL = "full"       # 完整模式（全链路 + 蒸馏 + 重建）

# ============================================================
# 向量常量 (Vector Constants)
# ============================================================

# Embedding 配置
DEFAULT_EMBEDDING_PROVIDER = "auto"           # 默认 embedding 提供者
DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"  # 默认 embedding 模型
DEFAULT_EMBEDDING_DIM = 384                   # 默认 embedding 维度
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"  # Ollama 默认地址
OLLAMA_TIMEOUT_CONNECT = 5                    # Ollama 连接超时（秒）
OLLAMA_TIMEOUT_REQUEST = 30                   # Ollama 请求超时（秒）

# 向量索引类型
VECTOR_INDEX_TYPE_HNSW = "HNSW"        # HNSW 索引
VECTOR_INDEX_TYPE_FLAT = "Flat"        # Flat 索引
VECTOR_INDEX_TYPE_IVF = "IVF"          # IVF 索引
DEFAULT_VECTOR_INDEX_TYPE = VECTOR_INDEX_TYPE_HNSW

# HNSW 索引参数
HNSW_DEFAULT_M = 32                    # HNSW M 参数（每层最大连接数）
HNSW_DEFAULT_EF_CONSTRUCTION = 200     # HNSW 构建时 ef 参数
HNSW_DEFAULT_EF_SEARCH = 128           # HNSW 搜索时 ef 参数
HNSW_MIN_EF_SEARCH = 16                # HNSW ef_search 最小值
HNSW_MAX_EF_SEARCH = 512               # HNSW ef_search 最大值

# GPU 配置
DEFAULT_USE_GPU = False                # 是否默认使用 GPU
DEFAULT_GPU_DEVICE_ID = 0              # 默认 GPU 设备 ID
DEFAULT_GPU_MEMORY_RATIO = 0.7         # GPU 显存使用比例

# 索引文件
DEFAULT_INDEX_PATH = "./data/vector/faiss.index"  # 默认索引路径
INDEX_META_SUFFIX = ".meta.pkl"        # 索引元数据文件后缀
INDEX_VECTORS_SUFFIX = ".vectors.npy"  # 向量数据文件后缀

# 向量批处理
DEFAULT_VECTOR_BATCH_SIZE = 100        # 批量嵌入的批次大小
DEFAULT_CACHE_EMBEDDINGS = True        # 是否缓存嵌入向量

# ============================================================
# 安全常量 (Security Constants)
# ============================================================

# 加密算法
ENCRYPTION_AES_256_GCM = "AES-256-GCM"
ENCRYPTION_AES_256_CBC = "AES-256-CBC"
ENCRYPTION_CHACHA20_POLY1305 = "ChaCha20-Poly1305"
DEFAULT_ENCRYPTION_ALGORITHM = ENCRYPTION_AES_256_GCM

# 密钥长度
MASTER_KEY_BYTE_LENGTH = 32            # 主密钥字节长度（256 bits）
SALT_BYTE_LENGTH = 16                  # Salt 字节长度
NONCE_BYTE_LENGTH = 12                 # Nonce 字节长度（GCM 推荐 96 bits）
GCM_TAG_BYTE_LENGTH = 16               # GCM 认证标签字节长度
CHECKSUM_BYTE_LENGTH = 16              # 降级加密校验和长度

# 加密参数别名（用于更通用的命名）
ENCRYPTION_KEY_SIZE = MASTER_KEY_BYTE_LENGTH    # 加密密钥大小
ENCRYPTION_SALT_SIZE = SALT_BYTE_LENGTH         # Salt 大小
ENCRYPTION_NONCE_SIZE = NONCE_BYTE_LENGTH        # Nonce 大小
ENCRYPTION_TAG_SIZE = GCM_TAG_BYTE_LENGTH        # 认证标签大小
ENCRYPTION_CHECKSUM_SIZE = CHECKSUM_BYTE_LENGTH  # 校验和大小

# PBKDF2 配置
PBKDF2_ITERATIONS_MEMORY = 10000       # 单条记忆密钥派生迭代次数
PBKDF2_ITERATIONS_MASTER = 100000      # 主密钥加密派生迭代次数
PBKDF2_HASH_ALGORITHM = "sha256"       # PBKDF2 哈希算法
PBKDF2_DERIVED_KEY_LENGTH = 32         # PBKDF2 派生密钥长度（字节）

# PBKDF2 别名
PBKDF2_ITERATIONS = PBKDF2_ITERATIONS_MEMORY  # PBKDF2 默认迭代次数
PBKDF2_DKLEN = PBKDF2_DERIVED_KEY_LENGTH      # PBKDF2 派生密钥长度

# 密级保留天数（超过后自动降级）
CLASSIFICATION_TOP_SECRET_DAYS = 365   # 绝密级保留天数
CLASSIFICATION_CONFIDENTIAL_DAYS = 180 # 机密级保留天数
CLASSIFICATION_INTERNAL_DAYS = 90      # 内部级保留天数
CLASSIFICATION_PUBLIC_DAYS = -1        # 公开级（永久，-1）

# 密级保留天数（超过后自动降级）

# 安全配置默认值
DEFAULT_HIGH_SECRET_LOCAL_ONLY = True   # 高密级是否仅限本地
DEFAULT_ENCRYPT_AT_REST = True          # 静态数据是否加密
DEFAULT_ACCESS_AUDIT = True             # 是否启用访问审计
DEFAULT_SECURE_DELETE = True            # 是否启用安全删除
DEFAULT_STORE_ORIGINAL = False          # 是否存储记忆原文（隐私优先）
DEFAULT_ORIGINAL_ENCRYPTION = True      # 原文是否加密存储

# 会话与认证
DEFAULT_SESSION_TIMEOUT_SECONDS = 3600  # 会话超时时间（秒）
DEFAULT_MAX_LOGIN_ATTEMPTS = 5          # 最大登录尝试次数

# 内容脱敏
CONTENT_SANITIZED = "[SANITIZED]"       # 脱敏内容占位符
CONTENT_ENCRYPTED = "[ENCRYPTED]"       # 加密内容占位符
CONTENT_ENCRYPTED_HINT = "[ENCRYPTED_CONTENT]"  # 加密内容提示

# ============================================================
# 情绪常量 (Emotion Constants)
# ============================================================

# EI 情绪指数
EI_MIN_VALUE = 0.0                     # EI 最小值
EI_MAX_VALUE = 1.0                     # EI 最大值
EI_DEFAULT_VALUE = 0.0                 # EI 默认值

# Valence-Arousal 范围
VALENCE_MIN = -1.0                     # 效价最小值
VALENCE_MAX = 1.0                      # 效价最大值
VALENCE_DEFAULT = 0.0                  # 效价默认值
AROUSAL_MIN = 0.0                      # 唤醒度最小值
AROUSAL_MAX = 1.0                      # 唤醒度最大值
AROUSAL_DEFAULT = 0.2                  # 唤醒度默认值

# 情绪标签阈值（Russell 情绪环模型）
AROUSAL_HIGH_THRESHOLD = 0.6           # 高唤醒度阈值
AROUSAL_LOW_THRESHOLD = 0.3            # 低唤醒度阈值
VALENCE_POSITIVE_HIGH = 0.3            # 高效价阈值（高唤醒分区）
VALENCE_NEGATIVE_HIGH = -0.3           # 低效价阈值（高唤醒分区）
VALENCE_POSITIVE_MID = 0.2             # 中效价正阈值（中唤醒分区）
VALENCE_NEGATIVE_MID = -0.2            # 中效价负阈值（中唤醒分区）

# 情绪标签
EMOTION_EXCITED = "excited"            # 兴奋
EMOTION_ANXIOUS = "anxious"            # 焦虑
EMOTION_ALERT = "alert"                # 警觉
EMOTION_CALM = "calm"                  # 平静
EMOTION_SAD = "sad"                    # 悲伤
EMOTION_RELAXED = "relaxed"            # 放松
EMOTION_POSITIVE = "positive"          # 积极
EMOTION_NEGATIVE = "negative"          # 消极
EMOTION_NEUTRAL = "neutral"            # 中性
EMOTION_DISTILLED = "distilled"        # 蒸馏（特殊标记）

# 默认情绪
DEFAULT_DOMINANT_EMOTION = EMOTION_NEUTRAL  # 默认主导情绪
DEFAULT_EMOTION_CONFIDENCE = 0.5       # 默认情绪置信度
NO_MODEL_CONFIDENCE = 0.3              # 无模型时的置信度
EMPTY_TEXT_CONFIDENCE = 0.1            # 空文本置信度

# 情绪历史
EMOTION_HISTORY_MAX_SIZE = 1000        # 情绪历史最大记录数
EMOTION_HISTORY_LIMIT = 100            # 默认历史查询限制
EMOTION_TREND_WINDOW = 10              # 情绪趋势窗口大小
EMOTION_TREND_RISE_FACTOR = 1.1        # 趋势上升判定因子
EMOTION_TREND_DECLINE_FACTOR = 0.9     # 趋势下降判定因子

# 情绪加权检索
EMOTION_MATCH_BONUS = 0.15             # 情绪一致性加成分数

# 效价-唤醒度模型
VA_BASE_AROUSAL = 0.3                  # 基础唤醒度
VA_CONFIDENCE_BASE = 0.2               # 置信度基础值
VA_CONFIDENCE_PER_WORD = 0.15          # 每个情绪词增加的置信度
VA_CONFIDENCE_MAX = 0.9                # 置信度上限
VA_NEGATION_BOOST = 0.05               # 否定后唤醒度提升
VA_NEGATION_STRENGTH_DEFAULT = 0.7     # 默认否定强度
VA_INTENSIFIER_WINDOW = 6              # 增强词窗口大小（字符）
VA_NEGATION_WINDOW = 5                 # 否定窗口大小（字符）
VA_DOUBLE_NEGATION_DISTANCE = 6        # 双重否定判定距离（字符）

# ============================================================
# 缓存常量 (Cache Constants)
# ============================================================

# 缓存协调器
DEFAULT_SETTLE_THRESHOLD_ACCESS = 2    # L0→L1 沉降访问次数阈值
DEFAULT_PRELOAD_HOT_MIN_ACCESS = 2     # 热门预加载最小访问次数
DEFAULT_PRELOAD_HOT_WITHIN_HOURS = 1   # 热门预加载时间窗口（小时）
DEFAULT_PRELOAD_HOT_MAX_ITEMS = 10     # 热门预加载最大数量

# ============================================================
# 潮汐相位常量 (Tide Phase Constants)
# ============================================================

# 相位名称
PHASE_FLOOD = "flood"                  # 潮起 - 召回活跃期
PHASE_RISING = "rising"                # 涨潮 - 写入活跃期
PHASE_SLACK = "slack"                  # 平潮 - 空闲期
PHASE_EBB = "ebb"                      # 潮落 - 低峰期

# 默认时间配置（24小时制，小时）
FLOOD_START_HOUR = 9                   # 潮起开始时间
FLOOD_END_HOUR = 12                    # 潮起结束时间
RISING_START_HOUR = 14                  # 涨潮开始时间
RISING_END_HOUR = 18                    # 涨潮结束时间
EBB_START_HOUR = 22                     # 潮落开始时间
EBB_END_HOUR = 6                       # 潮落结束时间（跨天）

# 相位检查
DEFAULT_PHASE_CHECK_INTERVAL = 60      # 相位检查间隔（秒）

# 各相位策略默认值
# Flood 潮起
FLOOD_L0_MAX_ITEMS = 200               # Flood 期 L0 缓存大小
FLOOD_SEARCH_TIMEOUT_MS = 500          # Flood 期检索超时
FLOOD_TOP_K_EXPAND = 2                 # Flood 期召回扩大倍数
FLOOD_WRITE_BATCH_SIZE = 10            # Flood 期写入批量大小

# Rising 涨潮
RISING_L0_MAX_ITEMS = 100              # Rising 期 L0 缓存大小
RISING_SEARCH_TIMEOUT_MS = 2000        # Rising 期检索超时
RISING_TOP_K_EXPAND = 1                # Rising 期召回扩大倍数
RISING_WRITE_BATCH_SIZE = 100          # Rising 期写入批量大小

# Slack 平潮
SLACK_L0_MAX_ITEMS = 100               # Slack 期 L0 缓存大小
SLACK_SEARCH_TIMEOUT_MS = 2000         # Slack 期检索超时
SLACK_TOP_K_EXPAND = 1                 # Slack 期召回扩大倍数
SLACK_WRITE_BATCH_SIZE = 50            # Slack 期写入批量大小

# Ebb 潮落
EBB_L0_MAX_ITEMS = 10                  # Ebb 期 L0 缓存大小
EBB_SEARCH_TIMEOUT_MS = 5000           # Ebb 期检索超时
EBB_TOP_K_EXPAND = 1                   # Ebb 期召回扩大倍数
EBB_WRITE_BATCH_SIZE = 200             # Ebb 期写入批量大小

# ============================================================
# 数据库常量 (Database Constants)
# ============================================================

# SQLite 配置
SQLITE_BUSY_TIMEOUT = 30.0             # SQLite 连接超时（秒）
SQLITE_CACHE_SIZE_KB = -20000          # SQLite 页缓存大小（KB，负数表示 KB 数）
SQLITE_MMAP_SIZE = 268435456           # SQLite 内存映射大小（字节，256MB）

# 数据库表名
TABLE_MEMORIES = "memories"            # 记忆主表名

# 默认分类等级
DEFAULT_CLASSIFICATION = "TOP_SECRET"  # 默认密级

# 同步
DEFAULT_SYNC_VERSION = 0               # 默认同步版本号

# ============================================================
# 审计常量 (Audit Constants)
# ============================================================

DEFAULT_AUDIT_LOG_PATH = "./logs/m5-audit.log"  # 默认审计日志路径
DEFAULT_AUDIT_ENABLED = True            # 是否默认启用审计
DEFAULT_AUDIT_ROTATION_DAYS = 30       # 日志轮转保留天数
DEFAULT_AUDIT_MAX_FILE_SIZE_MB = 100   # 单日志文件最大大小（MB）

# ============================================================
# 存储常量 (Storage Constants)
# ============================================================

DEFAULT_STORAGE_PATH = "./data/memory"  # 默认存储路径
DEFAULT_L1_DB_PATH = "./data/memory/l1_shallow.db"  # L1 默认数据库路径
DEFAULT_L2_DB_PATH = "./data/memory/l2_deep.db"    # L2 默认数据库路径
DEFAULT_L3_STORAGE_PATH = "./data/memory/l3_abyss"  # L3 默认存储路径
DEFAULT_LAYER_DB_PATH = "./data/memory/layer.db"    # 基类默认数据库路径
DEFAULT_INDEX_DB_PATH = "./data/memory/index.db"    # 索引默认数据库路径
DEFAULT_CLOUD_SYNC = False              # 是否默认启用云同步
DEFAULT_BACKUP_ENABLED = False          # 是否默认启用备份
DEFAULT_BACKUP_INTERVAL_HOURS = 24     # 备份间隔（小时）

# ============================================================
# 系统常量 (System Constants)
# ============================================================

# 基础配置
MODULE_NAME = "m5-memory"              # 模块名称
MODULE_VERSION = "2.4.0"               # 模块版本号
DEFAULT_PORT = 8005                     # 默认服务端口
DEFAULT_LOG_LEVEL = "info"              # 默认日志级别
DEFAULT_ENV = "production"              # 默认运行环境

# 分页
DEFAULT_PAGE_SIZE = 20                  # 默认分页大小

# 项目目录遍历深度
PROJECT_ROOT_SEARCH_DEPTH = 10          # 项目根目录搜索最大深度

# vim: set et ts=4 sw=4:
