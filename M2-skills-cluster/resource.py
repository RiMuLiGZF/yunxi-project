"""
Windows 兼容的 resource 模块 mock
M2 技能集群的沙箱在 Windows 上需要这个
"""

# 模拟 RLIMIT 常量
RLIMIT_AS = 9
RLIMIT_CPU = 0
RLIMIT_FSIZE = 1
RLIMIT_DATA = 2
RLIMIT_STACK = 3
RLIMIT_CORE = 4
RLIMIT_NOFILE = 7
RLIMIT_NPROC = 6
RLIMIT_MEMLOCK = 8
RLIMIT_VMEM = 9

def getrlimit(resource):
    """获取资源限制（Windows mock）"""
    return (1024 * 1024 * 1024, 2 * 1024 * 1024 * 1024)  # 1GB / 2GB

def setrlimit(resource, limits):
    """设置资源限制（Windows mock，不做实际限制）"""
    pass  # Windows 上不支持 POSIX rlimit，静默忽略

def getrusage(who):
    """获取资源使用情况（Windows mock）"""
    class RUsage:
        ru_utime = 0.0
        ru_stime = 0.0
        ru_maxrss = 0
        ru_ixrss = 0
        ru_idrss = 0
        ru_isrss = 0
        ru_minflt = 0
        ru_majflt = 0
        ru_nswap = 0
        ru_inblock = 0
        ru_oublock = 0
        ru_msgsnd = 0
        ru_msgrcv = 0
        ru_nsignals = 0
        ru_nvcsw = 0
        ru_nivcsw = 0
    return RUsage()
