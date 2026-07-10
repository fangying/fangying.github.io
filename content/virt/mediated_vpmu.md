Title: Mediated vPMU 特性分析
Date: 2026-7-10 10:00
Modified: 2026-7-10 10:00
Tags: virtualization, kvm, vpmu, performance
Slug: mediated-vpmu
Status: published
Authors: Yori Fang
Summary: 深入分析 KVM Mediated vPMU 特性的设计方案与代码实现，涵盖特性背景、整体方案、代码 Patch List、热迁移支持、适用 CPU 平台、特性约束以及关键 Review 意见。

# Mediated vPMU 特性分析文档

## 目录

1. [特性背景](#1-特性背景)
2. [特性整体方案设计](#2-特性整体方案设计)
3. [代码实现 Patch List](#3-代码实现-patch-list)
4. [热迁移支持情况](#4-热迁移支持情况)
5. [适用的 CPU 平台](#5-适用的-cpu-平台)
6. [特性约束与限制](#6-特性约束与限制)
7. [关键 Review 意见](#7-关键-review-意见)

---

## 1. 特性背景

### 1.1 什么是 vPMU

vPMU（Virtual Performance Monitoring Unit）是 KVM 提供的虚拟化性能监控单元，允许虚拟机内的软件（如 guest 内核的 perf 子系统）使用 PMU 硬件进行性能分析。在 x86 架构上，PMU 硬件通过一组 MSR（Model Specific Register）和 RDPMC 指令来暴露给软件使用，包括：

- **通用计数器（General Purpose PMCs）**：可编程的性能计数器，可通过事件选择器（event selector）配置监控的事件类型
- **固定计数器（Fixed-function PMCs）**：监控固定的核心事件（如指令退休数、周期数等）
- **全局控制寄存器（PERF_GLOBAL_CTRL）**：控制所有计数器的启停
- **全局状态寄存器（PERF_GLOBAL_STATUS）**：反映计数器溢出状态
- **全局溢出控制寄存器（PERF_GLOBAL_OVF_CTRL）**：清除溢出状态

### 1.2 现有 Emulated vPMU 的问题

KVM 早已支持 vPMU（emulated vPMU），其设计思路是：guest 对 PMU MSR 的访问全部触发 VM-Exit，由 KVM 拦截后将其转换为 host perf 子系统的 perf event，通过 host perf 框架调度和共享 PMU 硬件资源。在这种设计中，KVM 是 host perf 子系统的客户端，对 PMU 硬件没有直接控制权。

这种 emulated vPMU 存在以下严重问题：

#### 1.2.1 性能开销高

Emulated vPMU 的性能开销极其严重。当 guest PMU 在复用计数器（multiplexing counters）时，情况更为恶劣——KVM 花费大量时间在重新创建、启动和释放 perf event 上，导致严重的性能退化。

RFC 中的性能基准测试数据（基于 Specint-2017，Sapphire Rapids 平台）：

| 测试场景 | Emulated vPMU 开销 | Passthrough vPMU 开销 | Passthrough + Event Filter |
|---|---|---|---|
| 基本采样 (Basic sampling) | 33.62% | 4.24% | 6.21% |
| 复用采样 (Multiplex sampling) | 79.32% | 7.34% | 10.45% |

性能瓶颈主要集中在以下 host perf 子系统函数：
- `perf_event_enable()`
- `perf_event_period()`
- `perf_event_create_kernel_counter()`
- `find_next_bit()`

#### 1.2.2 静默错误（Silent Error）

Guest perf event 的后端可能被 host perf 调度器静默地换出或禁用。这是因为 host perf 调度器将 KVM 创建的 perf event 与其他 host perf event 同等对待，它们会竞争硬件资源。当所有硬件资源被 host perf event 占用时，KVM 的 perf event 将变为非活跃状态，但 KVM 无法将此后端错误通知给 guest。对于作为生产环境的 vPMU 来说，这种静默错误是一个严重的危险信号。

#### 1.2.3 难以扩展新特性

对于每个新的 vPMU 特性，KVM 可能需要模拟新的 PMU MSR，这涉及对 perf API 的修改。厂商特定的变更使得 perf API 变得复杂，难以被社区接受。此外，由于"共享"需求导致整体设计复杂化，使得上述"静默错误"问题更加严重。基于这些原因，PEBS（Processor Event-Based Sampling）、vIBS（virtual Instruction-Based Sampling）、Topdown 等高级特性难以在 emulated vPMU 框架下实现。

#### 1.2.4 维护成本高

Host PMU 子系统的 bug 会影响 vPMU 的准确性和性能。计数器状态管理高度依赖 host perf 子系统，在性能和准确性之间存在艰难的妥协。PEBS 等高级特性在 VM-Exit 边界处会"间歇性"不可用。

### 1.3 新设计的动机

Mediated vPMU 的核心目标是允许 guest 直接拥有 PMU 硬件的访问权和所有权，从而解决 emulated vPMU 的所有已知问题：

- **低性能开销**：PMU MSR 的 passthrough 访问，独立于 host perf 子系统
- **易于扩展**：LBR、PEBS、Intel PT 等新特性可以更容易地添加
- **易于维护**：代码简单直接，不依赖复杂的 perf 调度逻辑
- **无静默错误**：Guest 独占 PMU 硬件，不存在被 host perf 抢占的风险

---

## 2. 特性整体方案设计

### 2.1 核心设计理念

Mediated vPMU 采用"mediated"（中介）设计模式，符合虚拟化中"mediated passthrough"的标准定义：

- **控制平面拦截（Control operations intercepted）**：事件选择器（event selectors）的写入被 KVM 拦截，确保安全性——防止 guest 配置不受信任的事件
- **数据平面直通（Data operations passed through）**：读取 PMC（Performance Monitoring Counter）、切换计数器启停等数据操作直接触达硬件，无需 KVM 介入

这意味着当 guest 运行时，guest PMU 独占整个 PMU 硬件，直到上下文切换回 host。

### 2.2 PMU MSR 拦截策略

Mediated vPMU 对 PMU MSR 的拦截策略如下：

| MSR 类别 | 拦截策略 | 原因 |
|---|---|---|
| 事件选择器 (Event Select MSRs, 如 PERFEVTSEL0-N) | **拦截写入** | 安全性：防止 guest 配置不受信任的事件 |
| 通用计数器 (GP PMCs, 如 PMC0-N) | **直通** | 性能：避免 VM-Exit |
| 固定计数器 (Fixed PMCs) | **直通** | 性能：避免 VM-Exit |
| 全局控制寄存器 (PERF_GLOBAL_CTRL) | **视情况直通** | Intel SPR+ 支持 VMCS 自动保存/恢复；pre-SPR 需特殊处理 |
| 全局状态寄存器 (PERF_GLOBAL_STATUS) | **直通** | 性能：guest 直接读取溢出状态 |
| 全局溢出控制寄存器 (PERF_GLOBAL_OVF_CTRL) | **直通** | 性能：guest 直接清除溢出 |

### 2.3 RDPMC 拦截策略

RDPMC 指令的拦截策略经过精心设计：

- **仅当所有 PMU 计数器都暴露给 guest 时**，才直通 RDPMC 指令
- **如果有任何计数器未暴露给 guest**，则拦截 RDPMC，防止 guest 读取未授权的计数器值
- 在 RFC v1 中曾采用"直通 RDPMC 并将未暴露计数器值清零"的 hack 方式，后被 Jim Mattson 和 Sean Christopherson 否决，改为更安全的拦截策略
- 在 v6 中，RDPMC 拦截与 PERF_GLOBAL_CTRL 拦截解耦，因为 AMD CPU 存在需要拦截 PERF_GLOBAL_CTRL 但不需要拦截所有 PMC 访问的场景

### 2.4 PMU 上下文切换

#### 2.4.1 切换位置

PMU 上下文切换在 **VM-Entry/VM-Exit 边界** 进行完整的保存和恢复：

- **VM-Entry**：保存 host PMU MSR 值，恢复 guest PMU MSR 值
- **VM-Exit**：保存 guest PMU MSR 值，恢复 host PMU MSR 值

社区曾就上下文切换的位置进行过激烈讨论，替代方案是将切换位置放在 VCPU_RUN 循环边界。但该方案的缺点是无法分析 VCPU_RUN 循环内的 KVM 代码，最终保留了 VM-Entry/Exit 边界方案。

#### 2.4.2 Intel VMX 实现

在 Intel VMX 上，PMU MSR 的上下文切换通过 **VMCS MSR auto-load 列表** 实现：

- **VM-Exit MSR auto-load list**（host 恢复）：VM-Exit 时自动将 guest MSR 值存储到内存，并加载 host 值
- **VM-Entry MSR auto-load list**（guest 恢复）：VM-Entry 时自动加载 guest MSR 值
- **PERF_GLOBAL_CTRL**：在 Sapphire Rapids 及以后的 CPU 上，通过 VMCS execution control 字段自动保存/恢复（而非 MSR auto-load 列表），这是 v4 引入的约束
- **Pre-SPR Intel CPU**（v6 新增支持）：对于 PMU v4 但不支持"VM-Exit 时保存 PERF_GLOBAL_CTRL"的 CPU，使用代码手动读取/恢复 PERF_GLOBAL_CTRL

#### 2.4.3 AMD SVM 实现

AMD 平台的 PMU 上下文切换通过代码手动完成，在通用的 x86 KVM PMU 代码中实现（而非 vendor 特定代码）。

### 2.5 PMI（Performance Monitoring Interrupt）处理

#### 2.5.1 专用中断向量

Mediated vPMU 引入了专用的中断向量 **`PERF_GUEST_MEDIATED_PMI_VECTOR`**，用于处理 guest 的 PMI：

- 当 guest 运行且使用 PMU 时，guest 的 PMI 通过此专用向量传递
- PMI 触发 VM-Exit，KVM 随后将 PMI 注入到 guest
- Host 的 PMI 仍然使用 NMI 向量

#### 2.5.2 为什么需要专用向量

在 emulated vPMU 中，host PMI 处理程序在物理 PMI 属于 guest 计数器时通知 KVM 注入虚拟 PMI。但如果在 passthrough 模式下使用相同机制，PMI skid（PMI 可能在 VM-Exit 之后才到达）会导致 host PMI 处理程序无法区分该 PMI 属于 host 还是 guest。专用向量解决了这个歧义问题。

#### 2.5.3 FRED 兼容性

在 v5 中，新的系统中断 `PERF_GUEST_MEDIATED_PMI_VECTOR` 通过 perf（而非 KVM）路由，并与 FRED（Flexible Return and Event Delivery）架构兼容。

### 2.6 Perf 子系统接口

Mediated vPMU 引入了以下 perf 子系统 API，用于 hypervisor 与 perf 之间的交互：

#### 2.6.1 创建/释放 mediated PMU

```c
int perf_create_mediated_pmu(struct pmu *pmu);
void perf_release_mediated_pmu(struct pmu *pmu);
```

- `perf_create_mediated_pmu()`：Hypervisor 调用，创建 mediated PMU 实例
- `perf_release_mediated_pmu()`：释放 mediated PMU 实例
- 在 v5 中从 `perf_{get,put}_mediated_pmu()` 重命名而来，以更好区分上下文切换 API

#### 2.6.2 加载/卸载 guest PMU 上下文

```c
void perf_load_guest_context(struct pmu *pmu, unsigned long data);
void perf_put_guest_context(struct pmu *pmu);
```

- `perf_load_guest_context()`：在 VM-Entry 前调用，停止 host perf event，切换到 guest PMU 上下文
- `perf_put_guest_context()`：在 VM-Exit 后调用，恢复 host PMU 上下文
- `data` 参数在 x86 上传递 guest LVTPC 值（APIC Local Vector Table Performance Counter entry）
- 在 v5 中从 `perf_{guest,host}_{enter,exit}()` 重命名合并而来

#### 2.6.3 PMU 能力标志

```c
#define PERF_PMU_CAP_MEDIATED_VPMU    BIT(...)
```

- 新增 PMU 能力标志，表示 PMU 硬件支持 mediated vPMU
- Intel 和 AMD 的 x86_pmu 驱动分别设置此标志
- 通过 `perf/x86/core` 将能力从 `x86_pmu` 传递到 `x86_pmu_cap`

#### 2.6.4 exclude_guest 支持

- 新增通用的 `exclude_guest` 支持，确保 host perf event 在 guest 运行期间被停止
- 新增 `EVENT_GUEST` 标志用于区分 guest 和 host 的事件上下文
- 新增 `CONFIG_PERF_GUEST_MEDIATED_PMU` 内核配置选项来守护新的 perf 功能

### 2.7 KVM 使能机制

#### 2.7.1 内核参数

通过内核模块参数 `enable_mediated_pmu` 控制：

```bash
modprobe kvm_intel enable_mediated_pmu=Y
modprobe kvm_amd enable_mediated_pmu=Y
```

#### 2.7.2 用户空间使能

在 v4 中，通过 `KVM_CAP_PMU_CAPABILITY` ioctl 实现用户空间动态使能。在 v5 中进一步演进：不再要求用户空间通过 `KVM_CAP_PMU_CAPABILITY` 显式 opt-in，而是在首次 `KVM_CREATE_VCPU` 调用时，如果 VM 拥有 in-kernel local APIC，则自动"创建" mediated PMU。

#### 2.7.3 拦截计算机制

拦截（Interception）的重新计算使用 request 机制和现有的 vendor hooks：
- 检查硬件能力（而非 KVM 能力）来计算 MSR 和 RDPMC 拦截
- 使用 `pmu->version` 检测 vCPU 是否拥有 mediated PMU
- 使用 `kvm_x86_ops` hook 检查 mediated PMU 支持

### 2.8 嵌套虚拟化支持

Mediated vPMU 支持嵌套虚拟化（L2 guest 运行时）：

- **Intel nVMX**：在 L2 运行时，合并 L0/L1 的 MSR 拦截 bitmap，根据需要禁用 PMU MSR 拦截。新增宏 `nested_vmx_merge_msr_bitmaps_{read,write,rw}()` 简化嵌套 MSR 拦截设置
- **AMD nSVM**：在 L2 运行时，适当地禁用 PMU MSR 拦截

### 2.9 整体架构图

```
┌─────────────────────────────────────────────────────────┐
│                      Guest VM                            │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐ │
│  │ Guest Perf   │  │ Guest Kernel  │  │ Guest App     │ │
│  │ Tool         │  │ PMU Subsystem │  │ (RDPMC)       │ │
│  └──────┬───────┘  └───────┬───────┘  └───────┬───────┘ │
│         │                  │                   │         │
│         │   Event Select   │   PMC R/W         │ RDPMC   │
│         │   (intercepted)  │   (passthrough)   │ (条件)   │
├─────────┼──────────────────┼───────────────────┼─────────┤
│         ▼                  ▼                   ▼         │
│  ┌──────────────────────────────────────────────────────┐│
│  │              KVM (Mediated vPMU)                     ││
│  │  ┌────────────────┐  ┌───────────────────────────┐  ││
│  │  │ Event Filter   │  │ PMU Context Switch         │  ││
│  │  │ (eventsel 拦截) │  │ (VM-Entry/Exit 保存/恢复)  │  ││
│  │  └────────────────┘  └───────────────────────────┘  ││
│  │  ┌────────────────┐  ┌───────────────────────────┐  ││
│  │  │ PMI Handler    │  │ Nested Virt Support        │  ││
│  │  │ (专用向量)      │  │ (nVMX/nSVM)                │  ││
│  │  └────────────────┘  └───────────────────────────┘  ││
│  └──────────────────────────────────────────────────────┘│
│                          │                               │
│  ┌───────────────────────┼─────────────────────────────┐│
│  │              Perf Subsystem                          ││
│  │  ┌──────────────┐  ┌──────────────┐  ┌───────────┐  ││
│  │  │create/release│  │load/put      │  │exclude_   │  ││
│  │  │mediated_pmu()│  │guest_context()│ │guest support│ ││
│  │  └──────────────┘  └──────────────┘  └───────────┘  ││
│  └──────────────────────────────────────────────────────┘│
│                          │                               │
│  ┌───────────────────────┼─────────────────────────────┐│
│  │              PMU Hardware                            ││
│  │  PMC0-N  │  Fixed PMCs  │  PERF_GLOBAL_CTRL  │ ...  ││
│  └──────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────┘
```

---

## 3. 代码实现 Patch List

### 3.1 版本演进

| 版本 | 发布日期 | Patch 数量 | 发布者 | 关键变化 |
|---|---|---|---|---|
| RFC v1 | 2024-01-26 | 41 | Xiong Zhang (Intel) | 初始 RFC，仅 Intel 支持 |
| v2 | 2024-05-06 | 54 | Mingwei Zhang (Google) | 新增 AMD 支持，完整 x86 架构覆盖 |
| v3 | 2024-08-01 | - | Mingwei Zhang (Google) | 中间迭代 |
| v4 | 2025-03-24 | 38 | Mingwei Zhang (Google) | 重命名为"mediated"，动态使能，约束到 SPR+ |
| v5 | 2025-08-06 | 44 | Sean Christopherson (Google) | 大规模重构，API 重命名，自动创建 mediated PMU |
| v6 | 2025-12-05 | 44 | Sean Christopherson (Google) | 恢复 pre-SPR 支持，LVTPC API，RDPMC 解耦 |

### 3.2 v6 Patch List（最终版本，44 个 Patch）

基于 `kvm-x86/linux next` 分支，目标内核版本 6.19+ 合并窗口。Perf 变更通过 tip 树合入，KVM 变更通过 kvm-x86 树合入。

#### 3.2.1 Perf 子系统变更（10 个 Patch）

**Kan Liang (7 patches):**

1. `perf: Skip pmu_ctx based on event_type` — 基于 event_type 跳过 pmu_ctx
2. `perf: Add generic exclude_guest support` — 添加通用 exclude_guest 支持
3. `perf: Add APIs to create/release mediated guest vPMUs` — 创建/释放 mediated vPMU 的 API
4. `perf: Clean up perf ctx time` — 清理 perf 上下文时间跟踪，引入 `struct perf_time_ctx`
5. `perf: Add a EVENT_GUEST flag` — 添加 EVENT_GUEST 标志
6. `perf: Add APIs to load/put guest mediated PMU context` — 加载/卸载 guest mediated PMU 上下文的 API
7. `perf/x86/intel: Support PERF_PMU_CAP_MEDIATED_VPMU` — Intel PMU 支持 mediated vPMU 能力标志

**Sandipan Das (2 patches):**

8. `perf/x86/core: Do not set bit width for unavailable counters` — 不为不可用计数器设置位宽
9. `perf/x86/amd: Support PERF_PMU_CAP_MEDIATED_VPMU for AMD host` — AMD PMU 支持 mediated vPMU 能力标志

**Mingwei Zhang (1 patch):**

10. `perf/x86/core: Plumb mediated PMU capability from x86_pmu to x86_pmu_cap` — 将 mediated PMU 能力从 x86_pmu 传递到 x86_pmu_cap

#### 3.2.2 Perf/x86 中断处理变更（2 个 Patch，Sean Christopherson）

11. `perf/x86/core: Register a new vector for handling mediated guest PMIs` — 注册新的中断向量 `PERF_GUEST_MEDIATED_PMI_VECTOR` 处理 guest PMI
12. `perf/x86/core: Add APIs to switch to/from mediated PMI vector (for KVM)` — 添加切换到/从 mediated PMI 向量的 API

#### 3.2.3 通用 Perf 清理（1 个 Patch，Sean Christopherson）

13. `perf: Move security_perf_event_free() call to __free_event()` — 将 security_perf_event_free() 调用移动到 __free_event()

#### 3.2.4 KVM 核心变更（2 个 Patch）

14. `KVM: Add a simplified wrapper for registering perf callbacks` — 简化 perf 回调注册包装器（Sean Christopherson）
15. `include/linux/kvm_host.h` — KVM host 头文件变更（ mediated PMU 相关结构体和声明）

#### 3.2.5 KVM x86 PMU 核心变更（11 个 Patch，Dapeng Mi）

16. `KVM: x86/pmu: Start stubbing in mediated PMU support` — 开始引入 mediated PMU 支持框架
17. `KVM: x86/pmu: Implement Intel mediated PMU requirements and constraints` — 实现 Intel mediated PMU 需求和约束
18. `KVM: x86/pmu: Disable RDPMC interception for compatible mediated vPMU` — 为兼容的 mediated vPMU 禁用 RDPMC 拦截
19. `KVM: x86/pmu: Load/save GLOBAL_CTRL via entry/exit fields for mediated PMU` — 通过 VMCS entry/exit 字段加载/保存 PERF_GLOBAL_CTRL
20. `KVM: x86/pmu: Disable interception of select PMU MSRs for mediated vPMUs` — 为 mediated vPMU 禁用特定 PMU MSR 的拦截
21. `KVM: x86/pmu: Bypass perf checks when emulating mediated PMU counter accesses` — 模拟 mediated PMU 计数器访问时绕过 perf 检查
22. `KVM: x86/pmu: Reprogram mediated PMU event selectors on event filter updates` — 事件过滤器更新时重新编程 mediated PMU 事件选择器
23. `KVM: x86/pmu: Load/put mediated PMU context when entering/exiting guest` — 进入/退出 guest 时加载/卸载 mediated PMU 上下文
24. `KVM: x86/pmu: Handle emulated instruction for mediated vPMU` — 处理 mediated vPMU 的模拟指令
25. `KVM: x86/pmu: Expose enable_mediated_pmu parameter to user space` — 向用户空间暴露 enable_mediated_pmu 参数
26. `KVM: x86/pmu: Register PMI handler for mediated vPMU` (Xiong Zhang) — 为 mediated vPMU 注册 PMI 处理器

#### 3.2.6 KVM x86 PMU 其他变更（4 个 Patch）

27. `KVM: x86/pmu: Snapshot host (i.e. perf's) reported PMU capabilities` (Sean Christopherson) — 快照 host 报告的 PMU 能力
28. `KVM: x86/pmu: Introduce eventsel_hw to prepare for pmu event filtering` (Mingwei Zhang) — 引入 eventsel_hw 为 PMU 事件过滤做准备
29. `KVM: x86/pmu: Implement AMD mediated PMU requirements` (Sean Christopherson) — 实现 AMD mediated PMU 需求
30. `KVM: x86/pmu: Always stuff GuestOnly=1,HostOnly=0 for mediated PMCs on AMD` (Sandipan Das) — AMD 上始终设置 GuestOnly=1, HostOnly=0

#### 3.2.7 KVM x86 PMU 优化与安全（3 个 Patch，Sean Christopherson）

31. `KVM: x86/pmu: Disallow emulation in the fastpath if mediated PMCs are active` — 如果 mediated PMC 处于活跃状态，禁止 fastpath 中的模拟
32. `KVM: x86/pmu: Elide WRMSRs when loading guest PMCs if values already match` — 加载 guest PMC 时如果值已匹配则跳过 WRMSR
33. `KVM: x86/pmu: Snapshot host (i.e. perf's) reported PMU capabilities` — (已合并到上述)

#### 3.2.8 嵌套虚拟化变更（3 个 Patch）

34. `KVM: nVMX: Disable PMU MSR interception as appropriate while running L2` (Mingwei Zhang) — L2 运行时适当地禁用 PMU MSR 拦截
35. `KVM: nVMX: Add macros to simplify nested MSR interception setting` (Dapeng Mi) — 添加宏简化嵌套 MSR 拦截设置
36. `KVM: nSVM: Disable PMU MSR interception as appropriate while running L2` (Sean Christopherson) — AMD 嵌套虚拟化中适当地禁用 PMU MSR 拦截

#### 3.2.9 VMX MSR Auto-Load 清理与优化（10 个 Patch，Sean Christopherson）

37. `KVM: VMX: Drop intermediate "guest" field from msr_autostore` — 移除 msr_autostore 中的中间 "guest" 字段
38. `KVM: nVMX: Don't update msr_autostore count when saving TSC for vmcs12` — 保存 TSC 时不更新 msr_autostore 计数
39. `KVM: VMX: Dedup code for removing MSR from VMCS's auto-load list` — 去重从 VMCS auto-load 列表移除 MSR 的代码
40. `KVM: VMX: Drop unused @entry_only param from add_atomic_switch_msr()` — 移除 add_atomic_switch_msr() 中未使用的 @entry_only 参数
41. `KVM: VMX: Bug the VM if either MSR auto-load list is full` — 如果任一 MSR auto-load 列表已满则触发 Bug
42. `KVM: VMX: Set MSR index auto-load entry if and only if entry is "new"` — 仅当条目为"new"时设置 MSR index auto-load 条目
43. `KVM: VMX: Compartmentalize adding MSRs to host vs. guest auto-load list` — 将添加 MSR 到 host/guest auto-load 列表的代码分区化
44. `KVM: VMX: Dedup code for adding MSR to VMCS's auto list` — 去重添加 MSR 到 VMCS auto 列表的代码
45. `KVM: VMX: Initialize vmcs01.VM_EXIT_MSR_STORE_ADDR with list address` — 用列表地址初始化 vmcs01.VM_EXIT_MSR_STORE_ADDR
46. `KVM: VMX: Add mediated PMU support for CPUs without "save perf global ctrl"` — 为不支持"VM-Exit 保存 PERF_GLOBAL_CTRL"的 CPU 添加 mediated PMU 支持

### 3.3 代码统计

| 统计项 | 数值 |
|---|---|
| 总 Patch 数 | 44 |
| 修改文件数 | 38 |
| 新增行数 | +1396 |
| 删除行数 | -283 |
| Patch 作者数 | 6 |

### 3.4 Patch 作者贡献

| 作者 | 所属公司 | Patch 数量 |
|---|---|---|
| Sean Christopherson | Google | 19 |
| Dapeng Mi | Intel | 11 |
| Kan Liang | Intel | 7 |
| Mingwei Zhang | Google | 3 |
| Sandipan Das | AMD | 3 |
| Xiong Zhang | Intel | 1 |

### 3.5 主要修改文件

| 文件路径 | 变更行数 | 说明 |
|---|---|---|
| `kernel/events/core.c` | +517/-... | Perf 核心逻辑：mediated PMU API、exclude_guest、上下文切换 |
| `arch/x86/kvm/pmu.c` | +271 | KVM PMU 核心逻辑：mediated PMU 支持、上下文切换、事件过滤 |
| `arch/x86/kvm/vmx/vmx.c` | +212 | VMX 逻辑：MSR auto-load 管理、拦截控制 |
| `arch/x86/kvm/vmx/nested.c` | +144/-... | 嵌套虚拟化：L2 PMU MSR 拦截合并 |
| `arch/x86/kvm/svm/svm.c` | +46 | AMD SVM 逻辑：PMU MSR 拦截 |
| `arch/x86/kvm/x86.c` | +54 | 通用 x86 KVM：PMU 能力检查 |
| `arch/x86/events/core.c` | +37 | x86 perf 核心：PMI 向量注册、能力传递 |
| `arch/x86/kvm/svm/pmu.c` | +44 | AMD KVM PMU：mediated PMU 需求 |
| `arch/x86/kvm/vmx/pmu_intel.c` | +92 | Intel KVM PMU：mediated PMU 需求 |
| `include/linux/perf_event.h` | +35 | Perf 头文件：新 API 声明、数据结构 |
| `include/linux/kvm_host.h` | +11 | KVM 头文件：mediated PMU 相关字段 |

### 3.6 QEMU 配套 Patch

QEMU 侧也有配套 patch 系列用于支持 mediated vPMU：
- v4 配套 QEMU patch: [https://lore.kernel.org/all/20250324123712.34096-1-dapeng1.mi@linux.intel.com](https://lore.kernel.org/all/20250324123712.34096-1-dapeng1.mi@linux.intel.com)
- 由 Dapeng Mi (Intel) 发布

---

## 4. 热迁移支持情况

### 4.1 当前状态

截至 v6 patch 系列，**mediated vPMU 的热迁移（Live Migration）支持尚未在 patch 系列中明确实现**。在 patch 系列的 cover letter 和讨论中，热迁移没有被作为独立特性提及。

### 4.2 热迁移面临的技术挑战

Mediated vPMU 的热迁移存在以下技术挑战：

1. **PMU 硬件状态同步**：Mediated vPMU 模式下，guest 直接使用 PMU 硬件，PMU MSR 值（计数器值、事件选择器配置、全局控制寄存器等）需要在源端和目标端之间正确同步

2. **CPU 微架构差异**：不同 CPU 型号的 PMU 版本、计数器数量、可用事件可能不同，源端和目标端的 PMU 硬件能力必须兼容

3. **Perf 子系统状态一致性**：源端 host 的 perf 子系统状态（如 exclude_guest event 的停止/恢复）需要在迁移后正确重建

4. **PMI 处理**：迁移过程中可能存在未处理的 PMI，需要确保迁移后正确投递

### 4.3 可行的迁移策略

虽然 patch 系列未直接实现热迁移，但理论上可行的策略包括：

- **在迁移前切换回 emulated 模式**：迁移前将 mediated vPMU 降级为 emulated vPMU，迁移后在目标端重新启用 mediated vPMU
- **要求源端和目标端 PMU 能力一致**：通过 CPU 型号检查确保两端 PMU 硬件兼容
- **保存/恢复 PMU MSR 状态**：在迁移过程中保存 guest 的所有 PMU MSR 值并在目标端恢复

### 4.4 社区讨论

在社区讨论中，热迁移被认为是 mediated vPMU 生产化使用需要解决的重要问题之一，但在初始合并版本中不是优先目标。初始版本重点关注功能正确性和性能优化。

---

## 5. 适用的 CPU 平台

### 5.1 Intel 平台

| CPU 平台 | 支持状态 | 说明 |
|---|---|---|
| Sapphire Rapids (SPR) | ✅ 完整支持 | v4 起的基准平台，支持 VMCS PERF_GLOBAL_CTRL 自动保存/恢复 |
| Emerald Rapids (EMR) | ✅ 完整支持 | 与 SPR 同架构世代 |
| Granite Rapids (GRS/GRN) | ✅ 完整支持 | v4 测试中通过（PEBS 测试有无关故障） |
| Ice Lake (ICX) | ✅ 支持 (v6新增) | PMU v4，支持 mediated vPMU |
| Skylake (SKX) | ⚠️ 部分支持 | v2 测试中有已知故障（TSX cycles 相关），v6 恢复 pre-SPR 支持后可能改善 |
| Pre-SPR (PMU v4) | ✅ 支持 (v6新增) | v6 恢复了对 PMU v4 但不支持"VM-Exit 保存 PERF_GLOBAL_CTRL"的 CPU 的支持 |

**关键演进：**
- v4 版本将 Intel 侧支持约束到 Sapphire Rapids 及以后（因为放弃了 MSR save/restore list 方式，仅使用 VMCS exec_ctrl 方式保存 PERF_GLOBAL_CTRL）
- v6 版本恢复了 pre-SPR Intel CPU 支持（PMU v4 但无"save PERF_GLOBAL_CTRL on VM-Exit"能力的 CPU），通过代码手动处理

### 5.2 AMD 平台

| CPU 平台 | 支持状态 | 说明 |
|---|---|---|
| Genoa (Zen 4) | ✅ 支持 | v2 起的主要测试平台 |
| Turin (Zen 5) | ✅ 支持 | v6 修复了 Turin 拼写错误 |
| Milan (Zen 3) | ⚠️ 已知问题 | v2 测试中 pmu_event_filter_test 有偏差问题 |
| PerfMon v1 | ✅ 支持 | AMD 基础性能监控 |
| PerfMon v2 | ✅ 支持 | AMD 高级性能监控 |

**AMD 特殊处理：**
- AMD CPU 存在需要拦截 PERF_GLOBAL_CTRL 但不需要拦截所有 PMC 访问的场景（v6 中将 RDPMC 拦截与 PERF_GLOBAL_CTRL 拦截解耦）
- AMD mediated PMC 始终设置 GuestOnly=1, HostOnly=0

### 5.3 PMU 版本要求

| PMU 版本 | 架构 | 支持状态 |
|---|---|---|
| Intel PMU v4 | Intel | ✅ 支持（v6 起包含 pre-SPR） |
| Intel PMU v5+ | Intel | ✅ 支持（SPR 及以后） |
| AMD PerfMon v1 | AMD | ✅ 支持 |
| AMD PerfMon v2 | AMD | ✅ 支持 |

### 5.4 测试平台汇总

根据 RFC v2 和 v4 的测试报告：

| 平台 | 架构 | 测试版本 | 结果 |
|---|---|---|---|
| Genoa | AMD Zen 4 | v2 | 通过 |
| Skylake | Intel | v2 | 部分失败（TSX cycles） |
| Icelake | Intel | v2 | 通过 |
| Sapphire Rapids | Intel | v2/v4 | 通过 |
| Emerald Rapids | Intel | v2 | 通过 |
| Granite Rapids | Intel | v4 | 基本通过（PEBS 无关故障） |

---

## 6. 特性约束与限制

### 6.1 Host 侧 Perf Event 约束

#### 6.1.1 exclude_guest 要求

- **带有 `exclude_guest=1` 标志的 host perf event**：在 guest 运行期间被停止，VM-Exit 后恢复运行。这是预期行为
- **不带 `exclude_guest` 标志的 host perf event**：
  - VM 启动后，这类 event **被阻止创建**
  - 如果 VM 启动时这类 event 已存在，**VM 无法启动**
  - 在 v5 中，`exclude_guest` 属性在 perf 工具创建 event 时默认设置

#### 6.1.2 NMI Watchdog 限制

- NMI watchdog 的 perf event 是 system-wide cpu pinned event，在 guest 运行期间也会被停止
- NMI watchdog 的 perf event 没有 `exclude_guest=1` 标志，需要在 RFC 中特殊添加
- 这意味着 **NMI watchdog 在 guest 运行期间失去功能**
- 替代方案讨论：
  - Buddy hardlock detector：可靠性不足
  - HPET-based hardlock detector：尚未进入上游内核
- 实际使用建议：`echo 0 > /proc/sys/kernel/nmi_watchdog`

### 6.2 Host 无法分析 Guest

- **核心限制**：启用 mediated vPMU 后，host 用户**失去从 host 侧分析 guest 的能力**
- 如果用户需要从 host 侧分析 guest，**不应启用 mediated vPMU 模式**
- 这是 mediated vPMU 设计的固有 trade-off：用 host 分析能力换取 guest PMU 性能

### 6.3 CPU 平台约束

- **Intel 侧**：v4 曾约束到 Sapphire Rapids 及以后（因 PERF_GLOBAL_CTRL 保存/恢复方式限制），v6 恢复了 pre-SPR 支持（PMU v4）
- **AMD 侧**：支持 PerfMon v1 和 v2
- 需要硬件支持 `PERF_PMU_CAP_MEDIATED_VPMU` 能力标志

### 6.4 配置依赖

- 内核需启用 `CONFIG_PERF_GUEST_MEDIATED_PMU` 配置选项（v5 新增）
- KVM x86 需启用 `CONFIG_KVM_INTEL` 或 `CONFIG_KVM_AMD`
- 需要内核模块参数 `enable_mediated_pmu=Y`

### 6.5 嵌套虚拟化约束

- 嵌套虚拟化（L2 运行）时，PMU MSR 拦截 bitmap 需要在 L0/L1 之间正确合并
- L1 hypervisor 的 PMU 拦截设置会影响 L2 的 PMU MSR 访问行为

### 6.6 QEMU 配套要求

- 运行 mediated vPMU 需要配套的 QEMU patch 系列
- QEMU 需要正确配置 CPU 模型和 PMU 相关参数

### 6.7 功能限制

- 初始版本未实现热迁移支持
- 初始版本未实现 PEBS passthrough（但设计上为此铺平了道路）
- 初始版本未实现 LBR passthrough（但设计上为此铺平了道路）
- v6 发布者 Sean Christopherson 坦言："我手动验证了 MSR/PMC 按预期直通，但还没有真正在 guest 中大量使用 PMU"

### 6.8 上下文切换开销

- 每次 VM-Exit 都会产生适度的 PMU 寄存器读写开销
- 社区曾讨论将上下文切换移到 VCPU_RUN 循环边界以减少开销，但因无法分析 VCPU_RUN 内的 KVM 代码而保留在 VM-Entry/Exit 边界
- v5 中新增了优化：加载 guest PMC 时如果值已匹配则跳过 WRMSR（elide WRMSRs）

---

## 7. 关键 Review 意见

### 7.1 命名规范：从 "passthrough" 到 "mediated"（v4）

**提出者**：Sean Christopherson (Google)

**意见内容**：在 v4 中，Sean 要求将所有 patch 中的关键词 "passthrough" 改为 "mediated"。这符合虚拟化中 "mediated passthrough" 的标准定义——拦截控制操作（如事件选择器），同时允许数据操作直通。

**影响**：整个 patch 系列的命名、变量名、函数名、commit message 全部从 "passthrough" 更改为 "mediated"，包括：
- `perf_get/put_passthrough_pmu()` → `perf_create/release_mediated_pmu()`
- `perf_guest/host_enter/exit()` → `perf_load/put_guest_context()`
- 内核参数 `enable_passthrough_pmu` → `enable_mediated_pmu`
- 尽可能清除所有 "passthrough" 字样

### 7.2 使能方式：从静态使能到动态使能（v4）

**提出者**：Sean Christopherson (Google)

**意见内容**：要求将 mediated vPMU 的使能方式从内核模块参数静态使能改为用户空间通过 `KVM_CAP_PMU_CAPABILITY` ioctl 动态使能，实现 per-VM 粒度的控制。

**影响**：v4 实现了基于 `KVM_CAP_PMU_CAPABILITY` 的动态使能；v5 进一步演进为自动创建——不再要求用户空间显式 opt-in，而是在首次 `KVM_CREATE_VCPU` 调用时自动创建 mediated PMU。

### 7.3 PERF_GLOBAL_CTRL 保存/恢复约束（v4）

**提出者**：Sean Christopherson (Google)

**意见内容**：仅支持通过 VMCS execution control 字段保存/恢复 PERF_GLOBAL_CTRL，放弃 MSR save/restore list 方式。因此 mediated vPMU 在 Intel 侧被约束到 Sapphire Rapids 及以后。

**影响**：v4 将 Intel 侧支持限制在 SPR+；v6 通过新增 patch "KVM: VMX: Add mediated PMU support for CPUs without 'save perf global ctrl'" 恢复了 pre-SPR 支持。

### 7.4 RDPMC 拦截策略（v2）

**提出者**：Jim Mattson (Google) 和 Sean Christopherson (Google)

**意见内容**：RFC v1 中直通 RDPMC 并将未暴露计数器值清零的 hack 方式被否决。要求仅在所有计数器都暴露时才直通 RDPMC，否则必须拦截。

**影响**：v2 起实现了更安全的 RDPMC 拦截策略——仅在所有 PMU 计数器都暴露给 guest 时才直通 RDPMC。

### 7.5 RDPMC 与 PERF_GLOBAL_CTRL 拦截解耦（v6）

**提出者**：Sandipan Das (AMD)

**意见内容**：AMD CPU 存在需要拦截 PERF_GLOBAL_CTRL 但不需要拦截所有 PMC 访问的场景，不应将 RDPMC 拦截与 PERF_GLOBAL_CTRL 拦截绑定。

**影响**：v6 将 RDPMC 拦截与 PERF_GLOBAL_CTRL 拦截解耦，分别处理。

### 7.6 PMI 向量路由方式（v5）

**提出者**：Sean Christopherson (Google)

**意见内容**：新的系统中断 `PERF_GUEST_MEDIATED_PMI_VECTOR` 应该通过 perf（而非 KVM）路由，并与 FRED 架构兼容。

**影响**：v5 将 PMI 向量处理从 KVM 移至 perf 子系统，确保与 FRED 的兼容性。

### 7.7 API 重命名和简化（v5）

**提出者**：Sean Christopherson (Google)

**意见内容**：对 perf API 进行大规模重命名和简化：
- `perf_{guest,host}_{enter,exit}()` → `perf_{load,put}_guest_context()`
- `perf_{get,put}_mediated_pmu()` → `perf_{create,release}_mediated_pmu()`
- load/put API 参数从 `u32 guest_lvtpc` 改为 `unsigned long data`，解耦架构相关代码
- 在通用 x86 代码中（而非 vendor 代码）上下文切换 PMC 和事件选择器

**影响**：API 更清晰、更通用，降低了维护复杂度。

### 7.8 嵌套虚拟化 changelog 措辞（v4）

**提出者**：Sean Christopherson (Google)

**意见内容**：在 review v4 patch 32/38（KVM: nVMX: Add nested virtualization support for mediated PMU）时，Sean 纠正了 changelog 的措辞——"不要以'启用 KVM 特性'的方式描述与嵌套虚拟化相关的 changelog"。patch 被重命名为 "KVM: nVMX: Disable PMU MSR interception as appropriate while running L2"。

**影响**：嵌套虚拟化相关 patch 的描述更加准确，强调的是在 L2 运行时适当地调整 MSR 拦截，而非"启用嵌套特性"。

### 7.9 Perf 上下文切换中的完全禁用（v5）

**提出者**：Kan Liang (Intel) 和 Namhyung Kim (Google)

**意见内容**：在 `perf_{load,put}_guest_context()` 切换 guest/host 上下文时，必须确保 PMU 被完全禁用。

**影响**：v5 确保了上下文切换期间 PMU 的完全禁用，避免了潜在的计数器污染。

### 7.10 LVTPC 更新 API（v6）

**提出者**：Peter Zijlstra (Intel)

**意见内容**：需要一个 x86-only API 在 mediated vPMU 加载/卸载时更新 LVTPC entry。

**影响**：v6 新增了 x86-only API 用于更新 LVTPC entry。

### 7.11 VMCS MSR Auto-Load 列表清理（v5-v6）

**提出者**：Sean Christopherson (Google)

**意见内容**：对 VMX MSR auto-load 列表的管理代码进行了大规模清理和去重，包括：
- 移除中间 "guest" 字段
- 去重移除/添加 MSR 的代码
- 如果 auto-load 列表已满则触发 Bug
- 仅当条目为 "new" 时才设置
- 将 host/guest auto-load 列表操作分区化

**影响**：代码更清晰、更可维护，减少了重复代码和潜在 bug。

### 7.12 exclude_guest event 的错误处理改进（v2）

**提出者**：Sean Christopherson (Google)

**意见内容**：RFC v1 中，不带 `exclude_guest` 的 host perf event 在 VM 启动后会进入 error 状态且无法恢复。这严重影响 host perf 子系统。v2 改进为：确保 VM 启动前不存在 `!exclude_guest` event，且 VM 运行期间阻止创建 `!exclude_guest` event。

**影响**：v2 改进了错误处理策略，避免了不可恢复的 event 错误状态。

---

## 附录

### A. 参考资料

1. **v6 Cover Letter (Sean Christopherson)**: [KVM: x86: Add support for mediated vPMUs](https://lwn.net/Articles/1049588/)
2. **RFC v1 Cover Letter (Xiong Zhang)**: [https://lore.kernel.org/all/20240126085444.324918-1-xiong.y.zhang@linux.intel.com/](https://lore.kernel.org/all/20240126085444.324918-1-xiong.y.zhang@linux.intel.com/)
3. **v2 Cover Letter (Mingwei Zhang)**: [https://lore.kernel.org/all/20240506053020.3911940-1-mizhang@google.com/](https://lore.kernel.org/all/20240506053020.3911940-1-mizhang@google.com/)
4. **v4 Patch Series**: [https://patchew.org/linux/20250324173121.1275209-1-mizhang@google.com/](https://patchew.org/linux/20250324173121.1275209-1-mizhang@google.com/)
5. **v5 Patch Series**: [https://patchew.org/linux/20250806195706.1650976-1-seanjc@google.com/](https://patchew.org/linux/20250806195706.1650976-1-seanjc@google.com/)
6. **v6 Patch Series**: [https://patchew.org/linux/20251206001720.468579-1-seanjc@google.com/](https://patchew.org/linux/20251206001720.468579-1-seanjc@google.com/)
7. **LPC 2024 演讲**: [Mediated passthrough vPMU for KVM](https://lpc.events/event/18/contributions/1765/)
8. **v6 Git 仓库**: [https://github.com/sean-jc/linux.git tags/mediated-vpmu-v6](https://github.com/sean-jc/linux.git)
9. **QEMU 配套 Patch**: [https://lore.kernel.org/all/20250324123712.34096-1-dapeng1.mi@linux.intel.com](https://lore.kernel.org/all/20250324123712.34096-1-dapeng1.mi@linux.intel.com)
10. **KVM Forum 2019 - Efficient Performance Monitoring with Virtual PMUs**: [PDF](https://static.sched.com/hosted_files/kvmforum2019/9e/Efficient%20Performance%20Monitoring%20in%20the%20Cloud%20with%20Virtual%20PMUs%20%28KVM%20Forum%202019%29.pdf)

### B. 贡献者列表

| 姓名 | 公司 |
|---|---|
| Sean Christopherson | Google |
| Mingwei Zhang | Google |
| Jim Mattson | Google |
| Stephane Eranian | Google |
| Ian Rogers | Google |
| Dapeng Mi | Intel |
| Kan Liang | Intel |
| Xiong Zhang | Intel |
| Zhenyu Wang | Intel |
| Samantha Alt | Intel |
| Xudong Hao | Intel |
| Sandipan Das | AMD |
| Manali Shukla | AMD |
| Nikunj Dadhania | AMD |
| Santosh Shukla | AMD |
| Peter Zijlstra | Community |
| Namhyung Kim | Community |
| Paolo Bonzini | Community |
| Bibo Mao | Community |
| Zide Chen | Community |

### C. 版本时间线

```
2024-01-26  RFC v1 (41 patches, Xiong Zhang, Intel)
    │
2024-05-06  v2 (54 patches, Mingwei Zhang, Google) — 新增 AMD 支持
    │
2024-08-01  v3 (Mingwei Zhang, Google)
    │
2024-09-19  LPC 2024 演讲 (Mingwei Zhang, Vienna)
    │
2025-03-24  v4 (38 patches, Mingwei Zhang, Google) — 重命名 "mediated"，动态使能
    │
2025-03-24  QEMU 配套 patch (Dapeng Mi, Intel)
    │
2025-05-14  Sean Christopherson 全面 review v4
    │
2025-08-06  v5 (44 patches, Sean Christopherson, Google) — 大规模重构
    │
2025-12-05  v6 (44 patches, Sean Christopherson, Google) — 恢复 pre-SPR，最终版本
    │
    ▼
  目标: Linux 6.19+ / 6.20 合并窗口
  (Perf 变更通过 tip 树，KVM 变更通过 kvm-x86 树)
```
