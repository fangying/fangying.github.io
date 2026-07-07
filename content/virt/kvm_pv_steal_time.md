Title: KVM PV Steal Time 机制分析
Date: 2026-7-4 10:00
Modified: 2026-7-4 10:00
Tags: virtualization, kvm, paravirtualization
Slug: kvm-pv-steal-time
Status: published
Authors: Yori Fang
Summary: 深入分析 Linux KVM 半虚拟化 Steal Time 机制的内核实现，覆盖 x86 与 ARM64 架构，涵盖宿主机/客户机数据流、调度器集成、vCPU 抢占检测与 PV TLB Flush 等核心主题。

# KVM PV Steal Time 机制分析

本文深入分析 Linux KVM 半虚拟化（Paravirtualized）Steal Time 机制的内核实现，覆盖 x86 与 ARM64 架构，涵盖宿主机/客户机数据流、调度器集成、vCPU 抢占检测与 PV TLB Flush 等核心主题。

# 1\. 概述

在虚拟化环境中，客户机（Guest）的 vCPU 可能被宿主机（Host）调度器抢占，导致 vCPU 虽然在客户机视角处于运行态，但实际上在宿主机层面被挂起等待 CPU。这段"被偷走的时间"称为 **Steal Time**。

KVM 通过**半虚拟化（Paravirtualization）**机制，让宿主机主动将 steal time 信息通过共享内存传递给客户机，使客户机内核能够感知到真实的时间损耗，从而做出更准确的调度和计费决策。

**核心价值**：客户机内核能准确区分"真正运行的时间"和"被宿主机抢占的时间"，避免将 steal time 误计入用户进程 CPU 时间，提升调度公平性与监控准确性。

# 2\. 核心数据结构

## 2\.1 struct kvm\_steal\_time

宿主机与客户机之间的共享内存布局，定义在 Linux 内核 UAPI 头文件中：

```c
struct kvm_steal_time {
    __u64 steal;       /* 累计 steal time，单位：纳秒 */
    __u32 version;     /* 序列计数器（奇数 = 更新中） */
    __u32 flags;       /* 当前始终为零 */
    __u8  preempted;   /* 非零表示 vCPU 已被抢占 */
    __u8  u8_pad[3];
    __u32 pad[11];
};
```

|字段|类型|说明|
|---|---|---|
|`steal`|u64|累计被偷走的纳秒数。仅统计 vCPU 有任务但被宿主机调度走的时间，不含 idle 时间|
|`version`|u32|Seqlock 序列号。奇数表示写入进行中，偶数表示数据一致可读|
|`preempted`|u8|vCPU 抢占状态标志。非零 = 已抢占，零 = 正在运行|
|`flags`|u32|保留字段，当前始终为零|

## 2\.2 MSR 接口

x86 架构通过 MSR（Model Specific Register）进行交互：

|MSR|地址|用途|
|---|---|---|
|`MSR_KVM_STEAL_TIME`|`0x4b564d03`|客户机写入共享内存物理地址 \+ 使能位|
|`MSR_KVM_STEAL_TIME` bit 0|—|使能位（KVM\_MSR\_ENABLED）。置 1 开启 steal time 上报|

共享内存必须 **64 字节对齐**，以确保缓存行对齐，避免 false sharing。

# 3\. 宿主机侧实现

## 3\.1 数据来源：sched\_info\.run\_delay

宿主机内核调度器在每个任务的 `sched_info` 结构中维护运行队列等待时间：

```c
struct sched_info {
    unsigned long pcount;           /* 在此 CPU 上运行的次数 */
    unsigned long long run_delay;   /* 在运行队列上等待的时间（纳秒） */
    unsigned long long last_arrival;
    unsigned long long last_queued;
};
```

`run_delay` 在 `sched_info_arrive()`（入队时记录到达时间）和 `sched_info_dequeued()`（出队时累加等待差值）中更新，精确记录了 vCPU 线程在宿主机运行队列上等待调度的总时间。

## 3\.2 record\_steal\_time\(\) — 核心写入函数

该函数在 `kvm_arch_vcpu_load()` 中被调用，即每次 vCPU 即将被加载到物理 CPU 上运行前执行：

```c
static void record_steal_time(struct kvm_vcpu *vcpu) {
    struct kvm_steal_time *st;

    /* 建立 shared memory 映射（涉及 KVM_GUEST_USES_PGDPTR 等） */
    if (vcpu->arch.st.msr_val & KVM_MSR_ENABLED) {
        /* ...映射 st 指向 guest 物理地址... */

        /* 首次写入：若 version 为奇数，先 +1 变偶数 */
        if (st->version & 1)
            st->version += 1;

        /* 开始写入：version 变奇数，读者需等待 */
        st->version += 1;
        smp_wmb();  /* 写屏障：确保 version 先于 steal 更新 */

        /* 累加增量 steal time */
        st->steal += current->sched_info.run_delay
                   - vcpu->arch.st.last_steal;
        vcpu->arch.st.last_steal = current->sched_info.run_delay;

        smp_wmb();  /* 写屏障：确保 steal 先于 version 更新 */
        /* 写入完成：version 再变偶数 */
        st->version += 1;
    }
}
```

**Seqlock 写入流程**：version 奇→写数据→version 偶。读者通过检查 version 奇偶和前后一致性来保证读到完整数据。

## 3\.3 调用时机

|调用点|函数|说明|
|---|---|---|
|vCPU 加载|`kvm_arch_vcpu_load()`|每次 vCPU 线程被调度到物理 CPU 时调用|
|vCPU 放卸|`kvm_arch_vcpu_put()`|记录 last\_steal 快照，供下次 load 时计算增量|

# 4\. 客户机侧实现（x86）

## 4\.1 初始化与注册

客户机内核启动时，在 `kvm_guest_init()` 中检测并注册 steal time：

```c
if (kvm_para_has_feature(KVM_FEATURE_STEAL_TIME)) {
    has_steal_clock = 1;
    static_call_update(pv_steal_clock, kvm_steal_clock);
#ifdef CONFIG_PARAVIRT_SPINLOCKS
    pv_ops.lock.vcpu_is_preempted =
        PV_CALLEE_SAVE(__kvm_vcpu_is_preempted);
#endif
}
```

注册后，内核调度器通过 `paravirt_steal_clock` 静态调用（static call）获取 steal time，无需知晓底层 hypervisor 细节。

## 4\.2 kvm\_register\_steal\_time\(\) — 每核注册

每个 CPU 在上线时向宿主机注册共享内存地址：

```c
static void kvm_register_steal_time(void) {
    int cpu = smp_processor_id();
    struct kvm_steal_time *st = &per_cpu(steal_time, cpu);

    if (!has_steal_clock)
        return;

    /* 将共享内存物理地址 | 使能位写入 MSR */
    wrmsrq(MSR_KVM_STEAL_TIME,
           (slow_virt_to_phys(st) | KVM_MSR_ENABLED));
}
```

**SEV 加密虚拟机支持**：per\-cpu 变量使用 `DEFINE_PER_CPU_DECRYPTED` 声明，确保共享内存页在加密模式下被标记为宿主机可读写（decrypted），而非 guest 私有加密页。

## 4\.3 kvm\_steal\_clock\(\) — Seqlock 无锁读取

客户机通过 seqlock 模式无锁读取共享内存中的 steal time：

```c
static u64 kvm_steal_clock(int cpu) {
    u64 steal;
    struct kvm_steal_time *src;
    int version;

    src = &per_cpu(steal_time, cpu);

    do {
        version = src->version;   /* 读 version */
        virt_rmb();               /* 读屏障 */
        steal = src->steal;       /* 读 steal 值 */
        virt_rmb();               /* 读屏障 */
    } while ((version & 1) ||     /* 写入进行中？重读 */
             (version != src->version)); /* version 变化？重读 */

    return steal;
}
```

**Seqlock 读取逻辑**：① 读 version → ② 读屏障 → ③ 读 steal → ④ 读屏障 → ⑤ 校验 version 为偶数且未变化。若校验失败则重试，保证读到一致的数据快照。

# 5\. 调度器集成

## 5\.1 steal\_account\_process\_time\(\)

客户机内核在每次时钟中断处理中调用 `steal_account_process_time()`，将 steal time 从进程 CPU 时间中扣除：

```c
static __always_inline u64 steal_account_process_time(u64 maxtime) {
    if (static_key_false(&paravirt_steal_enabled)) {
        u64 steal;

        steal = paravirt_steal_clock(smp_processor_id());
        steal -= this_rq()->prev_steal_time;

        steal = min(steal, maxtime);
        account_steal_time(steal);
        this_rq()->prev_steal_time += steal;

        return steal;
    }
    return 0;
}
```

## 5\.2 account\_steal\_time\(\) — 计入 CPU 统计

```c
void account_steal_time(u64 cputime) {
    u64 *cpustat = kcpustat_this_cpu->cpustat;
    cpustat[CPUTIME_STEAL] += cputime;
}
```

steal time 被累加到 `cpustat[CPUTIME_STEAL]` 中，最终通过 `/proc/stat` 的 `steal` 列暴露给用户态工具。

## 5\.3 数据流全链路

## 5\.4 Static Key 优化

`paravirt_steal_enabled` 是一个 **static key**（静态分支），在非虚拟化环境或 steal time 未启用时，`steal_account_process_time()` 的分支通过 jump label 优化为 NOP，零开销。只有在 KVM guest 环境且检测到 `KVM_FEATURE_STEAL_TIME` 时才动态启用。

# 6\. vCPU 抢占检测与 PV TLB Flush

## 6\.1 vCPU 抢占状态检测

steal time 结构中的 `preempted` 字段不仅用于时间统计，还支持**锁优化**。客户机自旋锁在等待另一个 vCPU 释放锁时，可以先检查该 vCPU 是否被抢占：

```c
__visible bool __kvm_vcpu_is_preempted(long cpu) {
    struct kvm_steal_time *src = &per_cpu(steal_time, cpu);
    return !!(src->preempted & KVM_VCPU_PREEMPTED);
}
```

当持有锁的 vCPU 被抢占时，等待方可以主动退避（backoff）而非持续自旋，避免浪费 CPU 周期。这对 PV spinlock 性能有显著提升。

## 6\.2 PV TLB Flush 优化

当客户机需要向其他 vCPU 发送 TLB Flush IPI 时，若目标 vCPU 已被抢占，则无需发送 IPI（因为它恢复运行时会通过 context switch 自动 flush TLB）。客户机利用 `preempted` 字段实现**跳过被抢占 vCPU** 的优化：

```c
static void kvm_flush_tlb_multi(const struct cpumask *cpumask,
                                 const struct flush_tlb_info *info) {
    /* ... */
    for_each_cpu(cpu, flushmask) {
        src = &per_cpu(steal_time, cpu);
        state = READ_ONCE(src->preempted);

        /* 如果目标 vCPU 已被抢占 */
        if ((state & KVM_VCPU_PREEMPTED)) {
            /* 设置 FLUSH_TLB 标志，vCPU 恢复时自行 flush */
            if (try_cmpxchg(&src->preempted, &state,
                            state | KVM_VCPU_FLUSH_TLB))
                __cpumask_clear_cpu(cpu, flushmask);
        }
    }
    /* 只向未被抢占的 vCPU 发送 IPI */
    native_flush_tlb_multi(flushmask, info);
}
```

|标志位|值|含义|
|---|---|---|
|`KVM_VCPU_PREEMPTED`|bit 0|vCPU 已被宿主机抢占|
|`KVM_VCPU_FLUSH_TLB`|bit 1|vCPU 恢复运行时需要 flush TLB|

# 7\. ARM64 实现

ARM64 采用 SMCCC（SMC Calling Convention）规范实现 PV steal time，而非 x86 的 MSR 机制。

## 7\.1 超级调用接口

|SMCCC Function ID|值|用途|
|---|---|---|
|`PV_TIME_FEATURES`|`0xC5000020`|查询是否支持 PV time 功能|
|`PV_TIME_ST`|`0xC5000021`|获取 stolen time 共享内存地址|

## 7\.2 数据结构差异

ARM64 的 stolen time 结构为 16 字节，遵循 ARM 规范 DEN0057/A：

```c
struct pvclock_vcpu_stolen_time_info {
    __u32 revision;         /* 规范版本 */
    __u32 attributes;       /* 属性标志，当前为零 */
    __u64 stolen_time;      /* 累计 stolen time（纳秒） */
};
```

**x86**

• MSR 寄存器交互
• 64 字节结构体
• Seqlock 版本控制
• preempted 字段支持锁优化

**ARM64**

• SMCCC HVC 超级调用
• 16 字节结构体
• 无 seqlock（原子 64 位读取）
• 无 preempted 字段

# 8\. 实际观测方法

## 8\.1 用户态工具

|工具|命令|steal 指标位置|
|---|---|---|
|top|`top`|第三行 `%st` 列|
|vmstat|`vmstat 1`|`st` 列|
|pidstat|`pidstat -u 1`|`%steal` 列|
|/proc/stat|`cat /proc/stat`|第 8 个字段 `steal`|
|perf|`perf stat -e steal-time`|steal time 事件计数|

## 8\.2 关键判断指标

**运维建议**：steal time 持续高于 **5%** 通常意味着宿主机 CPU 资源争抢严重，可能需要迁移虚拟机或增加 CPU 配额。瞬时峰值可接受，持续高 steal 需关注。

# 9\. 性能影响与设计要点

## 9\.1 开销分析

|环节|开销|说明|
|---|---|---|
|共享内存读取|极低|Seqlock 无锁读取，仅缓存行访问|
|record\_steal\_time|低|每次 vCPU load 时一次写入，O\(1\)|
|调度器集成|零（未启用时）|Static key 优化，非 guest 环境 NOP|
|PV TLB Flush|负开销|减少不必要的 IPI，实际提升性能|

## 9\.2 设计亮点

1. **Seqlock 无锁通信**：宿主机写入、客户机读取之间无需 IPI 或自旋锁，通过 version 计数器实现一致性，热路径零开销

2. **增量上报**：宿主机仅上报 steal time 增量（`run_delay - last_steal`），客户机累加，避免 64 位计数器溢出风险

3. **Static Key 动态开关**：非虚拟化环境零开销，按需启用

4. **一石二鸟的 preempted 字段**：既用于 steal time 统计，又支撑 PV spinlock 和 PV TLB flush 优化

5. **SEV 加密兼容**：通过 `DEFINE_PER_CPU_DECRYPTED` 在加密虚拟化场景下正确共享内存

---

# 10\. 参考来源

- Linux 内核源码 `arch/x86/kernel/kvm.c` — 客户机侧 PV steal time 实现

- Linux 内核源码 `arch/x86/kvm/x86.c` — 宿主机侧 record\_steal\_time 实现

- Linux 内核源码 `kernel/sched/cputime.c` — 调度器 steal time 集成

- Linux 内核文档 `Documentation/virt/kvm/x86/msr.rst` — MSR\_KVM\_STEAL\_TIME 规范

- Linux 内核文档 `Documentation/virt/kvm/arm/pvtime.rst` — ARM64 PV time 规范

- LWN\.net: "KVM steal time" patch series \(lwn\.net/Articles/447376\) — Glauber Costa 原始补丁系列

> (注：内容由 AI 生成，请谨慎参考）
