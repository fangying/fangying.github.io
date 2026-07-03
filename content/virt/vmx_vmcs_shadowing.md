Title: VMCS Shadowing 技术详解
Date: 2026-7-3 10:00
Modified: 2026-7-3 10:00
Tags: virtualization, nested-virt
Slug: vmx-vmcs-shadowing
Status: published
Authors: Yori Fang
Summary: 从 Intel VMX 架构语义出发，详解 VMCS Shadowing 的原理、VMREAD/VMWRITE 退出判定、KVM 中 VMCS01/VMCS12/Shadow VMCS/VMCS02 的一致性维护，以及 AMD SVM 中 VMCB Clean Bits 的对应机制。

# VMCS Shadowing 技术详解

本文从 Intel VMX 的架构语义出发，说明 VMCS Shadowing 为什么存在、硬件如何决定 `VMREAD`/`VMWRITE` 是否退出，以及 Linux KVM 如何在 `VMCS01`、`VMCS12`、Shadow VMCS 和 `VMCS02` 之间维护一致性。文末还会说明 AMD SVM 为什么没有完全对应的机制，以及 VMCB Clean Bits 真正优化的是什么。

> 本文中的层级约定：
>
> - **L0**：运行在物理机上的 Hypervisor，例如宿主机 KVM。
> - **L1**：运行在 L0 虚拟机中的 Guest Hypervisor，例如虚拟机内的 KVM、Xen 或 Hyper-V。
> - **L2**：由 L1 创建的嵌套虚拟机。

---

## 1. VMCS Shadowing 要解决什么问题

### 1.1 VMCS 不是一块可由软件随意解析的普通结构体

Intel VMX 使用 VMCS（Virtual-Machine Control Structure）保存和控制虚拟机的运行状态。每个 VMCS 都关联一块最多 4 KiB 的 **VMCS region**，但除开头的 revision identifier 和 VMX-abort indicator 外，其余布局属于实现相关信息，软件不能依赖其内存格式。

软件必须使用下列 VMX 指令管理 VMCS：

- `VMPTRLD`：设置当前 VMCS。
- `VMPTRST`：读取当前 VMCS 指针。
- `VMREAD`：读取当前 VMCS 的字段。
- `VMWRITE`：写入当前 VMCS 的字段。
- `VMCLEAR`：使 VMCS 变为 inactive，并将其 launch state 置为 clear。
- `VMLAUNCH` / `VMRESUME`：使用当前的普通 VMCS 执行 VM Entry。

将 VMCS 简单描述为“存储在片上内存中”并不准确。Intel SDM 的表述是：处理器为 VMCS 关联一块内存区域，并且可以把 active VMCS 的状态保存在内存中、处理器内部，或者两者同时保存。真正导致嵌套虚拟化问题的关键是：**VMCS 的字段必须通过专用 VMX 指令访问，而不是它是否物理地位于片上。**

### 1.2 为什么 L1 的 VMREAD/VMWRITE 会退出到 L0

运行 L1 时，物理处理器处于 VMX non-root operation。默认情况下，L1 在 non-root operation 中执行 `VMREAD` 或 `VMWRITE` 会触发 VM Exit，由 L0 模拟该指令。

没有 VMCS Shadowing 时，一次字段访问大致经历：

```text
L1 执行 VMREAD/VMWRITE
          │
          ▼
物理 VM Exit 到 L0
          │
          ▼
L0 检查字段编码和访问权限，并读写 VMCS12 的软件表示
          │
          ▼
L0 执行 VM Entry，返回 L1
```

L1 在准备 L2 的 VM Entry、处理 L2 的 VM Exit 或切换虚拟 CPU 时，通常需要访问多个 VMCS 字段。如果每次字段访问都产生一次 L1→L0 VM Exit，退出、模拟和重新进入的成本会快速累积。

VMCS Shadowing 的目标是：**让一部分来自 L1 的 VMREAD/VMWRITE 直接由硬件作用于一个 Shadow VMCS，不再逐条退出到 L0。**

需要强调的是，它只优化这一类访问，并不会消除 `VMLAUNCH`、`VMRESUME`、`VMPTRLD`、`VMCLEAR` 等 VMX 指令产生的退出，也不会消除嵌套页表、虚拟中断和 I/O 虚拟化的成本。

---

## 2. 理清四种容易混淆的 VMCS

Linux KVM 的嵌套 VMX 实现通常使用以下命名：

| 名称 | 性质 | 作用 |
| --- | --- | --- |
| **VMCS01** | L0 创建的硬件 VMCS | 物理处理器用它运行 L1。L1 执行 `VMREAD`/`VMWRITE` 时，生效的是 VMCS01 中的 VMCS Shadowing 控制、bitmap 地址和 VMCS link pointer。 |
| **VMCS12** | L0 对“L1 为 L2 创建的 VMCS”的软件表示 | 表示 L1 希望用于运行 L2 的配置和状态。KVM 会缓存 L1 Guest Physical Memory 中的 VMCS region，并以 `struct vmcs12` 等内部数据结构处理它。 |
| **Shadow VMCS** | L0 分配的硬件 Shadow VMCS | VMCS01 的 VMCS link pointer 指向它。被 bitmap 放行的 L1 `VMREAD`/`VMWRITE` 直接访问它。它只是 VMCS12 部分字段的硬件镜像，不能用于 VM Entry。 |
| **VMCS02** | L0 创建的硬件普通 VMCS | 物理处理器实际用它运行 L2。它由 L1 的 VMCS12 意图与 L0 自身的控制和限制合成。 |

最重要的关系是：

```text
运行 L1 时

                  VMCS link pointer
VMCS01  ------------------------------------>  Shadow VMCS
  │                                               │
  │ 物理处理器用 VMCS01 运行 L1                  │ 被放行的 VMREAD/VMWRITE
  │                                               │ 直接读写这里
  ▼                                               ▼
 L1                                        VMCS12 部分字段的镜像


运行 L2 时

VMCS12（L1 的意图） + L0 的限制与宿主状态
                         │
                         ▼
                       VMCS02
                         │
                         ▼
                  物理处理器运行 L2
```

因此，“Shadow VMCS 与 VMCS02 关联”是容易造成误解的说法。在 KVM 中，用于加速 L1 字段访问的 Shadow VMCS 链接在 **VMCS01** 上；VMCS02 是运行 L2 的另一个普通 VMCS。

---

## 3. Intel VMCS Shadowing 的架构机制

### 3.1 支持能力和控制位

VMCS Shadowing 是 secondary processor-based VM-execution control 的 bit 14。

软件应读取 `IA32_VMX_PROCBASED_CTLS2`，检查该控制位是否允许设置为 1。仅仅发现 `CPUID.VMX=1` 并不能证明处理器支持 VMCS Shadowing。

经验上，这项能力从部分第四代 Intel Core vPro/Haswell 时代的处理器开始出现；但软件不应根据“第几代 Core”或产品系列名称作最终判断。**VMX capability MSR 才是权威依据。**

### 3.2 Ordinary VMCS 与 Shadow VMCS

VMCS region 开头 4 字节的 bit 31 是 shadow-VMCS indicator：

- `0`：ordinary VMCS，可以用于 VM Entry。
- `1`：shadow VMCS，不能用于 VM Entry。

Shadow VMCS 的用途不是直接运行虚拟机，而是允许 VMX non-root 中的软件通过 `VMREAD` 和 `VMWRITE` 访问它。

### 3.3 VMCS link pointer

当前普通 VMCS 中包含一个 64 位 `VMCS link pointer` 字段。

当 VMCS Shadowing 控制为 1 时，成功的 VM Entry 会检查该指针指向的 VMCS region 是否：

- 地址满足对齐和物理地址宽度要求；
- revision identifier 与当前处理器一致；
- shadow-VMCS indicator 为 1。

进入 L1 后，如果某次 `VMREAD`/`VMWRITE` 没有被 bitmap 拦截，处理器访问的是 **VMCS link pointer 指向的 Shadow VMCS**，而不是当前普通 VMCS 本身。

### 3.4 VMREAD bitmap 与 VMWRITE bitmap

硬件为 VMCS Shadowing 定义了两个各 4 KiB 的 bitmap：

- VMREAD bitmap：控制 L1 对各字段的读取是否退出。
- VMWRITE bitmap：控制 L1 对各字段的写入是否退出。

bitmap 使用 VMCS field encoding 的低 15 位作为索引。其语义是：

- 对应 bit 为 **0**：允许硬件直接访问 Shadow VMCS，不产生 VM Exit。
- 对应 bit 为 **1**：产生 VM Exit，由 L0 模拟。

对于在 64 位模式下 field encoding 的 bit 63:15 不全为 0 的情况，`VMREAD`/`VMWRITE` 也会退出。

可以把处理器的核心判断简化为：

```text
L1 在 VMX non-root 中执行 VMREAD(field)
    │
    ├─ VMCS shadowing = 0 ────────────────> VM Exit
    │
    ├─ field encoding 高位非法 ───────────> VM Exit
    │
    ├─ VMREAD bitmap[field] = 1 ─────────> VM Exit
    │
    └─ VMREAD bitmap[field] = 0
             │
             ▼
       从 VMCS link pointer 指向的 Shadow VMCS 读取
```

`VMWRITE` 的判断相同，只是使用 VMWRITE bitmap。

bitmap 的价值不仅是性能，还包括正确性和隔离性。L0 可以只放行自己能够可靠同步的字段，而继续拦截需要校验、模拟或特殊处理的字段。

---

## 4. KVM 中的完整工作流程

### 4.1 L1 执行 VMPTRLD：选择 VMCS12

L1 的 `VMPTRLD` 仍然会退出到 L0。KVM 模拟该指令，记录 L1 当前选择的 VMCS12，并在 VMCS01 中：

1. 设置 `SECONDARY_EXEC_SHADOW_VMCS`；
2. 将 `VMCS_LINK_POINTER` 指向 KVM 为该 vCPU 分配的硬件 Shadow VMCS；
3. 标记 VMCS12 的字段需要同步到 Shadow VMCS。

在再次进入 L1 之前，KVM 将需要由 L1 直接读取或修改的字段从 VMCS12 复制到 Shadow VMCS。

### 4.2 L1 配置 L2：大部分常用字段可直接访问

L1 执行 `VMREAD`/`VMWRITE` 时：

- 对 bitmap 为 0 的字段，处理器直接访问 Shadow VMCS；
- 对 bitmap 为 1 的字段，处理器退出到 L0，KVM 完成合法性检查和模拟。

KVM 并没有让 L1 直接修改 VMCS02。因此，L1 无法通过 Shadow VMCS 绕过 L0 的控制。Shadow VMCS 只是 L1 所见 VMCS12 的一个受控镜像。

### 4.3 L1 执行 VMLAUNCH/VMRESUME：进入 L2 前回收修改

`VMLAUNCH` 和 `VMRESUME` 仍会退出到 L0。KVM 的主要处理过程是：

1. 把 Shadow VMCS 中允许 L1 直接写入的字段复制回 VMCS12；
2. 按 Intel VMX 规则检查 VMCS12 的控制字段和 Guest/Host 状态；
3. 将 VMCS12 的配置与 L0 自身的限制合成为 VMCS02；
4. 切换到 VMCS02；
5. 使用 VMCS02 执行真正的硬件 VM Entry，运行 L2。

这也是 Shadow VMCS 不能直接用于 VM Entry 的原因：L0 必须保留验证、合并和强制执行宿主策略的机会。

### 4.4 L2 退出：决定是由 L0 处理还是转交 L1

L2 发生物理 VM Exit 后首先到达 L0，因为物理处理器运行 L2 时使用的是 VMCS02。

L0 随后判断：

- 如果退出属于 L0 自己需要处理的事件，L0 处理后可直接恢复 L2；
- 如果按照 VMCS12 的设置应当把退出交给 L1，KVM 将 VMCS02 中的 Guest 状态和 VM-exit information 写入 VMCS12，恢复 L1 的 Host 状态，并准备返回 L1。

在重新运行 L1 之前，KVM 再把 VMCS12 中需要被 L1 直接读取的字段同步到 Shadow VMCS。这样 L1 随后的 `VMREAD` 可以直接看到 `VM_EXIT_REASON`、`EXIT_QUALIFICATION`、Guest RIP 等最新信息。

### 4.5 状态的“权威副本”会随执行层级变化

理解同步流程的一个好方法，是明确某一时刻哪个副本最新：

| 执行阶段 | 主要权威状态 | 原因 |
| --- | --- | --- |
| L1 正在配置当前 VMCS12 | Shadow VMCS 中的可直接写字段 | L1 的无退出 `VMWRITE` 直接修改 Shadow VMCS。 |
| L1 执行 VMLAUNCH/VMRESUME 后 | VMCS12，随后是 VMCS02 | KVM 先把 Shadow VMCS 的可写字段收回 VMCS12，再据此构造 VMCS02。 |
| L2 正在运行 | VMCS02 | 物理处理器使用 VMCS02 运行 L2，Guest 状态会随执行变化。 |
| 准备把 L2 的退出交给 L1 | VMCS12 | KVM将 VMCS02 的退出状态整理到 VMCS12。 |
| 即将重新进入 L1 | Shadow VMCS | KVM把 L1 可直接读取的字段从 VMCS12 更新到 Shadow VMCS。 |

所以不能把同步简单概括成“VMLAUNCH 前 VMCS12→Shadow，VM Exit 后 Shadow→VMCS12”。在典型 KVM 流程中，进入 L2 前最关键的方向是 **Shadow VMCS→VMCS12→VMCS02**；把 L2 退出交给 L1 时则是 **VMCS02→VMCS12→Shadow VMCS**。

---

## 5. KVM 为什么只 Shadow 一部分字段

上游 KVM 初始化 VMREAD/VMWRITE bitmap 时，先把所有 bit 设为 1，也就是默认全部拦截；随后只为明确支持的字段清零。

典型的直接读写字段包括：

- `CPU_BASED_VM_EXEC_CONTROL`
- `PIN_BASED_VM_EXEC_CONTROL`
- `EXCEPTION_BITMAP`
- `VM_ENTRY_INTR_INFO_FIELD`
- `GUEST_RIP`
- `GUEST_RSP`
- `GUEST_CR0`、`GUEST_CR3`、`GUEST_CR4`
- `GUEST_RFLAGS`
- `CR0_GUEST_HOST_MASK`、`CR4_GUEST_HOST_MASK`

典型的直接读取字段包括：

- `VM_EXIT_REASON`
- `VM_EXIT_INTR_INFO`
- `EXIT_QUALIFICATION`
- `GUEST_LINEAR_ADDRESS`
- `GUEST_PHYSICAL_ADDRESS`

具体列表会随 Linux 内核版本和硬件能力变化。例如，只有硬件真正支持 PML 或 VMX preemption timer 时，KVM 才能安全地把相关字段加入 Shadow VMCS 放行集合。

这种 allowlist 设计有三个作用：

1. **正确性**：对不支持或需要特殊语义的字段继续由 KVM 模拟；
2. **安全性**：L1 不能直接改变 L0 不愿放行的控制；
3. **兼容性**：KVM 可以在不同硬件实现上提供一致的嵌套 VMX 行为。

因此，“启用 VMCS Shadowing 后所有 VMREAD/VMWRITE 都不退出”是错误的。准确说法是：**bitmap 为 0 且编码有效的字段访问可以不退出。**

---

## 6. Intel CPU 与 Linux KVM 支持

### 6.1 不要仅按 CPU 代际判断

“Haswell 或更新”可以作为经验判断，但不能替代能力检测。不同 SKU、固件设置、宿主机 Hypervisor 暴露策略和云平台 CPU model 都可能改变最终可用能力。

权威判断顺序应是：

1. 处理器通过 VMX capability MSR 表明 secondary control bit 14 可设置为 1；
2. 宿主 Linux KVM 检测到该能力；
3. `kvm_intel` 没有通过模块参数禁用它。

### 6.2 KVM 模块参数

当前上游 KVM 的 `enable_shadow_vmcs` 默认值为 1；如果硬件不支持，KVM 会在初始化时自动关闭它。

可以检查：

```bash
cat /sys/module/kvm_intel/parameters/nested
cat /sys/module/kvm_intel/parameters/enable_shadow_vmcs
```

典型输出为：

```text
Y
Y
```

如需查看当前内核是否提供这些参数：

```bash
modinfo kvm_intel | grep -E 'nested|enable_shadow_vmcs'
```

旧内核或发行版明确关闭默认值时，可以在 `/etc/modprobe.d/kvm_intel.conf` 中配置：

```text
options kvm_intel nested=1 enable_shadow_vmcs=1
```

Linux 上游文档说明，x86 KVM 从 Linux 4.20 起默认启用 `nested`，但发行版可以覆盖默认值。修改模块参数后重新加载 `kvm_intel` 会影响正在运行的虚拟机，生产环境中应先安排停机或迁移。

此外，L1 还必须看到 VMX 能力。QEMU 常用 `-cpu host`，libvirt 常用 host-passthrough；否则即使 L0 支持 Shadow VMCS，L1 也未必能够运行 L2。

---

## 7. AMD SVM：为什么没有同样的字段访问问题

### 7.1 VMCB 的架构设计不同

AMD SVM 使用 VMCB（Virtual Machine Control Block）。VMCB 是一块 4 KiB、架构定义了字段布局的内存区域。Hypervisor 使用普通内存 load/store 读写 VMCB，并通过 `VMRUN` 的操作数提供 VMCB 的物理地址。

因此，在嵌套 SVM 中，L1 修改 VMCB12 的字段通常只是普通内存访问，不需要执行与 `VMREAD`/`VMWRITE` 对应的专用字段访问指令，也不会因为“读取一个 VMCB 字段”而必然产生 L1→L0 的 `#VMEXIT`。

这意味着 AMD 不需要一个与 Intel VMCS Shadowing 完全等价、专门用于消除逐字段指令退出的机制。

但这不代表嵌套 SVM 没有控制块合并成本：

```text
L1 普通内存读写 VMCB12
          │
          ▼
L1 执行 VMRUN
          │
          ▼
#VMEXIT 到 L0
          │
          ▼
L0 校验 VMCB12，并构造/更新用于实际运行 L2 的 VMCB02
          │
          ▼
L0 执行真正的 VMRUN
```

也就是说，AMD 避免的是 **逐字段 VMREAD/VMWRITE 退出问题**；L0 对嵌套 `VMRUN` 的拦截、VMCB12 校验、VMCB02 合并以及 L2 退出转发仍然存在。

### 7.2 VMCB Clean Bits 的真实含义

VMCB Clean Bits 与 VMCS Shadowing 不是等价机制。

支持 VMCB state caching 的处理器可以在一次 `#VMEXIT` 与后续 `VMRUN` 之间缓存部分 Guest 状态。VMCB Clean 字段用于告诉处理器，哪些内存中的 VMCB 字段相对硬件缓存没有被 Hypervisor 修改：

- clean bit 为 **1**：处理器可以使用缓存值；这是一个 hint，处理器也可以选择重新从 VMCB 加载。
- clean bit 为 **0**：处理器必须从 VMCB 重新加载对应字段。

当 Hypervisor 显式修改一组 VMCB 字段时，必须清零相应 clean bit。首次运行某个 Guest、把 Guest 迁移到另一个物理核心或移动 VMCB 的物理页时，必须按 AMD 手册要求清理相关状态，通常要把整个 VMCB Clean 字段置 0。

当前 AMD 架构手册定义的主要分组包括：

| Bit | 分组 | 代表字段 |
| ---: | --- | --- |
| 0 | `I` | intercept vectors、TSC offset、Pause Filter Count |
| 1 | `IOPM` | IOPM base、MSRPM base |
| 2 | `ASID` | ASID |
| 3 | `TPR` | 虚拟 TPR 和虚拟中断相关字段 |
| 4 | `NP` | Nested Paging 的 NCR3、Guest PAT |
| 5 | `CRx` | CR0、CR3、CR4、EFER |
| 6 | `DRx` | DR6、DR7 |
| 7 | `DT` | GDT/IDT base 与 limit |
| 8 | `SEG` | 段寄存器 selector/base/limit/attributes、CPL |
| 9 | `CR2` | CR2 |
| 10 | `LBR` | DebugCtl 和 last-branch 相关状态 |
| 11 | `AVIC` | AVIC 相关指针 |
| 12 | `CET` | S_CET、SSP、ISST_ADDR |

VMCB Clean Bits 优化的是 **处理器在 VMRUN 时是否需要从内存重新加载某组 Guest 状态**。它不负责消除 L1 的字段访问退出，也不直接解决 VMCB12 与 VMCB02 的软件同步问题。

---

## 8. Intel 与 AMD 的准确对比

| 维度 | Intel VMX | AMD SVM |
| --- | --- | --- |
| 控制块 | VMCS region 有内存载体，但字段布局不透明 | VMCB 是布局公开的 4 KiB 内存结构 |
| 字段访问 | 使用 `VMREAD`/`VMWRITE` | 使用普通内存 load/store |
| 嵌套环境中的逐字段退出 | 默认会发生，除非 VMCS Shadowing 与 bitmap 允许直通 | 架构上没有对应的专用字段访问指令，因此没有同样的问题 |
| 实际运行 L2 | L0 由 VMCS12 合成 VMCS02 | L0 通常由 VMCB12 合成/更新 VMCB02 |
| 相关硬件优化 | Shadow VMCS、VMREAD/VMWRITE bitmap | VMCB state caching 与 Clean Bits |
| Clean/Shadow 是否等价 | 不适用 | 不等价；它们优化不同路径 |

---

## 9. 性能收益应如何理解

### 9.1 被减少的成本

VMCS Shadowing 主要减少：

- L1 `VMREAD`/`VMWRITE` 导致的物理 VM Exit 次数；
- L0 对这些指令进行解码、权限检查和软件模拟的次数；
- 从 L0 重新进入 L1 的次数。

它把多个逐字段退出，转换为在关键边界处对一组允许字段进行同步。对于频繁读写 VMCS 字段的 L1 Hypervisor，收益可能很明显。

### 9.2 没有被消除的成本

以下开销仍然存在：

- L1 的 `VMLAUNCH`、`VMRESUME`、`VMPTRLD`、`VMCLEAR` 等 VMX 指令退出；
- VMCS12 的合法性检查；
- VMCS12 与 VMCS02 的合并；
- L2 的物理 VM Exit 及其转发；
- nested EPT、TLB、虚拟中断、设备 I/O 和调度开销；
- Shadow VMCS 与 VMCS12 之间的批量字段同步；
- `VMREAD`/`VMWRITE` 指令本身的执行成本。

所以不应把性能模型写成固定的“N 次 VM Exit 变为 0 次 VM Exit加两次同步”，也不应给出一个与 workload、内核版本、L1 Hypervisor 和其他嵌套优化无关的统一性能比例。

历史报告中常把 VMCS Shadowing 与 nested EPT、APIC virtualization 等特性一起测试。此类数据可以说明整套嵌套虚拟化优化的潜力，但不能把组合结果全部归因于 VMCS Shadowing。尤其是“L2 达到 L1 的约 80%”这类数字，必须同时给出测试平台、workload、基线和启用的全部特性，不能作为普遍结论。

### 9.3 建议的测量方法

评估 VMCS Shadowing 时，至少应保持以下条件一致：

1. 相同 CPU、BIOS、内核、QEMU 和 L1 Hypervisor；
2. 相同 L1/L2 vCPU 数量、内存和 CPU model；
3. 仅切换 `enable_shadow_vmcs`，其他特性保持不变；
4. 同时记录 workload 用时和 L0 的 KVM exit 统计；
5. 特别观察 VMREAD、VMWRITE 类退出是否明显减少；
6. 将 nested EPT、APICv、posted interrupt 等变量单独记录。

---

## 10. 常见混淆

| 概念 | 与 VMCS Shadowing 的区别 |
| --- | --- |
| **Shadow Paging** | 用软件维护 Guest 页表到 Host 页表的映射，与 VMCS 字段访问无关。 |
| **Nested EPT** | 合成 L2 GPA 到 Host PA 的二级地址转换，与 Shadow VMCS 是两条独立的优化路径。 |
| **Hyper-V Enlightened VMCS（eVMCS）** | 一种 Hyper-V/KVM 间的半虚拟化 VMCS 接口，使用内存结构和 clean-field 协议；不是 Intel 硬件 Shadow VMCS。 |
| **VMCB Clean Bits** | AMD 用来提示处理器能否复用缓存 Guest 状态的机制，不是 VMREAD/VMWRITE 的直通机制。 |
| **VMCS02** | 真正运行 L2 的普通 VMCS；Shadow VMCS 只是 VMCS12 部分字段的受控镜像。 |

---

## 11. 总结

1. Intel VMCS 有内存关联区域，但字段布局不透明，软件必须使用 VMX 指令访问；把它简单称为“片上内存结构”不准确。
2. 默认情况下，L1 在 VMX non-root 中执行 `VMREAD`/`VMWRITE` 会退出到 L0。
3. L0 在 **VMCS01** 中启用 VMCS Shadowing，并通过 VMCS link pointer 指向硬件 Shadow VMCS。
4. VMREAD/VMWRITE bitmap 的 **0 bit 表示允许直接访问**，**1 bit 表示退出**。
5. Shadow VMCS 不能用于 VM Entry，也不会让 L1 直接修改 VMCS02。
6. KVM 只 Shadow 明确支持的一部分字段，并在 L1/L2 切换边界维护 `Shadow VMCS ↔ VMCS12 ↔ VMCS02` 的一致性。
7. AMD VMCB 可由普通内存访问，因此不存在同样的逐字段指令退出问题；但嵌套 `VMRUN`、VMCB12/VMCB02 合并等开销仍然存在。
8. VMCB Clean Bits 优化 VMRUN 时的硬件状态重载，不是 VMCS Shadowing 的 AMD 等价物。
9. VMCS Shadowing 的收益取决于 L1 的 VMCS 访问模式和整套嵌套虚拟化配置，不能用单一比例概括。

---

## 12. 参考资料

1. [Intel® 64 and IA-32 Architectures Software Developer’s Manual, Volume 3C](https://cdrdv2.intel.com/v1/dl/getContent/671506)，重点参见 VMCS region、secondary processor-based controls、VMCS types、VMREAD/VMWRITE 和 VM-entry checks。
2. [Linux Kernel Documentation: Nested VMX](https://www.kernel.org/doc/html/latest/virt/kvm/x86/nested-vmx.html)。
3. [Linux Kernel Documentation: Running nested guests with KVM](https://www.kernel.org/doc/html/next/virt/kvm/x86/running-nested-guests.html)。
4. [Linux KVM `nested.c`](https://github.com/torvalds/linux/blob/master/arch/x86/kvm/vmx/nested.c)。
5. [Linux KVM `vmcs_shadow_fields.h`](https://github.com/torvalds/linux/blob/master/arch/x86/kvm/vmx/vmcs_shadow_fields.h)。
6. [AMD64 Architecture Programmer’s Manual, Volume 2: System Programming](https://docs.amd.com/v/u/en-US/24593_3.44_APM_Vol2)，重点参见 SVM、VMCB State Caching 和 VMCB Clean Bits。
7. [KVM Forum 2013: Nested EPT to Make Nested VMX Faster](https://www.linux-kvm.org/images/8/8c/Kvm-forum-2013-nested-ept.pdf)，仅作为历史性能与实现背景资料。

> 内容依据 2026 年 7 月可获得的 Intel、AMD 架构文档和 Linux 上游 KVM 实现复核。内核实现细节可能继续演进，分析特定版本时应以对应版本源码为准。
