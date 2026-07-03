Title: x86 嵌套虚拟化性能优化项总结
Date: 2026-7-3 11:00
Modified: 2026-7-3 11:00
Tags: virtualization, nested-virt, performance
Slug: x86-nested-virt-performance
Status: published
Authors: Yori Fang
Summary: 以 Linux KVM 为背景，梳理 Intel VMX、AMD SVM 与 Hyper-V enlightenment 在嵌套虚拟化中的性能优化项、适用边界与上游状态，建立正确的嵌套性能模型。

# x86 嵌套虚拟化性能优化项总结

本文以 Linux KVM 为主要实现背景，梳理 Intel VMX、AMD SVM 和 Hyper-V enlightenment 在嵌套虚拟化中的性能作用、适用边界与当前上游状态。

> 本文中的层级约定：
>
> - **L0**：运行在物理机上的宿主 Hypervisor。
> - **L1**：运行在 L0 虚拟机中的 Guest Hypervisor。
> - **L2**：由 L1 创建的嵌套虚拟机。
>
> 功能状态依据 2026 年 7 月可获得的架构文档和 Linux 上游源码核验。具体发行版可能关闭、回退或尚未回移植某些特性。

---

## 1. 先建立正确的性能模型

嵌套虚拟化并不是简单地“多执行一层虚拟机”。硬件仍只有一套最高权限的虚拟化资源，L2 的退出首先到达 L0；如果该事件应由 L1 处理，L0 还要在软件中合成一次 L2→L1 退出。

典型的退出转发路径如下：

```text
L2 触发事件
    │
    ▼
物理 VM Exit / #VMEXIT 到 L0
    │
    ├─ L0 自己处理 ────────────────> 直接恢复 L2
    │
    └─ 应由 L1 处理
          │
          ▼
      L0 合成 L2→L1 退出
          │
          ▼
      L1 处理事件
          │
          ▼
      L1 执行 VM Entry 指令
          │
          ▼
      再次退出到 L0，由 L0 恢复 L2
```

如果 L1 在处理过程中又执行多条需要模拟的 VMX/SVM 指令，一次 L2 事件会放大成多次 L0/L1 切换，这通常称为 **exit multiplication**。

实际瓶颈可以分成六类，而不只是控制结构、地址翻译和中断三类：

| 路径 | 主要成本 | 典型症状 |
| --- | --- | --- |
| 控制结构与嵌套 Entry/Exit | VMX/SVM 指令模拟、VMCS12/VMCB12 校验、VMCS02/VMCB02 合成 | L2 启动慢、频繁退出的 workload 放大明显 |
| 地址翻译 | Shadow EPT/NPT 缺页、页表维护、TLB miss、失效传播 | 大内存随机访问或频繁修改二级页表时退化 |
| TLB 上下文管理 | L1/L2 切换时 flush、INVEPT/INVVPID/INVLPGA 模拟 | vCPU 切换和地址空间变化敏感 |
| 中断与 IPI | 中断转发、vAPIC 访问、跨 vCPU 唤醒 | 网络、小块 I/O、锁竞争、跨 vCPU workload 延迟升高 |
| I/O 数据路径 | 两层设备模型、两层 virtio backend、额外 copy 和通知 | 吞吐下降、尾延迟增大、宿主 CPU 占用升高 |
| 调度与时间 | L1/L2 调度不一致、timer/HLT/PAUSE 退出、NUMA 跨节点 | 抖动、steal time、周期性长尾 |

不同 workload 的主导项不同。不存在一组硬件开关能让所有嵌套场景都获得同样的收益。

---

## 2. 控制结构和嵌套 Entry/Exit 优化

### 2.1 Intel VMCS Shadowing

在 Intel VMX 中，L1 必须通过 `VMREAD`/`VMWRITE` 访问其为 L2 构造的 VMCS。默认情况下，这些指令在 VMX non-root operation 中会退出到 L0。

VMCS Shadowing 允许 L0：

1. 在运行 L1 的 VMCS01 中启用 VMCS Shadowing；
2. 通过 VMCS link pointer 指向一个硬件 Shadow VMCS；
3. 使用 VMREAD/VMWRITE bitmap 决定哪些字段可以由 L1 直接访问。

bitmap 对应 bit 为 0 的字段可以直接访问 Shadow VMCS；bit 为 1 的字段仍然退出到 L0。KVM 采用 allowlist，只放行能够可靠同步的字段。

它减少的是 L1 的逐字段访问退出，并不会消除：

- `VMPTRLD`、`VMCLEAR`、`VMLAUNCH`、`VMRESUME` 等 VMX 指令退出；
- VMCS12 的合法性检查；
- VMCS12 与 VMCS02 的合成；
- L2 的退出和退出转发。

VMCS Shadowing 的硬件对象链接在 **VMCS01** 上，而不是 VMCS02。更完整的同步流程是：

```text
L1 配置 L2：      Shadow VMCS → VMCS12 → VMCS02
L2 退出给 L1：    VMCS02 → VMCS12 → Shadow VMCS
```

### 2.2 Hyper-V Enlightened VMCS（eVMCS）

eVMCS 是 Microsoft Hyper-V 定义的半虚拟化接口，不是 Intel VMCS Shadowing 的别名。

L1 使用一页有公开布局的 Guest Physical Memory 表示 VMCS，并通过普通内存访问修改字段。当前 eVMCS 接口还配合 VP Assist Page 指定活动 eVMCS，因此不需要用 `VMPTRLD`、`VMREAD` 和 `VMWRITE` 完成常规字段管理。

eVMCS 的 clean fields 告诉 L0 哪些字段组没有变化。L1 修改某组字段后必须清除对应 clean bit，否则 L0 可能继续使用缓存的旧值。

eVMCS 的优势包括：

- 避免 L1 的大量 VMREAD/VMWRITE 退出；
- 通过内存结构批量传递控制状态；
- 通过 clean fields 避免重复读取和转换未变化字段。

它的限制是：

- 这是 Hyper-V ABI，需要 L0、L1 和用户空间 VMM 协商能力；
- 不应仅凭 Intel CPU 支持 VMX 就假定 eVMCS 可用；
- KVM 代码中存在相应实现，不代表所有发行版和 VM CPU model 都会暴露。

VMCS Shadowing 和 eVMCS 优化的是相似的控制路径，但路线不同：

| 机制 | 接口类型 | L1 如何修改状态 |
| --- | --- | --- |
| VMCS Shadowing | Intel 硬件接口 | 对允许字段继续执行 VMREAD/VMWRITE，由硬件访问 Shadow VMCS |
| eVMCS | Hyper-V 半虚拟化 ABI | 直接修改内存中的 eVMCS，并管理 clean fields |

### 2.3 AMD VMCB Clean Bits

AMD VMCB 的字段布局是架构可见的，L1 使用普通内存 load/store 修改 VMCB12，不存在 Intel VMREAD/VMWRITE 对应的逐字段指令退出问题。

VMCB Clean Bits 首先是一个硬件状态缓存协议：

- bit 为 1：对应字段相对处理器缓存没有被 Hypervisor 修改，处理器在 `VMRUN` 时可以使用缓存值；
- bit 为 0：处理器必须重新从 VMCB 加载该字段组。

当 Hypervisor 修改 VMCB 字段时，必须清除对应 clean bit。

在嵌套 SVM 中，KVM 还可以消费 L1 提供的 VMCB12 clean bits，跳过部分没有变化的 VMCB12→VMCB02 字段复制。因此它既能减少硬件 VMRUN 状态加载，也能帮助 L0 避免不必要的软件合并。

但 VMCB Clean Bits 不是 VMCS Shadowing 的 AMD 等价物：它不用于消除 VMREAD/VMWRITE 退出，因为 AMD 本来就没有这种逐字段访问方式。

### 2.4 Hyper-V Enlightened VMCB Fields

Microsoft TLFS 在 AMD VMCB 的保留区域中定义了 enlightened VMCB fields。当前接口包含：

- `NestedFlushVirtualHypercall`：允许 L0 直接处理 L2 的虚拟 TLB flush hypercall；
- `MsrBitmap`：启用 enlightened MSR bitmap 协议；
- `EnlightenedNptTlb`：把普通 ASID invalidation 与 NPT-derived translation 的失效分开。

Enlightened MSR bitmap 启用后，L0 不再主动监视 bitmap 的每次变化；L1 修改 bitmap 后负责清除相应 clean 状态。这样 L0 可以在 bitmap 未变化时跳过重新合成。

“Nested SVM Enlightenments”不是单一的“AMD 版 eVMCS”，而是一组 Hyper-V 与 SVM 协作的半虚拟化能力。

### 2.5 VMCS02/VMCB02 合成缓存

L0 实际使用 VMCS02 或 VMCB02 运行 L2。合成过程的优化重点是：

- 只更新发生变化的 Guest 状态；
- 缓存外部结构和页面映射；
- 仅在 bitmap 或控制字段变更时重新计算；
- 将 L0 与 L1 的拦截意图合成为一个可由硬件执行的配置。

#### MSR bitmap

对可由硬件 bitmap 表达的 MSR，VMCS02 中的拦截逻辑可以近似理解为：

```text
VMCS02 MSR intercept = L0 intercept OR L1 intercept
```

- 只有 L0 请求拦截：退出到 L0，L0 处理后可直接恢复 L2；
- L1 请求拦截：退出先到 L0，再由 L0 判断并转交 L1；
- 两边都不拦截：硬件允许 L2 直接访问。

KVM 还会针对 x2APIC、PMU、安全相关 MSR 和用户空间 MSR filter 做额外处理，因此真实实现并不是简单复制两个 bitmap。

#### I/O bitmap

不能把当前 KVM nVMX 描述成“合并 L0 与 L1 的 I/O bitmap 后由硬件直接执行”。当前上游实现在 VMCS02 中设置 unconditional I/O exiting，I/O port 访问先退出到 L0；L0 再检查 VMCS12 的 I/O bitmap，决定自己处理还是把退出转交 L1。

这保留了正确性，但意味着 I/O port 访问并没有获得与 MSR bitmap 相同的硬件合并收益。

#### 控制字段

VMCS02 的控制字段通常由 L0 的要求与 L1 的控制组合而成，但不同字段的来源和合并规则不同：

- 某些字段取 L0 与 L1 的并集；
- 某些字段只采用 L1 的值；
- 某些能力由 L0 模拟，不能直接在 VMCS02 中启用；
- 某些字段必须由 L0 强制覆盖。

`IA32_VMX_*_FIXED0/FIXED1` 用于控制寄存器和能力合法性检查，不应把整个 VMCS02 合成过程概括为“fixed1 合并”。

---

## 3. 地址翻译优化

### 3.1 KVM 如何把三段逻辑翻译压缩给硬件

L2 的完整逻辑翻译路径是：

```text
L2 GVA
  │ L2 Guest Page Table
  ▼
L2 GPA
  │ L1 EPT12 / NPT12
  ▼
L1 GPA
  │ L0 EPT01 / NPT01
  ▼
Host PA
```

主流 x86 硬件直接支持的是 Guest Virtual→Guest Physical→Host Physical 两维翻译，不能原生执行上面的三段组合。

KVM 因此使用 Shadow EPT/NPT，把 L1 的 EPT12/NPT12 与 L0 的 EPT01/NPT01 合成为 EPT02/NPT02：

```text
EPT02 / NPT02 = compose(EPT12 / NPT12, EPT01 / NPT01)

硬件运行 L2 时：

L2 GVA
  │ L2 Guest Page Table
  ▼
L2 GPA
  │ EPT02 / NPT02
  ▼
Host PA
```

这里的“Shadow”不是传统的 GVA→HPA shadow page table，而是对二级地址空间映射的合成。Linux KVM 源码分别使用 `shadow_ept_mmu` 和 `shadow_npt_mmu` 等路径维护它。

### 3.2 Shadow EPT/NPT 的代价

EPT02/NPT02 减少了硬件无法执行三维翻译的问题，但把一部分成本转移给 L0：

- 第一次访问缺失映射时，L0 需要遍历 L1 的 EPT12/NPT12；
- L1 修改二级页表后，L0 必须使相关 EPT02/NPT02 映射失效或重建；
- L1 执行 INVEPT、INVVPID 或 INVLPGA 时，L0 必须提供与架构一致的失效语义；
- 脏页跟踪、内存迁移、KSM、NUMA 迁移等宿主行为也会使 shadow 映射失效；
- 多 vCPU 会增加 MMU lock、远程 TLB shootdown 和失效广播压力。

旧论文会用 Shadow-on-EPT、VTLB-like、multi-dimensional paging 等术语描述不同设计。分析当前 KVM 时，更可靠的方式是直接说明 **EPT12/NPT12 与 EPT01/NPT01 被软件合成为 EPT02/NPT02，并由 KVM shadow MMU 维护**，而不是把当前实现简单标成“不写保护 gEPT 的 VTLB-like 方案”。

### 3.3 “24～25 次内存访问”的正确上下文

四级 Guest Page Table 配合四级 EPT 时，在 TLB 和 paging-structure cache 全部 miss 的理论模型中，一次地址转换可能需要很多页表项访问。常见的“约 24 次页表访问”或“包括最终数据访问约 25 次”来自这种冷缓存二维页表遍历模型。

需要注意：

1. 该数字已经可能出现在普通单层虚拟化的 Guest Page Table + EPT 场景，不是因为 L2 硬件直接连续遍历 EPT12 和 EPT01；
2. KVM 运行 L2 时使用合成后的 EPT02/NPT02，硬件并不直接完成三维页表遍历；
3. 真实成本受页表级数、1 GiB/2 MiB 大页、paging-structure cache、TLB 层级和微架构影响；
4. “比纯 EPT 高 5 倍”必须先说明比较基线。若所谓“纯 EPT”只计算 GPA→HPA 的单次 EPT walk，结论与完整 GVA→HPA 访问不是同一口径。

因此，性能文档不应把固定的 24～25 次访问直接写成“嵌套虚拟化两层 EPT 的必然成本”。

### 3.4 Huge Page

大页有两类收益：

- 一个 TLB entry 覆盖更大地址范围，降低 TLB miss 频率；
- 页表遍历提前在更高层级结束，降低 miss 时的 page-walk 成本。

在嵌套环境中，要得到大的最终 EPT02/NPT02 leaf，通常需要同时满足多层条件：

- L2 Guest Page Table 的映射粒度和对齐允许大页；
- L1 的 EPT12/NPT12 不把该范围拆碎；
- L0 的 backing memory、memslot、权限和脏页跟踪允许大页；
- Host 内存没有因碎片、NUMA 或写保护被迫拆分。

因此“给 L2 配置 huge page”并不保证 Host 最终建立 1 GiB 或 2 MiB 的 EPT02/NPT02 映射。应同时检查 L1 和 L0 的实际映射情况。

XGEMINI 等工作属于针对嵌套环境的大页研究方案，可以作为优化思路参考，但不能列入 Linux 上游生产特性。

---

## 4. TLB 标签与失效优化

### 4.1 Intel：EPTP 与 VPID

Intel 上的两个标签解决不同问题：

- **EPTP**：区分不同 Guest Physical Address Space 的 EPT-derived translation；
- **VPID**：区分不同 vCPU/Guest linear translation context，减少 VM Entry/Exit 时的线性和 combined translation flush。

当前上游 KVM nVMX 会为 L2 分配 `vpid02`。当 L1 为 L2 启用 VPID 且 L0 成功分配独立 VPID 时，L1 与 L2 可以使用不同 TLB tag，减少嵌套切换时的无条件刷新。

如果 L1 没有为 L2 启用 VPID，KVM 必须模拟 VPID 0 的架构刷新语义。如果 VPID12 发生变化，KVM 也需要按保守方式刷新，因为当前实现没有跟踪每一个历史 VPID12 对应的完整上下文。

### 4.2 AMD：当前 KVM 仍共用 ASID

截至本文核验的 Linux 上游版本，KVM SVM 仍然：

- 让 L1 与 L2 共用一个 KVM 管理的 ASID；
- 在 nested VMRUN 和 nested VMEXIT 转换时请求 MMU sync 和 TLB flush。

上游源码仍保留“优化无条件 TLB flush/MMU sync”的 TODO。

2025 年的 `KVM: SVM: Rework ASID management` RFC patchset 提议为 nested guest 分配独立 ASID，并完善 L1/L2 flush 跟踪。该方案的方向是合理的，但在本文核验的上游 `master` 中尚未合入。因此它应标记为：

```text
研究/开发中的 RFC，不能作为现有生产内核能力
```

### 4.3 架构失效指令

常见失效接口包括：

| 平台 | 接口 | 作用 |
| --- | --- | --- |
| Intel | INVEPT | 使 EPT-derived translation 失效 |
| Intel | INVVPID | 按 VPID 和范围使线性/combined translation 失效 |
| AMD | VMCB `TLB_CONTROL`、INVLPGA | 按 ASID 或地址控制 TLB 失效 |

在嵌套场景中，这些请求由 L1 发出，但真正拥有物理 TLB 的是 L0。L0 必须把 L1 的抽象标识映射到 EPT02/NPT02、VPID02 或宿主管理的 ASID，并处理远程 vCPU 的 shootdown。

---

## 5. Hyper-V TLB Flush Enlightenment

### 5.1 为什么需要半虚拟化 flush

如果 L2 修改页表后请求 TLB flush，传统路径可能是：

```text
L2 hypercall / invalidate
        │
        ▼
退出到 L0
        │
        ▼
转交 L1 Hyper-V
        │
        ▼
L1 再通过 hypercall 请求 L0 执行真正的 flush
```

Direct Virtual Flush 允许 L1 授权 L2 直接调用 L0 的 Hyper-V flush hypercall，从而避免绕行 L1。

### 5.2 Direct Virtual Flush

Microsoft TLFS 定义的 Direct Virtual Flush 使用：

- eVMCS 或 enlightened VMCB 中的 `NestedFlushVirtualHypercall`；
- VP Assist Page 中的 DirectHypercall 能力；
- `VmId`、`VpId` 和 Partition Assist Page 标识 nested context。

L0 收到 L2 的 flush hypercall 后，可以直接使相应 nested context 的 translation 失效。必要时，L0 再向 L1 注入 synthetic VM Exit，让 L1 观察到协议要求的状态。

当前 Linux 上游 KVM 已包含 Intel VMX 和 AMD SVM 的 L2 Hyper-V TLB flush 识别与 L0 处理路径。因此，把 `hv-tlbflush-direct` 标记为“2022 WIP”已经过时。准确说法是：

> 上游实现已存在，但只有 L0、L1 和 L2 通过 Hyper-V CPUID、eVMCS/enlightened VMCB 与 assist page 完成能力协商时才能使用。

### 5.3 Enlightened NPT TLB

在 AMD 平台启用 `EnlightenedNptTlb` 后，普通 ASID invalidation 可以只处理第一阶段的 virtual translation；NPT-derived translation 通过 Hyper-V 的 Guest Physical Address flush hypercall 单独失效。

这能减少不必要的 NPT mapping invalidation，但也改变了 flush 协议：L1 必须正确发出相应 Hyper-V hypercall，不能只依赖传统 ASID flush。

---

## 6. 中断与 IPI 优化

### 6.1 Intel APIC virtualization

Intel 的 APIC virtualization 是一组相关能力，包括：

- virtualize APIC accesses；
- APIC-register virtualization；
- virtual-interrupt delivery；
- posted-interrupt processing；
- 新处理器上的 IPI virtualization。

这些能力可减少 vAPIC MMIO/MSR 访问退出、EOI 退出和软件中断注入成本。

### 6.2 Posted Interrupt 的边界

对普通单层虚拟机，Posted Interrupt 配合 interrupt remapping 可以在目标 vCPU 正在运行时把中断放入 Posted Interrupt Descriptor，并通过通知向量触发硬件同步 PIR→vIRR，避免传统的退出、软件注入和重新进入。

嵌套场景更复杂：

- L0 必须区分中断属于 L1 还是 L2；
- L1 可能要求把外部中断作为 L2→L1 VM Exit；
- L1 还可以为 L2 配置自己的 posted-interrupt descriptor；
- 目标 vCPU 是否正在 L2、APICv 是否 active、IOMMU interrupt remapping 是否可用都会改变路径。

KVM 包含 nested posted-interrupt 处理逻辑，但不能把它概括成“物理中断总能直接投递给 L2，完全跳过 L0”。L0 仍负责能力校验、descriptor 映射、通知处理和必要的退出合成。

### 6.3 AMD AVIC / x2AVIC

AVIC 和 x2AVIC 可以加速 AMD 平台上的虚拟 APIC 访问、中断投递和部分 IPI。当前上游代码中：

- 传统 AVIC 的物理 APIC ID 上限为 254；
- 基本 x2AVIC 的上限为 511，即最多 512 个可寻址 vCPU；
- 支持 x2AVIC 扩展时，上限可提高到 4095，即 4096 个 vCPU。

但这些是 AVIC/x2AVIC 本身的容量，不等于 KVM 已用 AVIC 直接加速 L2。

当前上游 KVM 的 `avic_vcpu_get_apicv_inhibit_reasons()` 在 `is_guest_mode(vcpu)` 时返回 nested inhibit，也就是运行 L2 时抑制 AVIC。因此：

> AVIC/x2AVIC 是成熟的单层 AMD 中断虚拟化能力，但在当前上游 KVM 中不能列为已经加速 L2 的通用 nested interrupt datapath。

### 6.4 IOMMU AVIC / Posted Interrupt

IOMMU 可以把设备中断重映射到 Guest interrupt descriptor，减少 Host 软件介入。它对设备直通和普通虚拟机非常重要。

但“设备中断直接进入 L2”还需要：

- L2 可见或被代理的设备分配模型；
- 两层 IOMMU 地址空间与 interrupt remapping 协调；
- L0、L1 对目标 vCPU/descriptor 的共同管理；
- Hypervisor 对 nested interrupt posting 的实现支持。

因此，IOMMU AVIC 或 Intel posted interrupt 本身不能证明嵌套设备中断已经绕过 L0/L1。

### 6.5 Immediate-exit

KVM nVMX 的 immediate-exit 用于一个事件重注入的正确性问题：当必须先把事件注入 L2、又需要尽快重新评估 L1 pending event 时，KVM 请求 CPU 在进入 L2 后立即退出。

它的目标是避免 L1 事件丢失或长期延迟。这个机制会故意增加一次快速退出，不应被列为一般吞吐性能优化。更准确的分类是：

```text
嵌套事件注入的正确性与延迟控制机制
```

---

## 7. I/O、定时器与调度路径

### 7.1 避免两层设备模型

传统嵌套 virtio 路径可能是：

```text
L2 virtio frontend
      │
      ▼
L1 虚拟设备/backend
      │
      ▼
L1 看到的虚拟设备
      │
      ▼
L0 backend / 物理设备
```

通知、descriptor 处理、中断和数据 copy 都可能经历两层，容易产生 exit multiplication。

可选优化包括：

- 尽量缩短 L2→L0 的数据路径；
- 使用 vhost、批处理和 multiqueue 降低每 I/O 固定成本；
- 在平台支持时，把 VF 或其他设备直接分配给更接近数据面的层级；
- 通过 polling 在极端低延迟场景减少中断，但要评估 CPU 占用；
- 避免在 L1 和 L0 同时重复执行不必要的网络或存储功能。

设备直通到 L2 会涉及 nested IOMMU、DMA 隔离、迁移和安全问题，不能作为所有生产环境都可用的通用开关。

### 7.2 时间虚拟化

嵌套时间路径需要组合 L0 和 L1 的：

- TSC offset；
- TSC scaling ratio；
- timer deadline；
- VMX preemption timer 或 SVM timer 语义；
- steal time 和调度延迟。

如果硬件和 KVM 支持 TSC scaling，L0 可以把多层 offset/ratio 合成为 L2 的有效变换，减少软件模拟。否则，频繁读取时间、编程 timer 或迁移 vCPU 可能产生更多退出和校正成本。

### 7.3 调度和拓扑

常见的部署级优化包括：

- 保持 L1/L2 vCPU 拓扑与物理拓扑一致；
- 避免把高通信量的 L2 vCPU 分散到不同 NUMA node；
- 为 latency-sensitive workload 配置 CPU pinning 和中断亲和性；
- 确保 L1 的 vCPU 数量足以承载其 L2 vCPU，而不是严重 overcommit；
- 谨慎使用 halt polling：它可以降低唤醒延迟，但会消耗宿主 CPU；
- 同时观察 L0 和 L1 的 steal time，避免只在 L2 内部做出错误诊断。

这些优化不改变 VMX/SVM 架构，但在生产环境中的收益常常不低于单个硬件特性。

---

## 8. Direct Virtual Hardware（DVH）：研究方案

DVH 是 Columbia University 在 ASPLOS 2020 提出的研究方案，目标是让 L0 直接向 L2 提供特定虚拟硬件接口，减少由 L1 处理设备或事件导致的 exit multiplication。

论文提出的四个机制是：

1. **Virtual-passthrough**：把 L0 提供的虚拟设备直接分配给 L2，而不是让 L1 再构造一层设备模型；
2. **Virtual timers**：由 L0 直接提供 L2 可用的虚拟 timer；
3. **Virtual IPIs**：让 L0 根据 L1 提供的 vCPU 映射直接处理 L2 IPI；
4. **Virtual idle**：避免 L2 idle 指令在多个 Hypervisor 层级重复模拟。

原文将其概括为“Direct virtual CPU、memory、I/O、timer”，并称 L0 全面接管 L2 调度和内存管理，这与论文实际提出的四个机制不符。

论文在修改后的 KVM 原型上报告，部分真实 workload 相比基线嵌套 KVM 提升超过一个数量级，并在不少场景接近非嵌套性能。这些结论应按研究结果理解：

- 对比的是论文定义的基线与特定 workload；
- 需要 Guest Hypervisor 配合配置 DVH；
- 不是 Linux 上游 KVM 的通用生产功能；
- “超过一个数量级”不能外推到 CPU-bound 或所有 I/O workload。

---

## 9. 当前能力与成熟度

与其绑定容易过时的“首次合入版本”，更可靠的是描述当前上游状态和启用条件：

| 优化项 | 主要路径 | 当前上游状态 | 关键条件或限制 |
| --- | --- | --- | --- |
| VMCS Shadowing | Intel L1 VMREAD/VMWRITE | 已实现 | Host CPU 能力、`enable_shadow_vmcs`、KVM 配置 |
| Enlightened VMCS | Hyper-V on VMX | 已实现 | Hyper-V CPUID/ABI、KVM/用户空间暴露、Guest 支持 |
| VMCB Clean Bits | AMD VMRUN 与 VMCB02 合成 | 已实现 | CPU 支持 VMCB state caching；软件正确维护 clean bits |
| Enlightened VMCB/MSR bitmap | Hyper-V on SVM | 已实现 | Hyper-V nested feature 协商 |
| Shadow EPT/NPT | L2 内存翻译 | KVM 核心路径 | EPT/NPT、shadow MMU、内存槽与权限 |
| L2 `vpid02` | Intel nested TLB tag | 已实现 | L0 VPID、L1 为 L2 启用 VPID |
| L2 独立 AMD ASID | AMD nested TLB tag | **未合入当前上游** | 2025 RFC 方案；当前仍共享 ASID 并在转换时 flush |
| Nested posted interrupt | Intel nested interrupt | 已实现但有条件 | APICv、L1 控制、descriptor、IOMMU/目标状态 |
| AVIC/x2AVIC 加速 L2 | AMD nested interrupt | **当前 KVM 抑制** | 运行 L2 时存在 nested inhibit |
| Direct Virtual Flush | Hyper-V L2 TLB flush | 已实现 | eVMCS/enlightened VMCB、assist page、CPUID 协商 |
| Immediate-exit | nVMX 事件正确性 | 已实现 | 是正确性/延迟机制，不是通用吞吐优化 |
| DVH | 直接虚拟硬件 | 研究原型 | 未作为通用方案进入上游 |
| XGEMINI 类大页策略 | 内存/TLB | 学术研究 | 不应标记为 Linux KVM 生产特性 |

“上游已实现”不等于默认启用。还需要结合：

- CPU capability；
- KVM module parameter；
- 内核配置项；
- QEMU/libvirt CPU model；
- L1 Hypervisor 是否使用该接口；
- Live migration compatibility；
- 发行版 backport 策略。

---

## 10. 如何正确引用性能数据

### 10.1 Turtles Project

Turtles Project 的“6～8%”是 **as low as** 的历史研究结论，不是所有 workload 的统一开销。

论文中 KVM-on-KVM 的具体结果包括：

- kernbench：嵌套相对单层虚拟化开销约 14.5%；
- SPECjbb：嵌套相对单层性能下降约 7.8%；
- 在实验性地扣除 Intel VMREAD/VMWRITE 开销后，分别约为 10.3% 和 6.3%。

因此，把这项工作概括成“常见 workload 都只有 6～8% 开销”会隐藏基准差异和实验条件。

### 10.2 “L2 达到 L1 的 80%”

如果没有同时给出以下信息，这个数字不应出现在结论中：

- 使用的 benchmark；
- Host CPU 和微架构；
- L0/L1/L2 Hypervisor 与内核版本；
- 是否启用 Shadow VMCS、nested EPT、VPID、APICv；
- L1 与 L2 的 CPU、内存和设备配置；
- 对比的是吞吐、延迟还是执行时间。

组合启用多项优化后的结果也不能全部归因于 VMCS Shadowing。

### 10.3 eVMCS 与 SVM enlightenment

原文引用的“Windows 启动 42 秒降至 29 秒”来自 Hyper-V nested virtualization 在 AMD/SVM 方向的特定 patchset 测试，不能标成 Intel eVMCS 的通用收益。

启动时间还同时受磁盘 backend、固件、vCPU 数、设备初始化和缓存状态影响。此类数据适合作为 case study，不适合作为跨平台结论。

### 10.4 DVH

DVH 的“超过一个数量级”是论文原型相对其实验基线、在特定真实 workload 上得到的结果。准确表述应包含“研究原型”“部分 workload”和“相对论文基线”三个限定词。

---

## 11. 建议的优化优先级

### 第一优先级：确认基础加速路径

1. L0 确实使用 KVM 硬件加速，而不是 TCG；
2. L1 能看到 VMX/SVM，并且嵌套能力已启用；
3. Intel EPT 或 AMD NPT 已启用；
4. Intel Host 支持时启用 VMCS Shadowing 与 VPID；
5. 使用合理的 L1/L2 CPU model，避免意外隐藏能力；
6. 检查发行版是否覆盖了上游 module parameter 默认值。

### 第二优先级：减少地址翻译与 TLB 成本

1. 检查 L0、L1、L2 的实际大页使用，而不只是配置文件；
2. 避免频繁修改 EPT12/NPT12；
3. 减少内存 balloon、迁移、碎片化和脏页跟踪导致的大页拆分；
4. 对 Intel 检查 L2 VPID 是否真正启用；
5. 对 AMD 不要假定当前 KVM 已有独立 nested ASID。

### 第三优先级：按 workload 缩短 I/O 和中断路径

1. 网络/存储 workload 优先检查两层 virtio backend；
2. IPI 密集 workload 检查 vCPU placement、APIC 模式和跨 NUMA 通信；
3. 设备直通场景同时检查 IOMMU、interrupt remapping 和迁移需求；
4. Hyper-V on KVM 场景检查 eVMCS、enlightened MSR bitmap 和 Direct Virtual Flush；
5. 不要因为 Host 支持 AVIC/x2AVIC 就假定 L2 已获得 AVIC 加速。

### 第四优先级：减少调度抖动

1. 对齐 vCPU、NUMA 和中断亲和性；
2. 避免 L1 严重 overcommit 后再在其中过量创建 L2 vCPU；
3. 同时观察 L0、L1 和 L2 的 run queue、steal time 与 CPU frequency；
4. 通过 A/B 测试评估 halt polling、busy polling 和 CPU pinning。

---

## 12. 测量方法

### 12.1 建立三个基线

至少比较：

1. workload 运行在物理 Host；
2. workload 运行在单层 Guest；
3. workload 运行在 L2。

只有 L1 与 L2 对比，容易把单层虚拟化本身的开销误算为嵌套开销。

### 12.2 一次只改变一个变量

建议分开测试：

- Shadow VMCS 开/关；
- VPID 开/关；
- 4 KiB page 与 2 MiB/1 GiB page；
- APICv/posted interrupt；
- eVMCS/Direct Virtual Flush；
- vCPU pinning 与默认调度；
- 单层 virtio 与两层 virtio。

### 12.3 同时记录时间与路径指标

仅记录 benchmark 总时间不足以解释原因。还应观察：

- L0 的 VM Exit 类型和次数；
- L2→L1 退出转发次数；
- VMREAD/VMWRITE、I/O、MSR、EPT/NPT fault 等退出；
- TLB miss、page walk、remote TLB shootdown；
- vCPU wakeup、IPI 和中断注入延迟；
- L0/L1 的 CPU 占用与 steal time；
- 大页命中、拆分和 NUMA locality；
- I/O backend 的 queue depth、batch size 与 copy 次数。

常用入口包括 `perf kvm stat`、KVM tracepoints、`trace-cmd`、`perf stat` 以及 L0/L1 两层的调度和内存统计。具体事件名随内核和 CPU PMU 变化，应以当前系统列出的事件为准。

---

## 13. 总结

1. 嵌套虚拟化的核心问题是 exit multiplication、三段逻辑地址翻译、TLB 失效传播、中断转发和两层 I/O 数据路径。
2. Intel VMCS Shadowing 和 Hyper-V eVMCS 都减少 L1 控制结构访问开销，但一个是硬件 Shadow VMCS，一个是半虚拟化内存 ABI。
3. AMD VMCB Clean Bits 优化 VMRUN 状态缓存，并可帮助 KVM 跳过部分 VMCB12→VMCB02 复制；它不是 VMCS Shadowing 的等价物。
4. KVM 使用 EPT02/NPT02 把 EPT12/NPT12 与 EPT01/NPT01 合成，硬件并不会直接执行三层页表翻译。
5. 当前 KVM nVMX 已使用独立 `vpid02`；当前 nSVM 仍共用 ASID 并在嵌套转换时刷新，独立 nested ASID 仍是未合入 RFC。
6. Intel nested posted interrupt 已有实现但受多项条件限制；AMD AVIC/x2AVIC 在当前 KVM 运行 L2 时被抑制。
7. Hyper-V Direct Virtual Flush 已有上游实现，不应继续标记为 2022 WIP。
8. Immediate-exit 是事件注入正确性和延迟机制，不是一般吞吐优化。
9. DVH 的四项机制是 virtual-passthrough、virtual timers、virtual IPIs 和 virtual idle；它仍属于研究方案。
10. 任何性能百分比都必须附带 workload、平台、版本、基线和启用特性，不能把多项组合优化的收益归因于单一机制。

---

## 14. 参考资料

### 架构与接口规范

1. [Intel® 64 and IA-32 Architectures Software Developer’s Manual, Volume 3C](https://cdrdv2.intel.com/v1/dl/getContent/671506)。
2. [AMD64 Architecture Programmer’s Manual, Volume 2: System Programming](https://docs.amd.com/v/u/en-US/24593_3.44_APM_Vol2)。
3. [Microsoft Hypervisor Top-Level Functional Specification: Nested Virtualization](https://learn.microsoft.com/en-us/virtualization/hyper-v-on-windows/tlfs/nested-virtualization)。
4. [Microsoft TLFS: HV_SVM_ENLIGHTENED_VMCB_FIELDS](https://learn.microsoft.com/en-us/virtualization/hyper-v-on-windows/tlfs/datatypes/hv_svm_enlightened_vmcb_fields)。

### Linux KVM 文档与源码

5. [Linux Kernel Documentation: Running nested guests with KVM](https://www.kernel.org/doc/html/next/virt/kvm/x86/running-nested-guests.html)。
6. [Linux Kernel Documentation: Nested VMX](https://www.kernel.org/doc/html/latest/virt/kvm/x86/nested-vmx.html)。
7. [Linux Kernel Documentation: The x86 KVM shadow MMU](https://docs.kernel.org/virt/kvm/x86/mmu.html)。
8. [Linux KVM VMX `nested.c`](https://github.com/torvalds/linux/blob/master/arch/x86/kvm/vmx/nested.c)。
9. [Linux KVM VMX `vmx.c`](https://github.com/torvalds/linux/blob/master/arch/x86/kvm/vmx/vmx.c)。
10. [Linux KVM SVM `nested.c`](https://github.com/torvalds/linux/blob/master/arch/x86/kvm/svm/nested.c)。
11. [Linux KVM SVM `svm.c`](https://github.com/torvalds/linux/blob/master/arch/x86/kvm/svm/svm.c)。
12. [Linux KVM SVM `avic.c`](https://github.com/torvalds/linux/blob/master/arch/x86/kvm/svm/avic.c)。
13. [Linux SVM architecture definitions](https://github.com/torvalds/linux/blob/master/arch/x86/include/asm/svm.h)。
14. [RFC: KVM SVM Rework ASID management](https://patchew.org/linux/20250326193619.3714986-1-yosry.ahmed%40linux.dev/)。

### 论文与历史资料

15. [The Turtles Project: Design and Implementation of Nested Virtualization, OSDI 2010](https://www.usenix.org/events/osdi10/tech/full_papers/Ben-Yehuda.pdf)。
16. [Nested EPT to Make Nested VMX Faster, KVM Forum 2013](https://www.linux-kvm.org/images/8/8c/Kvm-forum-2013-nested-ept.pdf)。
17. [Improving KVM x86 Nested Virtualization](https://events19.linuxfoundation.org/wp-content/uploads/2017/12/Improving-KVM-x86-Nested-Virtualization-Liran-Alon-Oracle.pdf)。
18. [Optimizing Nested Virtualization Performance Using Direct Virtual Hardware, ASPLOS 2020](https://www.cs.columbia.edu/~nieh/pubs/asplos2020_dvh.pdf)。
19. [Linux Transparent Hugepage Documentation](https://www.kernel.org/doc/html/latest/admin-guide/mm/transhuge.html)。

> 上游 `master` 链接用于说明 2026 年 7 月核验时的实现。分析某个发行版或稳定内核时，应切换到对应 tag 或发行版源码。
