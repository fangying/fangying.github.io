---
Title: AMD AVIC and X2AVIC
Date: 2026-7-30 23:00
Modified: 2026-7-30 23:00
Tags: virtualization, amd, avic, x2avic
Slug: amd-avic-x2avic
Status: published
Authors: Yori Fang
Summary: AMD AVIC/x2AVIC hardware virtualization design and implementation analysis based on AMD APM Vol.2 and Linux KVM-SVM source code
---

# AMD AVIC 的设计与实现分析文档

> 基于 AMD64 Architecture Programmer's Manual Volume 2 (Section 15.29) 及 Linux Kernel KVM-SVM 源码分析
>
> 适用于系统虚拟化领域技术调研

---

## 目录

1. [背景与动机](#1-背景与动机)
2. [AVIC 架构概览](#2-avic-架构概览)
3. [AVIC 核心数据结构](#3-avic-核心数据结构)
4. [VMCB 控制字段](#4-vmcb-控制字段)
5. [IPI 虚拟化流程](#5-ipi-虚拟化流程)
6. [设备中断虚拟化（IOMMU AVIC / GA 模式）](#6-设备中断虚拟化iommu-avic--ga-模式)
7. [x2AVIC 扩展](#7-x2avic-扩展)
8. [Secure AVIC（SEV-SNP 环境）](#8-secure-avicsev-snp-环境)
9. [KVM 代码实现详解](#9-kvm-代码实现详解)
10. [已知硬件 Erratum](#10-已知硬件-erratum)
11. [AVIC vs x2AVIC vs Secure AVIC 对比](#11-avic-vs-x2avic-vs-secure-avic-对比)
12. [参考文献](#12-参考文献)

---

## 1. 背景与动机

### 1.1 传统中断虚拟化的瓶颈

在传统 AMD SVM（Secure Virtual Machine）虚拟化中，所有与 Local APIC 相关的操作（如读写 APIC 寄存器、发送 IPI）都会触发 **VM-Exit**，由 KVM 软件模拟。这种模式带来显著的性能开销：

- **每次 APIC 寄存器访问** → VM-Exit → KVM 模拟 → VM-Entry 返回 Guest
- **每次 IPI 发送** → VM-Exit → KVM 遍历目标 vCPU → 软件注入中断 → 可能再次 VM-Exit 唤醒目标 vCPU
- **设备中断投递**（直通场景）→ IOMMU 中断到 Host → KVM 注入 → VM-Entry

在高中断频率场景（如网络密集型 workload、多 vCPU 通信）下，VM-Exit 开销成为虚拟化性能的关键瓶颈。

### 1.2 AVIC 的设计目标

AMD AVIC（Advanced Virtual Interrupt Controller）通过**硬件虚拟化 Local APIC**，大幅减少 VM-Exit：

| 场景 | 传统模式 | AVIC 模式 |
|------|----------|-----------|
| Guest 读 APIC 寄存器 | VM-Exit → KVM 模拟 | 硬件直接从 vAPIC 页读取，无 VM-Exit |
| Guest 写部分 APIC 寄存器 | VM-Exit → KVM 模拟 | 硬件直接写入 vAPIC 页，无 VM-Exit |
| Guest 发送 IPI（目标 vCPU 正在运行） | VM-Exit → KVM 软件投递 | 硬件直接设置目标 vAPIC 页的 IRR + Doorbell 通知 |
| 设备中断投递（直通） | IOMMU → Host → KVM 注入 | IOMMU GA 模式直接写入 vAPIC 页 |

**CPUID 检测**：`Fn8000_000A EDX[3]` 表示 AVIC 支持，`EDX[14]` 表示 x2AVIC 支持。

> **前提条件**：AVIC 要求 NPT（Nested Page Table，嵌套页表）必须启用。AVIC 硬件需要通过 NPT 来检查权限并定位 vAPIC Backing Page。

---

## 2. AVIC 架构概览

AVIC 硬件通过以下机制实现 APIC 虚拟化：

```
┌─────────────────────────────────────────────────────────────┐
│                      Guest vCPU                              │
│                                                             │
│   ┌─────────────┐    ┌──────────────────────────┐           │
│   │  Local APIC  │◄──►│  vAPIC Backing Page     │           │
│   │  (MMIO/MSR)  │    │  (per-vCPU, 4KB)        │           │
│   └──────┬───────┘    └──────────┬──────────────┘           │
│          │                        │                          │
└──────────┼────────────────────────┼──────────────────────────┘
           │                        │
     ┌──────▼───────┐        ┌──────▼──────────────────┐
     │  AVIC 硬件    │───────►│  Physical APIC ID Table  │
     │  (in CPU)    │        │  (per-VM)                │
     │              │        │  ┌────────────────────┐   │
     │              │        │  │ Entry[0] (vCPU 0)  │   │
     │              │        │  │ Entry[1] (vCPU 1)  │   │
     │              │        │  │ ...                │   │
     │              │        │  │ Entry[N] (vCPU N)  │   │
     │              │        │  └────────────────────┘   │
     │              │        └──────────────────────────┘
     │              │
     │              │        ┌──────────────────────────┐
     │              │───────►│  Logical APIC ID Table   │
     │              │        │  (per-VM, 4KB)           │
     │              │        │  (仅 xAPIC 模式使用)      │
     └──────────────┘        └──────────────────────────┘
            │
            │ Doorbell (MSR)
            ▼
     ┌──────────────┐
     │ 目标 pCPU    │
     │ (目标 vCPU   │
     │  正在运行)   │
     └──────────────┘
```

### AVIC 硬件处理流程（Guest 发送 IPI 时）

```
Guest 写 ICR (ICRL/ICRH)
        │
        ▼
   ┌────────────────────┐
   │ AVIC 硬件拦截      │
   │ (不需 VM-Exit)    │
   └────────┬───────────┘
            │
            ▼
   ┌────────────────────────────────┐
   │ 1. 解析 IPI 目标 (Physical/   │
   │    Logical 地址模式)           │
   │ 2. 查 Physical APIC ID Table  │
   │    定位目标 vCPU               │
   │ 3. 判断目标 vCPU 是否在运行    │
   │    (IsRunning 位)              │
   └────────┬───────────────────────┘
            │
     ┌──────┴──────┐
     │             │
     ▼             ▼
 IsRunning=1    IsRunning=0
     │             │
     ▼             ▼
 设置目标 vAPIC  设置目标 vAPIC
 IRR 位          IRR 位
     │             │
     ▼             ▼
 写 Doorbell MSR  触发
 (目标 pCPU)      AVIC_INCOMPLETE_IPI
     │             VM-Exit (源 vCPU)
     ▼             │
 目标 pCPU         ▼
 收到 Doorbell    KVM 处理:
 → 评估 vIRR      唤醒/调度目标 vCPU
 → 注入中断
```

---

## 3. AVIC 核心数据结构

AVIC 依赖三个关键数据结构，这些在 AMD APM Volume 2 Section 15.29 中有详细描述。

### 3.1 vAPIC Backing Page（虚拟 APIC 背ing页）

- **粒度**：per-vCPU，每个 vCPU 一个 4KB 页面
- **作用**：作为 Guest Local APIC 寄存器的硬件级影子页面
- **物理位置**：Host 物理内存，由 VMM 分配
- **VMCB 关联**：通过 VMCB 的 `AVIC_BACKING_PAGE` 字段指向

当 Guest 访问 APIC MMIO 地址（`0xFEE00000` 区域）或 x2APIC MSR 时，AVIC 硬件会：
1. 拦截该访问（不触发 NPF #VMEXIT）
2. 通过 NPT 验证权限
3. **不使用 NPT 中的物理地址**，而是使用 VMCB 中 `AVIC_BACKING_PAGE` 指针指向的页面
4. 直接读写 vAPIC Backing Page 中对应的 APIC 寄存器

> KVM 实现：`avic_get_backing_page_address()` 返回 `__pa(svm->vcpu.arch.apic->regs)`，即 KVM 的 LAPIC 寄存器页就是 AVIC 的 Backing Page。

### 3.2 Physical APIC ID Table（物理 APIC ID 表）

- **粒度**：per-VM，每个虚拟机一张表
- **作用**：将 Guest Physical APIC ID 映射到 vAPIC Backing Page 物理地址和 Host Physical CPU ID
- **表大小**：
  - xAVIC 模式：256 个条目（APIC ID 0~255，占 2KB）
  - x2AVIC 模式：512 个条目（APIC ID 0~511，占 4KB）
  - x2AVIC EXT 模式：4096 个条目（APIC ID 0~4095，占 32KB）
- **VMCB 关联**：通过 VMCB 的 `AVIC_PHYSICAL_ID` 字段指向表基址

#### Physical APIC ID Table Entry 格式（64-bit）

```
 63  62  61  60          52  51                            12  11          0
┌───┬───┬───┬─────────────┬──────────────────────────────────┬────────────┐
│ V │ IR│GLI│   Reserved  │     Backing Page Address [51:12]  │Host Phys ID│
└───┴───┴───┴─────────────┴──────────────────────────────────┴────────────┘
```

| 字段 | Bit | 描述 |
|------|-----|------|
| **V (Valid)** | 63 | 条目是否有效。为 0 时，硬件忽略该条目，广播 IPI 也不会投递到此 vCPU |
| **IR (IsRunning)** | 62 | 目标 vCPU 是否正在运行。为 1 时硬件通过 Doorbell 通知；为 0 时触发 INCOMPLETE_IPI VM-Exit |
| **GLI (GA_LOG_INTR)** | 61 | 置位时，IOMMU 收到设备中断后通过 GALog 通知 KVM 唤醒 vCPU |
| **Backing Page Address** | 51:12 | vAPIC Backing Page 的物理地址（页对齐，40-bit） |
| **Host Physical ID** | 11:0 | 目标 vCPU 当前运行的 Host 物理 CPU ID |

> KVM 中 `svm.h` 定义：
> - `AVIC_PHYSICAL_ID_ENTRY_VALID_MASK` = `BIT_ULL(63)`
> - `AVIC_PHYSICAL_ID_ENTRY_IS_RUNNING_MASK` = `BIT_ULL(62)`
> - `AVIC_PHYSICAL_ID_ENTRY_GA_LOG_INTR` = `BIT_ULL(61)`
> - `AVIC_PHYSICAL_ID_ENTRY_BACKING_PAGE_MASK` = `GENMASK_ULL(51, 12)`
> - `AVIC_PHYSICAL_ID_ENTRY_HOST_PHYSICAL_ID_MASK` = `GENMASK_ULL(11, 0)`

### 3.3 Logical APIC ID Table（逻辑 APIC ID 表）

- **粒度**：per-VM，每个虚拟机一张表
- **作用**：支持 Logical 地址模式的 IPI 投递，将 Logical APIC ID 映射到 Guest Physical APIC ID
- **表大小**：4KB（1024 个 32-bit 条目）
- **仅 xAPIC 模式使用**：x2AVIC 模式下硬件通过算法直接从 x2APIC ID 推导 Logical ID，不使用此表

#### Logical APIC ID Table Entry 格式（32-bit）

```
 31  30          8  7        0
┌───┬────────────┬──────────┐
│ V │ Reserved   │Guest Phys│
│   │            │  APIC ID │
└───┴────────────┴──────────┘
```

| 字段 | Bit | 描述 |
|------|-----|------|
| **V (Valid)** | 31 | 条目是否有效 |
| **Guest Physical APIC ID** | 7:0 | 对应的 Guest Physical APIC ID |

> KVM 中 `svm.h` 定义：
> - `AVIC_LOGICAL_ID_ENTRY_VALID_MASK` = `BIT(31)`
> - `AVIC_LOGICAL_ID_ENTRY_GUEST_PHYSICAL_ID_MASK` = `GENMASK(7, 0)`

---

## 4. VMCB 控制字段

AVIC 通过 VMCB（Virtual Machine Control Block）控制区域的多个字段进行配置。

### 4.1 关键 VMCB 字段

| VMCB 字段 | 偏移 | 描述 |
|-----------|------|------|
| `int_ctl` | 0x60 | 中断控制字段，包含 AVIC_ENABLE 和 X2APIC_MODE 位 |
| `avic_backing_page` | 0x78 (0xe0 in control area) | vAPIC Backing Page 的物理地址 |
| `avic_logical_id` | 0x88 (0xf0) | Logical APIC ID Table 的物理地址 |
| `avic_physical_id` | 0x90 (0xf8) | Physical APIC ID Table 的物理地址 + MAX_INDEX |
| `avic_vapic_bar` | 0x98 | vAPIC BAR 地址，通常设为 `0xFEE00000`（APIC 默认基址） |

### 4.2 int_ctl 关键位

```
 31  30  29                    0
┌───┬───┬───────────────────────┐
│AVC│X2M│      其他控制位        │
└───┴───┴───────────────────────┘
```

| 位 | 名称 | 描述 |
|----|------|------|
| Bit 31 | **AVIC_ENABLE** | 启用 AVIC 硬件虚拟化 |
| Bit 30 | **X2APIC_MODE** | 启用 x2AVIC 模式（x2APIC MSR 虚拟化） |

> KVM `svm.h`：
> - `AVIC_ENABLE_SHIFT` = 31
> - `X2APIC_MODE_SHIFT` = 30
> - `AVIC_ENABLE_MASK` = `BIT_ULL(31)`
> - `X2APIC_MODE_MASK` = `BIT_ULL(30)`

### 4.3 avic_physical_id 字段中的 MAX_INDEX

`VMCB.avic_physical_id` 的高位存储 Physical APIC ID Table 基址，低 12 位存储 **MAX_INDEX**（表中最大有效索引值）：

```
 63                              12  11          0
┌──────────────────────────────────┬──────────────┐
│  Physical APIC ID Table Base Addr │  MAX_INDEX  │
└──────────────────────────────────┴──────────────┘
```

MAX_INDEX 告诉硬件表中有多少个有效条目，用于广播 IPI 时确定扫描范围。

> KVM：`avic_activate_vmcb()` 中设置 `vmcb->control.avic_physical_id |= avic_get_max_physical_id(vcpu)`

---

## 5. IPI 虚拟化流程

### 5.1 Guest 发送 IPI 时的硬件处理

当 Guest 写 APIC ICR（Interrupt Command Register）发送 IPI 时，AVIC 硬件执行以下步骤：

**Step 1: 解析 IPI 目标**

根据 ICR 中指定的目标地址模式（Physical / Logical）和交付模式：

**Step 2: 查找目标 vCPU**

- **Physical 模式**：直接使用目标 APIC ID 作为索引查找 Physical APIC ID Table
- **Logical 模式**（xAPIC）：根据 DFR（Flat/Cluster）模式查找 Logical APIC ID Table，获取 Guest Physical APIC ID，再查 Physical APIC ID Table

**Step 3: 检查目标 vCPU 运行状态**

- 如果 `IsRunning=1`：硬件直接设置目标 vAPIC 页的 IRR 位，然后通过 **Doorbell MSR**（`MSR_AMD64_SVM_AVIC_DOORBELL`）通知目标 pCPU
- 如果 `IsRunning=0`：硬件设置目标 vAPIC 页的 IRR 位，然后触发源 vCPU 的 **AVIC_INCOMPLETE_IPI VM-Exit**

**Step 4: 处理异常情况**

以下情况会触发 AVIC_INCOMPLETE_IPI VM-Exit（exit code = `0x401`）：

| IPI Failure Cause | 值 | 含义 | KVM 处理方式 |
|-------------------|----|----|-------------|
| `INVALID_INT_TYPE` | 0 | 交付模式不被 AVIC 支持（非 Fixed/Edge-Triggered INTR） | 软件模拟 IPI |
| `TARGET_NOT_RUNNING` | 1 | 目标 vCPU 未在运行（IsRunning=0） | 唤醒目标 vCPU |
| `INVALID_TARGET` | 2 | 目标 APIC ID 在 Physical ID Table 中无有效条目 | 软件模拟 IPI |
| `INVALID_BACKING_PAGE` | 3 | 目标 vAPIC Backing Page 地址无效 | WARN + 忽略 |
| `INVALID_IPI_VECTOR` | 4 | IPI vector < 16（保留向量） | 忽略 |

### 5.2 AVIC Doorbell 机制

当目标 vCPU 正在另一个 pCPU 上运行时，AVIC 硬件通过 **Doorbell MSR** 通知目标 pCPU：

```
MSR_AMD64_SVM_AVIC_DOORBELL
    写入值 = 目标 pCPU 的物理 CPU ID
```

目标 pCPU 收到 Doorbell 后：
1. 在下一次 VMRUN 之前检查 vIRR
2. 如果有 pending 中断，注入到 Guest

> KVM 实现 `avic_ring_doorbell()`：
> ```c
> void avic_ring_doorbell(struct kvm_vcpu *vcpu)
> {
>     int cpu = READ_ONCE(vcpu->cpu);
>     if (cpu != get_cpu()) {
>         wrmsrq(MSR_AMD64_SVM_AVIC_DOORBELL, cpu_physical_id(cpu));
>     }
>     put_cpu();
> }
> ```
> 注意：Doorbell 有可能发到错误的 pCPU（vCPU 迁移竞态），但这是无害的——vCPU 迁移后会执行 VMRUN 并处理 pending 中断。

### 5.3 VM-Exit 信息

AVIC_INCOMPLETE_IPI VM-Exit 提供以下信息：

| 字段 | 内容 |
|------|------|
| `exit_code` | 0x401 (SVM_EXIT_AVIC_INCOMPLETE_IPI) |
| `exit_info_1` | ICR 的完整 64-bit 值（高 32-bit = ICRH，低 32-bit = ICRL） |
| `exit_info_2` | 高 32-bit = IPI failure cause ID；低 12-bit = 目标索引（target index） |

> `exit_info_2` 中的 target index 是硬件提供的关键优化信息：KVM 可以直接用此索引定位目标 vCPU，无需遍历所有 vCPU。

---

## 6. 设备中断虚拟化（IOMMU AVIC / GA 模式）

### 6.1 传统模式 vs GA 模式

在 **传统模式**下，设备中断（如 PCI 直通设备的 MSIX 中断）的投递流程：
```
设备 → IOMMU → Host Physical IRQ → KVM → VM-Entry → 注入 Guest
```

在 **GA（Guest APIC）模式**下，AMD IOMMU 可以**直接将中断注入 Guest 的 vAPIC Backing Page**：
```
设备 → IOMMU (GA mode) → 直接写 vAPIC IRR → (如需唤醒) GALog → KVM
```

### 6.2 IRTE（Interrupt Remapping Table Entry）

IOMMU 使用 IRTE 来配置中断重映射。在 GA 模式下，IRTE 包含：

- **Guest Mode** 标志：启用 GA 模式
- **vAPIC Backing Page 地址**：IOMMU 直接写入此页面的 IRR
- **GATag**：用于 GALog 通知时标识目标 VM 和 vCPU
- **Vector**：中断向量号

> KVM 实现 `avic_pi_update_irte()`：
> ```c
> struct amd_iommu_pi_data pi_data = {
>     .ga_tag = AVIC_GATAG(to_kvm_svm(kvm)->avic_vm_id, vcpu->vcpu_idx),
>     .is_guest_mode = kvm_vcpu_apicv_active(vcpu),
>     .vapic_addr = avic_get_backing_page_address(to_svm(vcpu)),
>     .vector = vector,
> };
> ```

### 6.3 GATag 编码

GATag 是 32-bit 的不透明值（对硬件而言），用于 IOMMU ↔ SVM 之间的通信：

```
 31                   N+1  N                   0
┌────────────────────────┬──────────────────────┐
│      VM ID             │     vCPU Index       │
└────────────────────────┴──────────────────────┘
```

其中 N 的值取决于 `AVIC_PHYSICAL_MAX_INDEX_MASK` 的位宽：
- xAVIC：N = 7（支持 256 个 vCPU ID）
- x2AVIC：N = 8（支持 512 个 vCPU ID）
- x2AVIC EXT：N = 11（支持 4096 个 vCPU ID）

> KVM 使用 vCPU 的 **index**（而非 APIC ID）来编码 GATag，因为 KVM 对 index 有快速查找能力。

### 6.4 GALog（Guest APIC Log）

当 vCPU 不在运行状态时（IsRunning=0），IOMMU 无法通过 Doorbell 通知。此时使用 **GALog** 机制：

1. IOMMU 在 vAPIC 页设置 IRR 位
2. IOMMU 写入一条 GALog 条目（包含 GATag）
3. IOMMU 触发 **GALog Interrupt**（Host 侧中断）
4. KVM 的 `avic_ga_log_notifier()` 回调被调用
5. 从 GATag 解码出 VM ID 和 vCPU Index
6. 通过哈希表查找对应的 VM 和 vCPU
7. 调用 `kvm_vcpu_wake_up()` 唤醒目标 vCPU

```
┌──────────┐     IRTE (GA mode)      ┌──────────────┐
│  PCI 设备 │ ──────────────────────► │   IOMMU      │
└──────────┘                         │              │
                                     │ 1. 写 vAPIC   │
                                     │    IRR 位     │
                                     │              │
                                     │ 2. vCPU运行?  │
                                     └──────┬───────┘
                                   Yes │           │ No
                                      ▼           ▼
                                 Doorbell     GALog 条目
                                 (无需KVM)         │
                                              ▼
                                         GALog IRQ
                                              │
                                              ▼
                                     avic_ga_log_notifier()
                                         │
                                         ▼
                                     kvm_vcpu_wake_up()
```

### 6.5 IRTE 更新与 vCPU 迁移

当 vCPU 在不同 pCPU 间迁移时，KVM 需要更新所有关联的 IRTE：

> KVM 维护 per-vCPU 的 `ir_list`（中断重映射列表），记录所有投递到该 vCPU 的设备中断。

`avic_update_iommu_vcpu_affinity()` 遍历 `ir_list`，对每个 IRTE 调用：
- `amd_iommu_update_ga()`：更新目标 pCPU 和 GA_LOG_INTR 标志
- `amd_iommu_activate_guest_mode()`：激活 GA 模式
- `amd_iommu_deactivate_guest_mode()`：退出 GA 模式

---

## 7. x2AVIC 扩展

### 7.1 动机

传统 AVIC 仅支持 xAPIC 模式（MMIO 地址 `0xFEE00000` 区域访问 APIC 寄存器）。Guest 必须禁用 x2APIC 才能使用 AVIC 硬件加速。现代操作系统默认使用 x2APIC 模式，这导致 AVIC 无法被利用。

**x2AVIC** 扩展了 AVIC，支持 x2APIC 模式（通过 MSR `0x800-0x8FF` 访问 APIC 寄存器），使得 Guest 在 x2APIC 模式下也能获得硬件加速。

### 7.2 启用方式

x2AVIC 需要同时设置 VMCB `int_ctl` 的两个位：
- **Bit 31 (AVIC_ENABLE)**：启用 AVIC 基础设施
- **Bit 30 (X2APIC_MODE)**：启用 x2APIC MSR 虚拟化

同时需要**关闭 x2APIC MSR 范围的拦截**，允许 AVIC 硬件直接处理 MSR 读写。

> CPUID 检测：`Fn8000_000A EDX[14]` 表示 x2AVIC 支持。

### 7.3 x2AVIC 的关键差异

| 特性 | xAVIC | x2AVIC |
|------|-------|--------|
| APIC 访问方式 | MMIO (0xFEE00000) | MSR (0x800-0x8FF) |
| 最大 vCPU 数 | 256 | 512 (或 4096 with X2AVIC_EXT) |
| Logical APIC ID Table | 使用 | 不使用（硬件直接计算） |
| Physical ID Table 大小 | 2KB (256 entries) | 4KB (512 entries) 或 32KB (4096 entries) |
| LDR/DFR 寄存器 | Guest 可写，需维护逻辑表 | LDR 只读，DFR 不存在 |
| MSR 拦截 | N/A | 需关闭 x2APIC MSR 范围拦截 |

### 7.4 动态模式切换

x2AVIC 支持运行时在 xAPIC 和 x2APIC 模式之间切换：

- Guest 从 xAPIC 切换到 x2APIC：设置 `X2APIC_MODE` 位，启用 MSR 不拦截，禁用 vAPIC BAR MMIO 重定向
- Guest 从 x2APIC 切换到 xAPIC：清除 `X2APIC_MODE` 位，启用 MSR 拦截，启用 vAPIC BAR MMIO 重定向

> KVM 实现 `avic_refresh_virtual_apic_mode()` 负责处理模式切换。

### 7.5 Hybrid AVIC 模式

KVM 支持 **Hybrid AVIC 模式**：当 Guest 启用 x2APIC 但硬件不支持 x2AVIC 时，KVM 可以：
- 软件模拟 x2APIC MSR 读写（通过 MSR 拦截）
- 同时利用 AVIC Doorbell 机制进行中断注入

> KVM 在 `avic_hardware_setup()` 中设置 `svm_x86_ops.allow_apicv_in_x2apic_without_x2apic_virtualization = true` 来启用此模式。

---

## 8. Secure AVIC（SEV-SNP 环境）

### 8.1 概述

在 SEV-SNP（Secure Encrypted Virtualization - Secure Nested Paging）环境中，Guest 内存是加密的，Host 无法直接访问 Guest 的 APIC 寄存器页。Secure AVIC 为此设计：

- **Guest 拥有的 APIC Backing Page**：Backing Page 位于 Guest 加密内存中
- **AllowedIRR / RequestedIRR**：Host 和 IOMMU 通过这两个机制间接请求设置 IRR 位
  - Host/IOMMU 设置 `RequestedIRR` 位
  - Guest 硬件检查 `RequestedIRR`，如果 `AllowedIRR` 允许，则将其同步到实际 IRR

### 8.2 安全模型

```
┌─────────────────────────────┐
│       Host / IOMMU          │
│                             │
│  设置 RequestedIRR 位 ──────┼──► RequestedIRR (Guest encrypted page)
│                             │
└─────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────┐
│       Guest Hardware        │
│                             │
│  检查 AllowedIRR 权限        │
│  if allowed:                │
│    IRR |= RequestedIRR      │
│    clear RequestedIRR       │
│                             │
└─────────────────────────────┘
```

> KVM 检查：`avic_hardware_setup()` 中检查 `X86_FEATURE_HV_INUSE_WR_ALLOWED`（即 `HvInUseWrAllowed`），确保 Host 有权写入 Guest 的加密 APIC 页。

---

## 9. KVM 代码实现详解

以下基于 Linux kernel master 分支 `arch/x86/kvm/svm/avic.c` 进行分析。

### 9.1 硬件检测与初始化

```c
bool __init avic_hardware_setup(void)
{
    avic = avic_want_avic_enabled();
    if (!avic)
        return false;

    // AVIC 是 x2AVIC 的前提
    x2avic_enabled = boot_cpu_has(X86_FEATURE_X2AVIC);
    if (x2avic_enabled) {
        if (cpu_feature_enabled(X86_FEATURE_X2AVIC_EXT))
            x2avic_max_physical_id = X2AVIC_4K_MAX_PHYSICAL_ID; // 0xFFF
        else
            x2avic_max_physical_id = X2AVIC_MAX_PHYSICAL_ID;    // 0x1FF
    }

    // Erratum 1235: Zen1/Zen2 禁用 IPI virtualization
    if (boot_cpu_data.x86 == 0x17 || boot_cpu_data.x86 == 0x18)
        enable_ipiv = false;

    // 注册 IOMMU GALog 回调
    amd_iommu_register_ga_log_notifier(&avic_ga_log_notifier);
    return true;
}
```

**自动启用逻辑**（`avic_want_avic_enabled()`）：
- 默认 `avic = AVIC_AUTO_MODE (-1)`
- Auto 模式下：仅 Zen4+ 且支持 x2AVIC 时自动启用
- 必须启用 NPT
- 必须支持 AVIC CPUID bit（或 force_avic）
- SNP 环境下需要 `HvInUseWrAllowed`

### 9.2 VMCB 初始化

```c
void avic_init_vmcb(struct vcpu_svm *svm, struct vmcb *vmcb)
{
    // 设置 vAPIC Backing Page 地址
    vmcb->control.avic_backing_page = avic_get_backing_page_address(svm);
    // 设置 Logical APIC ID Table 地址
    vmcb->control.avic_logical_id = __sme_set(__pa(kvm_svm->avic_logical_id_table));
    // 设置 Physical APIC ID Table 地址
    vmcb->control.avic_physical_id = __sme_set(__pa(kvm_svm->avic_physical_id_table));
    // 设置 vAPIC BAR
    vmcb->control.avic_vapic_bar = APIC_DEFAULT_PHYS_BASE;

    // 根据 APICv 状态激活/停用
    if (kvm_vcpu_apicv_active(&svm->vcpu))
        avic_activate_vmcb(svm);
    else
        avic_deactivate_vmcb(svm);
}
```

### 9.3 avic_activate_vmcb() — 激活 AVIC

```c
static void avic_activate_vmcb(struct vcpu_svm *svm)
{
    // 清除旧配置，设置 AVIC_ENABLE
    vmcb->control.int_ctl &= ~(AVIC_ENABLE_MASK | X2APIC_MODE_MASK);
    vmcb->control.avic_physical_id &= ~AVIC_PHYSICAL_MAX_INDEX_MASK;
    vmcb->control.avic_physical_id |= avic_get_max_physical_id(vcpu);
    vmcb->control.int_ctl |= AVIC_ENABLE_MASK;

    // CR8 写拦截不需要（AVIC 硬件处理）
    svm_clr_intercept(svm, INTERCEPT_CR8_WRITE);

    // TLB 刷新：切换 xAVIC/x2AVIC 模式时需要
    kvm_make_request(KVM_REQ_TLB_FLUSH_CURRENT, &svm->vcpu);

    if (x2avic_enabled && apic_x2apic_mode(svm->vcpu.arch.apic)) {
        // x2AVIC 模式：设置 X2APIC_MODE，关闭 MSR 拦截
        vmcb->control.int_ctl |= X2APIC_MODE_MASK;
        avic_set_x2apic_msr_interception(svm, false);
    } else {
        // xAVIC 模式：启用 MSR 拦截（KVM 软件模拟 x2APIC MSR）
        avic_set_x2apic_msr_interception(svm, true);
    }
}
```

**TLB 刷新的原因**：

KVM 使用 per-VM 的 "scratch" 页面来支持 APIC memslot。当 AVIC 启用时，硬件忽略 NPT 中的物理地址，转而使用 VMCB 中的 Backing Page 指针。因此 TLB 中可能缓存了指向 scratch 页面的旧映射，需要刷新。

### 9.4 Backing Page 初始化

```c
static int avic_init_backing_page(struct kvm_vcpu *vcpu)
{
    u32 max_id = x2avic_enabled ? x2avic_max_physical_id : AVIC_MAX_PHYSICAL_ID;
    u32 id = vcpu->vcpu_id;
    u64 new_entry;

    // vCPU ID 超出硬件支持范围时禁用 AVIC
    if (id > max_id) {
        kvm_set_apicv_inhibit(vcpu->kvm, APICV_INHIBIT_REASON_PHYSICAL_ID_TOO_BIG);
        vcpu->arch.apic->apicv_active = false;
        return 0;
    }

    // 构建 Physical ID Table 条目
    new_entry = avic_get_backing_page_address(svm) |
                AVIC_PHYSICAL_ID_ENTRY_VALID_MASK;
    svm->avic_physical_id_entry = new_entry;

    // 写入实际表（广播 IPI 需要有效条目）
    WRITE_ONCE(kvm_svm->avic_physical_id_table[id], new_entry);
    return 0;
}
```

### 9.5 vCPU Load/Put — IsRunning 管理

```c
static void __avic_vcpu_load(struct kvm_vcpu *vcpu, int cpu,
                             enum avic_vcpu_action action)
{
    int h_physical_id = cpu_physical_id(cpu);
    u64 entry;

    entry = svm->avic_physical_id_entry;
    // 清除旧的 Host Physical ID 和 GA_LOG_INTR
    entry &= ~(AVIC_PHYSICAL_ID_ENTRY_HOST_PHYSICAL_ID_MASK |
               AVIC_PHYSICAL_ID_ENTRY_GA_LOG_INTR);
    // 设置新的 Host Physical ID
    entry |= (h_physical_id & AVIC_PHYSICAL_ID_ENTRY_HOST_PHYSICAL_ID_MASK);
    // 设置 IsRunning = 1
    entry |= AVIC_PHYSICAL_ID_ENTRY_IS_RUNNING_MASK;

    svm->avic_physical_id_entry = entry;

    // 如果 IPI virtualization 被禁用（erratum 1235），
    // 写入实际表时清除 IsRunning
    if (!enable_ipiv)
        entry &= ~AVIC_PHYSICAL_ID_ENTRY_IS_RUNNING_MASK;

    WRITE_ONCE(kvm_svm->avic_physical_id_table[vcpu->vcpu_id], entry);

    // 更新 IOMMU IRTE
    avic_update_iommu_vcpu_affinity(vcpu, h_physical_id, action);
}
```

**关键设计点**：
- `svm->avic_physical_id_entry` 是 KVM 的缓存值（含 GA_LOG_INTR）
- 实际写入 Physical ID Table 的值可能不同（erratum 1235 时不含 IsRunning）
- `enable_ipiv=false` 时，IsRunning 永远为 0，强制走 INCOMPLETE_IPI 路径

### 9.6 vCPU Blocking/Unblocking

```c
void avic_vcpu_blocking(struct kvm_vcpu *vcpu)
{
    // vCPU 即将阻塞时，清除 IsRunning，设置 GA_LOG_INTR
    __avic_vcpu_put(vcpu, AVIC_START_BLOCKING);
    // 此时 IOMMU 设备中断会通过 GALog 通知 KVM 唤醒
}

void avic_vcpu_unblocking(struct kvm_vcpu *vcpu)
{
    // vCPU 被唤醒时，恢复 IsRunning
    avic_vcpu_load(vcpu, vcpu->cpu);
}
```

**Blocking 时的内存屏障问题**：

```
vCPU Blocking:                    中断投递:
  1. IsRunning = 0                  1. 写 vAPIC IRR 位
  2. 读 vIRR (检查 pending)         2. 读 IsRunning
     → 决定是否真正阻塞               → 决定是否触发 INCOMPLETE_IPI
```

KVM 使用 `set_current_state()` 中的隐式内存屏障来保证 Step 1 在 Step 2 之前完成。但 CPU 端需要匹配的屏障（在中断投递时先写 IRR 后读 IsRunning），**erratum 1235** 正是此屏障缺失导致的。

### 9.7 Incomplete IPI 处理

```c
int avic_incomplete_ipi_interception(struct kvm_vcpu *vcpu)
{
    u32 icrh = svm->vmcb->control.exit_info_1 >> 32;
    u32 icrl = svm->vmcb->control.exit_info_1;
    u32 id = svm->vmcb->control.exit_info_2 >> 32;      // failure cause
    u32 index = svm->vmcb->control.exit_info_2 & AVIC_PHYSICAL_MAX_INDEX_MASK;

    switch (id) {
    case AVIC_IPI_FAILURE_INVALID_TARGET:
    case AVIC_IPI_FAILURE_INVALID_INT_TYPE:
        // AVIC 不支持的 IPI 类型，软件模拟
        if (icrl & APIC_ICR_BUSY)
            kvm_apic_write_nodecode(vcpu, APIC_ICR);
        else
            kvm_apic_send_ipi(apic, icrl, icrh);
        break;

    case AVIC_IPI_FAILURE_TARGET_NOT_RUNNING:
        // 目标 vCPU 未运行，需要唤醒
        avic_kick_target_vcpus(vcpu->kvm, apic, icrl, icrh, index);
        break;

    case AVIC_IPI_FAILURE_INVALID_BACKING_PAGE:
        WARN_ONCE(1, "Invalid backing page\n");
        break;

    case AVIC_IPI_FAILURE_INVALID_IPI_VECTOR:
        // vector < 16，忽略
        break;
    }
    return 1;
}
```

### 9.8 快速路径 IPI Kick

```c
static int avic_kick_target_vcpus_fast(struct kvm *kvm, struct kvm_lapic *source,
                                       u32 icrl, u32 icrh, u32 index)
{
    // 利用 exit_info_2 中的 index 直接定位目标 vCPU
    // 避免遍历所有 vCPU

    if (dest_mode == APIC_DEST_PHYSICAL) {
        // 物理模式：index 就是目标 APIC ID
        avic_kick_vcpu_by_physical_id(kvm, dest, icrl);
    } else {
        // 逻辑模式：解析 cluster + bitmap
        if (apic_x2apic_mode(source)) {
            bitmap = dest & 0xFFFF;
            cluster = (dest >> 16) << 4;
        }
        // 遍历 bitmap 中的每个 bit
        for_each_set_bit(i, &bitmap, 16)
            avic_kick_vcpu_by_logical_id(kvm, ..., cluster + i, icrl);
    }
    return 0;
}
```

**慢速路径**（`avic_kick_target_vcpus()`）：当 fast path 返回 `-EINVAL`（如广播 IPI 或 shorthand 非 NOSHORT）时，遍历所有 vCPU 进行匹配。

### 9.9 Unaccelerated Access 处理

当 Guest 访问的 APIC 寄存器不被 AVIC 硬件直接支持时，触发 `SVM_EXIT_AVIC_UNACCELERATED_ACCESS`（0x402）：

```c
int avic_unaccelerated_access_interception(struct kvm_vcpu *vcpu)
{
    u32 offset = exit_info_1 & AVIC_UNACCEL_ACCESS_OFFSET_MASK;
    bool trap = is_avic_unaccelerated_access_trap(offset);

    if (trap) {
        // Trap：硬件已执行了操作，KVM 只需更新副作用
        // 涉及 LDR/DFR 等需要维护 Logical APIC ID Table 的寄存器
        avic_unaccel_trap_write(vcpu);
    } else {
        // Fault：硬件未执行，KVM 需要模拟指令
        kvm_emulate_instruction(vcpu, 0);
    }
}
```

**Trap vs Fault 的区别**：
- **Trap**：AVIC 硬件已完成寄存器写入到 vAPIC 页，但需要 KVM 处理副作用（如更新 Logical APIC ID Table）
- **Fault**：AVIC 硬件未完成操作，需要 KVM 完整模拟

Trap 类型的寄存器包括：APIC_ID, EOI, LDR, DFR, SPIV, ESR, ICR, LVT*, TMICT, TDCR 等。

### 9.10 GALog 通知回调

```c
static int avic_ga_log_notifier(u32 ga_tag)
{
    u32 vm_id = AVIC_GATAG_TO_VMID(ga_tag);
    u32 vcpu_idx = AVIC_GATAG_TO_VCPUIDX(ga_tag);

    // 通过哈希表查找 VM
    hash_for_each_possible(svm_vm_data_hash, kvm_svm, hnode, vm_id) {
        if (kvm_svm->avic_vm_id == vm_id) {
            // 通过 index 快速获取 vCPU
            vcpu = kvm_get_vcpu(&kvm_svm->kvm, vcpu_idx);
            break;
        }
    }

    // IOMMU 已经在 vAPIC 页设置了 IRR，只需唤醒 vCPU
    if (vcpu)
        kvm_vcpu_wake_up(vcpu);
    return 0;
}
```

### 9.11 IRTE 更新

```c
int avic_pi_update_irte(struct kvm_kernel_irqfd *irqfd, struct kvm *kvm,
                       unsigned int host_irq, uint32_t guest_irq,
                       struct kvm_vcpu *vcpu, u32 vector)
{
    struct amd_iommu_pi_data pi_data = {
        .ga_tag = AVIC_GATAG(to_kvm_svm(kvm)->avic_vm_id, vcpu->vcpu_idx),
        .is_guest_mode = kvm_vcpu_apicv_active(vcpu),
        .vapic_addr = avic_get_backing_page_address(to_svm(vcpu)),
        .vector = vector,
    };

    // 从 Physical ID Entry 获取当前 pCPU 和运行状态
    entry = svm->avic_physical_id_entry;
    if (entry & AVIC_PHYSICAL_ID_ENTRY_IS_RUNNING_MASK) {
        pi_data.cpu = entry & AVIC_PHYSICAL_ID_ENTRY_HOST_PHYSICAL_ID_MASK;
    } else {
        pi_data.cpu = -1;
        pi_data.ga_log_intr = entry & AVIC_PHYSICAL_ID_ENTRY_GA_LOG_INTR;
    }

    // 调用 IOMMU 驱动更新 IRTE
    ret = irq_set_vcpu_affinity(host_irq, &pi_data);

    // 将 IRTE 元数据加入 vCPU 的 ir_list
    list_add(&irqfd->vcpu_list, &svm->ir_list);
}
```

---

## 10. 已知硬件 Erratum

### 10.1 Erratum 1235（Family 17h / 18h）

**影响范围**：AMD Zen1 (Family 0x17) 和 Hygon (Family 0x18)

**问题**：CPU 在中断投递时，写入 IRR 和读取 IsRunning 之间缺少内存屏障，导致：
- 源 vCPU 设置了目标 vAPIC 的 IRR 位
- 但目标 vCPU 的 IsRunning 位的更新未被可靠检测
- 导致目标 vCPU 错过 VM-Exit（INCOMPLETE_IPI），中断被延迟或丢失

**KVM 解决方案**：

```c
// 在 avic_hardware_setup() 中
if (boot_cpu_data.x86 == 0x17 || boot_cpu_data.x86 == 0x18)
    enable_ipiv = false;
```

禁用 IPI virtualization 后：
- Physical ID Table 中 IsRunning 永远为 0
- 所有 IPI 都会触发 INCOMPLETE_IPI VM-Exit
- KVM 完全软件模拟 IPI 投递
- 但设备中断投递（IOMMU GA 模式）不受影响

---

## 11. AVIC vs x2AVIC vs Secure AVIC 对比

| 特性 | AVIC (xAVIC) | x2AVIC | Secure AVIC |
|------|-------------|--------|-------------|
| **APIC 模式** | xAPIC (MMIO) | x2APIC (MSR) | xAPIC/x2APIC |
| **CPUID 检测** | Fn8000_000A EDX[3] | Fn8000_000A EDX[14] | HV_INUSE_WR_ALLOWED |
| **最大 vCPU 数** | 256 | 512 (4096 with EXT) | 同 x2AVIC |
| **VMCB 控制位** | AVIC_ENABLE (bit 31) | AVIC_ENABLE + X2APIC_MODE (bit 31+30) | AVIC_ENABLE + 加密支持 |
| **vAPIC Backing Page** | Host 分配，Guest 可见 | Host 分配，Guest 可见 | Guest 加密内存 |
| **IOMMU GA 模式** | 支持 | 支持 | 支持（受限） |
| **Logical APIC ID Table** | 使用 | 不使用 | 使用/不使用 |
| **中断注入安全模型** | 直接写 IRR | 直接写 IRR | RequestedIRR → AllowedIRR → IRR |
| **适用场景** | 传统虚拟化 | 现代操作系统（默认 x2APIC） | SEV-SNP 加密虚拟机 |
| **首个支持 CPU** | Family 15h (Carrizo) | Zen4 (Family 19h) | SEV-SNP 平台 |

---

## 12. 参考文献

1. **AMD64 Architecture Programmer's Manual Volume 2: System Programming** (Publication 24593), Section 15.29 — AMD AVIC 架构规范
2. **AMD I/O Virtualization Technology (IOMMU) Specification** (Publication 48882) — IOMMU GA 模式和 IRTE 格式
3. **Linux Kernel Source** — `arch/x86/kvm/svm/avic.c`, `arch/x86/include/asm/svm.h` (master branch, [GitHub](https://github.com/torvalds/linux/blob/master/arch/x86/kvm/svm/avic.c))
4. **[RFCv2 PATCH 00/12] Introducing AMD x2APIC Virtualization (x2AVIC) support** — Suravee Suthikulpanit, [LWN](https://lwn.net/Articles/887196/)
5. **[PART1 RFC v2 00/10] KVM: x86: Introduce SVM AVIC support** — KVM AVIC 初始 patch series, [kernel archive](https://fa.linux.kernel.narkive.com/zH000A6k/part1-rfc-v2-00-10-kvm-x86-introduce-svm-avic-support)
6. **AMD64 Technology CPUID Specification** — Fn8000_000A EDX bit 定义
7. **AMD Processor Revision Guide for Family 17h** — Erratum 1235 详细说明

---

> **文档版本**：基于 Linux Kernel master 分支（2024-2025）和 AMD APM Rev 3.30+ 分析
>
> **作者**：系统虚拟化团队 — AVIC 技术调研
