---
Title:  Intel SMM
Date: 2026-7-31 23:00
Modified: 2026-7-31 23:00
Tags: Intel SMM, virtualization, KVM, QEMU, OVMF
Slug: intel-smm-virt
Status: published
Authors: Yori Fang
Summary: Intel SMM 模式详解及其在虚拟化场景下的实现
---

# Intel SMM 模式详解及虚拟化场景下的实现

> 本文分两部分：第一部分介绍 Intel x86 架构的系统管理模式（System Management Mode, SMM）的原理与关键机制；第二部分介绍在虚拟化场景下（以 KVM + QEMU + OVMF 为例）如何为虚拟机提供 SMM 能力。

---

## 目录

- [一、Intel SMM 模式详解](#一intel-smm-模式详解)
  - [1.1 什么是 SMM](#11-什么是-smm)
  - [1.2 SMM 的典型用途](#12-smm-的典型用途)
  - [1.3 进入 SMM：SMI 中断](#13-进入-smmsmi-中断)
  - [1.4 SMRAM 与 SMBASE](#14-smram-与-smbase)
  - [1.5 SMM 的执行环境与状态保存区](#15-smm-的执行环境与状态保存区)
  - [1.6 退出 SMM：RSM 指令](#16-退出-smmrsm-指令)
  - [1.7 SMRAM 的保护与锁定](#17-smram-的保护与锁定)
  - [1.8 SMM 的安全问题](#18-smm-的安全问题)
- [二、虚拟化场景如何为虚拟机提供 SMM](#二虚拟化场景如何为虚拟机提供-smm)
  - [2.1 为什么虚拟机需要 SMM](#21-为什么虚拟机需要-smm)
  - [2.2 整体架构：KVM + QEMU + OVMF 的三方协作](#22-整体架构kvm--qemu--ovmf-的三方协作)
  - [2.3 KVM 侧：世界切换与 SMRAM 隔离](#23-kvm-侧世界切换与-smram-隔离)
  - [2.4 QEMU 侧：芯片组模拟与 TSEG](#24-qemu-侧芯片组模拟与-tseg)
  - [2.5 OVMF/EDK2 侧：SMM 驱动栈](#25-ovmfedk2-侧smm-驱动栈)
  - [2.6 一次完整的虚拟机 SMI 流程](#26-一次完整的虚拟机-smi-流程)
  - [2.7 配置示例](#27-配置示例)
  - [2.8 限制与注意事项](#28-限制与注意事项)
- [三、总结](#三总结)
- [参考资料](#参考资料)

---

## 一、Intel SMM 模式详解

### 1.1 什么是 SMM

系统管理模式（System Management Mode, SMM）是 x86 处理器的一种特殊运行模式，它提供一个**对操作系统透明、隔离的执行环境**，用于执行电源管理、硬件错误处理等关键系统管理任务，且只能通过系统管理中断（System Management Interrupt, SMI）进入 [1]。

SMM 由 Intel 在 20 世纪 90 年代初随 386SL 处理器引入，此后成为所有 Intel 处理器统一的标准体系结构特性 [1]。它是 x86 处理器四种主要运行模式（实模式、保护模式、虚拟 8086 模式、系统管理模式）之一，但相较其他模式一直较为"隐蔽"。

SMM 的核心特点可以概括为：

- **最高特权**：SMM 常被称为"Ring -2"，其权限高于操作系统内核（Ring 0）和 Hypervisor（Ring -1）。
- **OS 透明**：进入/退出 SMM 对操作系统完全不可见，OS 无法感知或拦截。
- **代码来源于固件**：在 SMM 中执行的代码（称为 SMI handler）由 BIOS/UEFI 固件在启动时装载 [4]。
- **独立地址空间**：SMM 代码运行在受保护的专用内存区域 SMRAM 中 [2]。

### 1.2 SMM 的典型用途

SMM 主要被固件（BIOS/UEFI）用于处理需要脱离操作系统、直接与硬件交互的敏感任务，典型场景包括：

- 电源管理（如 ACPI 之前/之外的电源状态切换、设备待机/唤醒）
- 热管理与风扇控制（温度监控）
- 硬件错误处理（如 RAS、内存 ECC 错误处理）
- 传统硬件的仿真与兼容（如 USB 键盘模拟 PS/2、legacy 设备支持）
- OEM 专有代码执行
- **UEFI 安全启动中的变量保护**（在启用 SMM 的固件中，认证变量的写入由 SMM 内的特权驱动完成，见第二部分）[4]

在 SMM 中，所有 I/O 和系统指令都可用，SMI handler 可以读取和修改被保存的处理器上下文，因为该上下文就存放在 SMRAM 内 [3]。

### 1.3 进入 SMM：SMI 中断

进入 SMM 的**唯一途径**是 SMI（System Management Interrupt）。SMI 是一种独立于普通可屏蔽中断（INTR）和不可屏蔽中断（NMI）之外的最高优先级中断，通常有两种触发来源 [1]：

- **硬件 SMI**：由主板逻辑/芯片组通过专用的 SMI# 引脚（或消息）触发，例如温度告警、电源事件等。
- **软件 SMI**：由系统软件通过对某个被主板逻辑视为特殊的 I/O 端口进行写操作触发，最常见的是写 `0x0B2` 端口（APM 控制端口）[1]。这也是 OS/固件"主动调用"SMI handler 的常用方式。

当处理器接收到 SMI 后，会：

1. 保存当前处理器完整上下文（寄存器状态）到 SMRAM 的状态保存区；
2. 切换到 SMM 的执行环境；
3. 从 `SMBASE + 0x8000` 处取第一条指令开始执行 SMI handler（默认 SMBASE 为 `0x30000`，因此默认入口为 `0x38000`，此时 `CS = 0x3000`、`EIP = 0x8000`）[1]。

### 1.4 SMRAM 与 SMBASE

**SMRAM** 是一段专用的、受保护的物理内存区域，用于存放 SMI handler 的代码、数据、堆栈，以及被中断时保存的处理器上下文 [2]。其关键属性：

- SMRAM 映射到处理器的物理地址空间。处理器用它来保存上下文、存放 SMI handler 代码/数据/堆栈，以及系统管理信息和 OEM 专有信息。
- **可被锁定**：SMRAM 一旦锁定，即使是运行在保护模式最高特权级（Ring 0）的软件也无法访问它 [2]。这是 SMM 隔离性的关键。

**SMBASE** 是 CPU 内部寄存器，保存了该处理器 SMRAM 的基地址 [2][3]。

- 默认 SMBASE 为 `0x30000`，SMI handler 入口位于 `SMBASE + 0x8000`。早期 386 要求 SMM handler 从 `0x38000` 开始执行且不可重定位；`0x3FE00`–`0x3FFFF`（512 字节）保留给 CPU 且必须是 RAM [10]。
- SMBASE 是可被修改（重定位）的。在多核系统中，固件通常为每个逻辑处理器设置**各自独立的 SMBASE**，从而让每个核心拥有自己的状态保存区，避免多核同时进入 SMM 时相互覆盖上下文。

### 1.5 SMM 的执行环境与状态保存区

进入 SMM 后，处理器切换到一个类似实模式（big real mode）的执行环境：段寄存器行为、地址空间访问方式都与保护模式不同，寻址范围可达 4GB。

**状态保存区（State Save Map / State Save Area）** 是 SMRAM 中的一块固定布局区域，位于 SMRAM 的高地址端。进入 SMM 时，CPU 自动把通用寄存器、段寄存器、控制寄存器、EFLAGS、EIP、以及各类隐藏描述符等上下文写入该区域。SMI handler 可以直接读写这块区域，从而：

- 检查是谁/什么原因触发了 SMI；
- 修改即将恢复的执行上下文（例如改写返回地址、寄存器值），这也是 SMM 被用作 rootkit 载体的原因之一 [3]。

状态保存区在 32 位和 64 位下有不同的字段布局与偏移（例如 KVM 源码中对 SMRAM64 各字段偏移做了严格校验）[8]。

### 1.6 退出 SMM：RSM 指令

SMI handler 处理完毕后，通过执行 **`RSM`（Resume from System Management Mode）** 指令退出 SMM [2]。`RSM` 会：

1. 从 SMRAM 状态保存区恢复此前保存的处理器上下文（可能是被 handler 修改过的版本）；
2. 将处理器切换回进入 SMM 之前的运行模式（实模式/保护模式等）；
3. 从被中断处继续执行。

`RSM` 是一条**只能在 SMM 内执行**的特权指令；在 SMM 之外执行会触发 `#UD`（无效操作码异常）。

### 1.7 SMRAM 的保护与锁定

SMRAM 的隔离依赖芯片组/内存控制器提供的一组控制位，典型的有：

- **D_OPEN**：置位时，SMRAM 对非 SMM 的普通访问也"打开"，通常仅在固件初始化阶段用于装载 SMI handler。
- **D_CLOSE**：控制 SMRAM 在非 SMM 状态下的可见性。
- **D_LCK（Lock）**：一旦置位，SMRAM 的配置（包括 D_OPEN 等）被锁死，直到下次复位才能改变。固件在启动后期会置位 D_LCK，之后任何非 SMM 代码都无法再打开或篡改 SMRAM [12]。

**TSEG（Top of Memory Segment）** 是现代芯片组（如 Intel Q35）提供的一种更大、更灵活的 SMRAM 区域：

- TSEG 位于低端内存的顶部，其位置相对于 TOLUD（Top of Low Usable DRAM，即 4GB 以下内存的分界线）确定 [6]。
- 相比传统的固定小 SMRAM（如 A/B segment 只有几十 KB），TSEG 可以容纳更大的 SMI handler 与数据。
- SMRAM 的 LCK 位在锁定 SMRAM 的同时也会锁定 TSEG 配置；但需要注意，LCK 并不锁定 TOLUD [6]。

### 1.8 SMM 的安全问题

由于 SMM 权限极高且对 OS 透明，它天然是攻击者觊觎的目标：

- **SMM Rootkit（SMBR）**：学术界很早就指出，基于 SMM 的 rootkit 是一种"OS 无关"的恶意软件，因为它运行在比 OS 更底层、且 OS 无法检测的环境中 [14]。
- 保护 SMM 需要同时保护**运行中的 SMRAM 地址空间**和**其代码来源（Flash 芯片）**，包括保护 SMBASE 位置、SMRAM 权限，以及对 Flash 进行写保护 [12]。
- Intel 后来引入 **STM（SMI Transfer Monitor）** 等机制，尝试在 SMM 之上再加一层监控/降权，以约束 SMI handler 的行为 [16]。

> 关键结论：SMM 的安全性建立在"SMRAM 锁定 + Flash 保护 + handler 代码可信"之上。这一安全模型在虚拟化场景下同样需要被完整复刻，否则虚拟机内的 SMM（以及依赖它的安全启动）就形同虚设。

---

## 二、虚拟化场景如何为虚拟机提供 SMM

### 2.1 为什么虚拟机需要 SMM

在纯虚拟化场景中，虚拟机长期以来可以不需要 SMM。但随着 **UEFI 安全启动（Secure Boot）** 在虚拟机中的落地，SMM 变得不可或缺：

- 安全启动的核心是一组**认证变量**（PK、KEK、db、dbx 等），它们必须**防止运行中的操作系统随意篡改**。
- 在物理机 UEFI 固件中，这些变量的写入被限制在 SMM 内的特权驱动中完成，非特权（非 SMM）代码只能通过 `EFI_SMM_COMMUNICATION_PROTOCOL` 发起请求，由 SMM 侧的特权驱动校验后代为执行 [4]。
- 因此，若要在虚拟机中实现"真正安全"的 Secure Boot（OS 无法伪造/绕过对认证变量的保护），就必须为虚拟机提供一个具备隔离性的 SMM 环境 [2]。

换言之，虚拟机 SMM 的主要驱动力是 **Secure Boot 的变量保护**，其安全模型要求：即使 guest 内核被攻破，也无法访问 guest 的 SMRAM、无法伪造对认证变量的写入。

### 2.2 整体架构：KVM + QEMU + OVMF 的三方协作

在 QEMU/KVM 虚拟化栈中，为虚拟机提供 SMM 需要三个层次协同完成 [2]：

| 组件 | 角色 | 主要职责 |
| --- | --- | --- |
| **KVM**（内核 Hypervisor） | CPU 虚拟化 | 执行 SMM 的"世界切换"（SMI 进入、RSM 退出）；向非 SMM 状态的 vCPU 隐藏 SMRAM |
| **QEMU**（用户态 VMM） | 平台/芯片组模拟 | 模拟 Q35 芯片组所需的 SMRAM/TSEG 相关寄存器；向非 SMM 处理器保护 Flash |
| **OVMF/EDK2**（虚拟固件） | Guest 固件 | 提供完整的 SMM 驱动栈，在 SMM 中实现 Secure Boot 变量保护等特权服务 |

Paolo Bonzini 在 KVM Forum 2015 上把三方职责总结为 [2]：

- **KVM 必须**：执行 SMM 世界切换（SMI、RSM）；对不处于 SMM 的处理器隐藏 SMRAM。
- **QEMU 必须**：实现所需的芯片组寄存器；对不处于 SMM 的处理器保护 Flash；支持 KVM 的 SMM 扩展（TCG 软件模拟同理）。
- **目标平台是 Q35**：因为老的 440FX（i440fx）芯片组的 SMRAM 太小，不足以承载完整的 SMM 驱动栈 [2]。

### 2.3 KVM 侧：世界切换与 SMRAM 隔离

KVM 负责 CPU 层面的 SMM 语义模拟，核心工作有两块 [2]：

1. **世界切换（world switch）**：
   - 当虚拟机收到 SMI 时，KVM 负责将 vCPU 状态保存到 guest 的 SMRAM 状态保存区，把 vCPU 切入 SMM 执行环境，并从 `SMBASE + 0x8000` 开始执行。
   - 当 guest 执行 `RSM` 时，KVM 负责从状态保存区恢复上下文并切回原模式。
   - 为此 KVM 在 `arch/x86/kvm/smm.c` 中实现了 32/64 位的状态保存布局，并对各字段偏移做了严格校验以保证与真实硬件一致 [8]。

2. **SMRAM 的按 vCPU 可见性隔离**：
   - KVM 必须保证只有处于 SMM 的 vCPU 才能访问 SMRAM；非 SMM 状态的 vCPU 对该物理地址范围的访问要被重定向/拒绝 [2]。
   - 在对称多处理（SMP）guest 中，还必须避免 SMRAM 可见性切换时的竞态（race），保证每个 vCPU 独立、正确地进出 SMM [2]。

KVM 通过 `KVM_CAP_X86_SMM` 能力向用户态（QEMU）暴露 SMM 支持；QEMU 检测到该能力后才会启用相应的 SMM 模拟路径。

### 2.4 QEMU 侧：芯片组模拟与 TSEG

QEMU 负责把"物理平台"这一侧补齐，重点是 Q35 芯片组的 SMRAM 相关行为 [2]：

- **实现 Q35 专属的 SMRAM 特性**：包括 SMRAM 控制寄存器（对应真实芯片组中控制 SMRAM 打开/关闭/锁定的位）。
- **实现 TSEG**：把一段低端内存顶部区域划为 TSEG（SMRAM），并根据锁定位控制其可见性 [2][5]。
- **实现 SMRAM 锁定（locking）**：模拟 D_LCK 等锁定语义，锁定后非 SMM 无法再更改配置 [2]。
- **保护 Flash**：对不处于 SMM 的处理器保护固件 Flash（pflash），防止 guest OS 直接改写固件/变量存储 [2]。

早期 QEMU 只有对位于 `0x0` 附近的基础 SMRAM 支持，缺失的正是 Q35 专属 SMRAM 特性、TSEG、SMRAM 锁定、按 CPU 的 SMRAM 可见性、以及 Flash 保护等能力，这些随后被逐步补齐 [2]。

> ⚠️ 一个历史上的实现差异：TSEG 的锁定位（LCK）会锁定 TSEG 配置，但**不锁定 TOLUD**。攻击者虽然不能关闭 TSEG，却有可能通过移动 TOLUD 把 TSEG"挪开"。QEMU 早期并未完整实现 TOLUD 相关寄存器，这类边界需要在实现虚拟 SMM 时特别关注 [6]。

### 2.5 OVMF/EDK2 侧：SMM 驱动栈

OVMF（Open Virtual Machine Firmware）是基于 EDK2 的、面向虚拟机的 UEFI 固件，它在 guest 内提供完整的 SMM 软件栈 [4]：

- **SMM 驱动是特权驱动**：它们运行在 SMM 中、能访问 SMRAM，并通过 SMI 与其他非 SMM 驱动隔离、切换 [4]。
- **安全通信**：非特权（非 SMM）驱动与特权（SMM）驱动之间通过 `EFI_SMM_COMMUNICATION_PROTOCOL` 通信，该协议由 SMM Core 实现 [4]。这正是 Secure Boot 变量写入请求从普通环境安全地转交到 SMM 内特权代码的通道。
- **内存布局调整（TSEG carve-out）**：当平台配置了 SMM 支持时，OVMF 的 Platform PEI 阶段会修改内存映射，把 SMRAM 区域（TSEG）从通用可用 RAM 池中"抠出来"，并通过创建 `EfiReservedMemoryType` 类型的 HOB 将其标记为对操作系统不可访问 [5]。

**构建开关 `SMM_REQUIRE`**：OVMF 需要以打开 SMM 支持的方式构建（构建时定义 `-D SMM_REQUIRE`）。只有这样构建出的 OVMF 才会包含并要求 SMM 驱动栈，从而与 KVM/QEMU 的 SMM 能力配合，实现受保护的 Secure Boot。tianocore 的官方 wiki 专门给出了在 QEMU/KVM/libvirt 上测试该 SMM 驱动栈的完整环境搭建方法 [3][7]。

### 2.6 一次完整的虚拟机 SMI 流程

以 guest 内一次 Secure Boot 认证变量写入（软件 SMI）为例，串联三方协作：

1. **触发**：guest 中的非 SMM UEFI 驱动想写认证变量，通过 `EFI_SMM_COMMUNICATION_PROTOCOL` 准备好请求，然后写 `0x0B2` 端口触发软件 SMI [1][4]。
2. **陷入 KVM**：写该 I/O 端口被 QEMU/KVM 识别为 SMI 源，KVM 对目标 vCPU 发起 SMM 世界切换 [2]。
3. **切入 SMM**：KVM 保存 vCPU 上下文到 guest SMRAM 状态保存区，切换执行环境，从 `SMBASE + 0x8000` 开始执行 OVMF 的 SMI handler [1][8]。
4. **SMRAM 隔离生效**：此时只有该 vCPU 处于 SMM，能看到 SMRAM；其他 vCPU 与 guest OS 都无法访问 SMRAM，QEMU 侧也保护着 Flash [2]。
5. **特权处理**：SMM 内的特权变量驱动校验请求合法性后，真正写入受保护的认证变量存储 [4]。
6. **退出 SMM**：handler 执行 `RSM`，KVM 从状态保存区恢复上下文，vCPU 切回原运行模式，guest 继续执行 [2]。

整个过程对 guest OS 透明，且 guest OS 无法绕过 SMM 直接篡改变量——这正是虚拟机 Secure Boot 安全性的基础。

### 2.7 配置示例

在实际使用中，通常通过 libvirt/QEMU 启用带 SMM 的 Q35 虚拟机，要点是：**使用 Q35 机型 + 打开 SMM + 使用 `SMM_REQUIRE` 构建的 OVMF + 开启 Secure Boot**。

QEMU 命令行关键参数（示意）：

```bash
qemu-system-x86_64 \
  -machine q35,smm=on \                       # Q35 芯片组，开启 SMM
  -global driver=cfi.pflash01,property=secure,value=on \  # 保护固件 Flash
  -drive if=pflash,format=raw,unit=0,readonly=on,file=OVMF_CODE.secboot.fd \  # SMM_REQUIRE 构建的固件
  -drive if=pflash,format=raw,unit=1,file=OVMF_VARS.fd \  # 变量存储
  ...
```

libvirt domain XML 关键片段（示意）：

```xml
<domain type='kvm'>
  <os firmware='efi'>
    <type arch='x86_64' machine='q35'>hvm</type>
    <loader secure='yes'/>          <!-- 启用受 SMM 保护的固件 -->
  </os>
  <features>
    <smm state='on'/>               <!-- 开启 SMM -->
  </features>
</domain>
```

> 具体路径与文件名依发行版而定，官方推荐参照 tianocore 的 "Testing SMM with QEMU, KVM and libvirt" 指南进行端到端验证 [3][7]。

### 2.8 限制与注意事项

- **必须用 Q35**：i440fx 的 SMRAM 太小，无法承载完整 SMM 驱动栈，虚拟 SMM 只在 Q35 上支持 [2]。
- **SMM 与安全的耦合**：只有 KVM（世界切换 + SMRAM 隐藏）、QEMU（芯片组寄存器 + Flash 保护）、OVMF（SMM 驱动栈）三者都正确实现，虚拟机 Secure Boot 才真正安全；任一环节缺失都会削弱保护 [2]。
- **SMM 本身的安全历史包袱**：SMM 在设计之初并未以安全为目标，历史上有不良记录，虚拟化实现时必须谨慎，避免把物理机上的 SMM 漏洞模式带进虚拟机 [1]。
- **TSEG/TOLUD 边界**：需完整实现锁定语义，注意 LCK 不锁 TOLUD 带来的"挪走 TSEG"风险 [6]。
- **迁移与嵌套**：启用 SMM 会增加 vCPU 状态（SMRAM、SMBASE 等）的迁移复杂度；在嵌套虚拟化下，SMM 状态保存区还需处理 SVM/VMX guest 相关字段 [8]。

---

## 三、总结

- **SMM 是什么**：x86 的最高特权、OS 透明的系统管理模式，只能由 SMI 进入、由 `RSM` 退出，代码（SMI handler）由固件装载并运行在受保护的 SMRAM 中，SMBASE 决定其入口 [1][2]。
- **SMM 靠什么保证隔离**：SMRAM 锁定（D_LCK）、Flash 写保护、handler 可信；TSEG 提供了更大的现代 SMRAM 区域 [6][12]。
- **虚拟机为什么要 SMM**：主要为 UEFI Secure Boot 的认证变量提供 OS 无法绕过的保护 [4]。
- **虚拟化如何提供 SMM**：KVM 做 CPU 世界切换与 SMRAM 隔离，QEMU 模拟 Q35 芯片组的 SMRAM/TSEG/锁定并保护 Flash，OVMF（以 `SMM_REQUIRE` 构建）提供 SMM 驱动栈并通过 `EFI_SMM_COMMUNICATION_PROTOCOL` 完成特权/非特权交互，三方协作在 Q35 机型上复刻物理机的 SMM 安全模型 [2][4][5]。

---

## 参考资料

1. System Management Mode — Wikipedia：<https://en.wikipedia.org/wiki/System_Management_Mode>
2. Paolo Bonzini, *Securing secure boot with System Management Mode*, KVM Forum 2015：<http://events17.linuxfoundation.org/sites/events/files/slides/kvmforum15-smm.pdf>
3. Testing SMM with QEMU, KVM and libvirt — tianocore wiki：<https://github.com/tianocore/tianocore.github.io/wiki/Testing-SMM-with-QEMU,-KVM-and-libvirt>
4. Open Virtual Machine Firmware (OVMF) Status Report (Laszlo Ersek)：<https://www.linux-kvm.org/downloads/lersek/ovmf-whitepaper-c770f8c.txt>
5. What is OVMF (UEFI Firmware for Virtual Machines)：<https://termbasehub.com/ovmf/>
6. Gerd Hoffmann (kraxel), *Virtual secure boot — Secure boot support in qemu, kvm and ovmf*：<https://www.kraxel.org/slides/virtual-secure-boot.pdf>
7. Testing SMM with QEMU, KVM, and libvirt（tianocore 文档站）：<https://www.tianocore.org/tianocore-wiki.github.io/development/tutorials-howto/testing_smm_with_qemu,_kvm_and_libvirt.html>
8. Linux 内核 KVM SMM 实现 `arch/x86/kvm/smm.c`：<https://cgit.freedesktop.org/drm/drm-tip/tree/arch/x86/kvm/smm.c>
9. Firmware security 3: Digging into System Management Mode (SMM)：<https://nixhacker.com/digging-into-smm/>
10. Intel 386 User Manual — SMM Active Output / SMRAM：<https://www.manualslib.com/manual/77671/Intel-386.html?page=161>
11. SMMMmmmm — when root is not enough：<https://barbieauglend.re/2019-08-15-system-managing-god/>
12. Advanced x86: BIOS and System Management Mode Internals（OpenSecurityTraining）：<https://opensecuritytraining.info/IntroBIOS_files/Day1_07_Advanced%20x86%20-%20BIOS%20and%20SMM%20Internals%20-%20SMM.pdf>
13. A Tour Beyond BIOS: Launching STM to Monitor SMM in EFI Developer Kit II (Intel)：<https://www.intel.co.za/content/dam/develop/external/us/en/documents/a-tour-beyond-bios-launching-stm-to-monitor-smm-in-efi-developer-kit-ii-819978.pdf>
14. SMM Rootkits: A New Breed of OS Independent Malware：<https://dl.acm.org/doi/pdf/10.1145/1460877.1460892>
