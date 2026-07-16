Title: x86 架构 VMExit 类型全览（Intel VMX & AMD SVM）
Date: 2026-7-16 14:00
Modified: 2026-7-16 14:00
Tags: virtualization, kvm, vmx, svm, vmexit
Slug: x86-vmexit
Status: published
Authors: Yori Fang
Summary: 系统梳理 x86 虚拟化架构下 Intel VMX 与 AMD SVM 两个平台的所有 VMExit 类型，涵盖退出码、触发原因及 VMM 典型处理方式。

# x86 架构 VMExit 类型全览（Intel VMX \& AMD SVM）

本文档系统梳理了 x86 虚拟化架构下 **Intel VMX** 和 **AMD SVM** 两个平台的所有 VMExit（虚拟机退出）类型，涵盖每种退出的退出码、触发原因、以及 VMM（虚拟机监控器）的典型处理方式。

数据来源：Intel SDM Vol\.3D Appendix C、AMD APM Vol\.2 Chapter 15、Linux 内核 `arch/x86/include/uapi/asm/vmx.h` 及 `svm.h`。

# 一、Intel VMX VM Exit 退出原因

**Intel VMX VM Exit 概述**

VM Exit 是从 VMX 非根操作模式（客户机）切换回 VMX 根操作模式（VMM/宿主机）的过程。当 VM Exit 发生时，CPU 自动将客户机状态保存到 VMCS 的客户机状态区，从 VMCS 的宿主机状态区加载宿主机状态，并在 VMCS 中记录**退出原因**。VMM 通过读取退出原因来确定触发原因并执行相应处理。退出原因码定义于 Intel SDM Vol\. 3D, Appendix C。16 位基本退出原因存储在 VMCS 字段 `VM_EXIT_REASON`（偏移 **0x4402**）中。Bits 15:0 包含**基本退出原因**；Bit 31 指示 VM\-entry 失败是否由 VM\-entry **不一致性**引起。

---

## 1\. 异常与中断（退出码 0\-8）

这些退出在客户机执行期间由异常、中断和系统管理信号触发。它们是与事件投递相关的最基础的 VM 退出类别。

|退出码|名称|触发原因|VMM 处理方式|
|---|---|---|---|
|0|EXIT\_REASON\_EXCEPTION\_NMI|客户机执行期间发生异常（故障、陷阱或中止）或 NMI，且对应的 VM\-exit 控制位已设置（例如，异常位图中对应异常向量的位已设置，或 NMI exiting 已启用）。|VMM 检查 VMCS 的 `VM_EXIT_INTR_INFO` 和 `VM_EXIT_INTR_ERROR_CODE` 字段以识别异常向量和类型。它可以通过 VM\-entry 事件注入机制将事件重新注入客户机，内部处理（如页错误反射），或将其传递给宿主机 OS。|
|1|EXIT\_REASON\_EXTERNAL\_INTERRUPT|客户机执行期间收到外部中断，且 "external\-interrupt exiting" VM\-execution control 已设置。如果中断未被屏蔽，CPU 触发 VM exit。|VMM 读取 `VM_EXIT_INTR_INFO`**以获取中断向量**。它将中断分发给宿主机中断处理程序。处理完成后，VMM 通过 VMRESUME 恢复客户机执行。如果启用了虚拟中断投递，VMM 也可以将其重新注入客户机。|
|2|EXIT\_REASON\_TRIPLE\_FAULT|客户机执行期间发生三重错误：在投递 double fault 时引发异常，或在投递 double fault 期间发生 double fault。|VMM 将此视为客户机的致命错误。它通常记录该事件，如果已配置则捕获崩溃转储，并终止客户机 VM 或重置客户机的虚拟处理器。某些 VMM 可能将客户机重置为初始状态。|
|3|EXIT\_REASON\_INIT\_SIGNAL|在 VMX non\-root 操作期间，逻辑处理器收到 INIT 信号，且 "INIT exiting" VM\-execution control 已设置。|VMM 将 INIT 信号排队，可能稍后投递给客户机（例如，当客户机处于可接受状态时），或者将客户机虚拟处理器重置为 INIT 状态。VMM 确保 INIT 信号不会丢失。|
|4|EXIT\_REASON\_SIPI\_SIGNAL|客户机执行期间收到 SIPI，且 "SIPI exiting" VM\-execution control 已设置。|VMM 读取 `VM_EXIT_INTR_INFO` 以提取 SIPI 向量。当客户机虚拟处理器处于 wait\-for\-SIPI 状态时，VMM 将 SIPI 排队等待投递给客户机。VMM 与客户机多处理器管理协调，启动额外的 vCPU。|
|5|EXIT\_REASON\_IO\_SMI|客户机执行期间收到 I/O SMI（系统管理中断）。这是通过 I/O APIC 或专用 SMI 引脚投递的 SMI。|VMM 通过进入自身的 SMM 处理程序或延迟处理来处理 SMI。客户机不会直接感知到 SMI。如果 VMM 自行处理 SMI，必须确保 SMM 状态正确保存/恢复。|
|6|EXIT\_REASON\_OTHER\_SMI|客户机执行期间收到非 I/O SMI 的 SMI。这可能是软件生成的 SMI 或其他 SMI 源。|与 I/O SMI 处理类似。VMM 在自身的 SMM 上下文中处理 SMI 或延迟处理。具体处理方式取决于 VMM 是否支持 SMM 虚拟化。|
|7|EXIT\_REASON\_INTERRUPT\_WINDOW|"interrupt\-window exiting" VM\-execution control 已设置，且客户机 RFLAGS\.IF=1（中断已启用），并且没有其他条件阻止中断投递。这向 VMM 表明客户机现在可以接受可注入的中断。|VMM 检查是否有待注入客户机的中断。如果有，通过 VM\-entry 事件注入机制注入该中断，并清除 interrupt\-window exiting 控制位。如果没有待处理的中断，则禁用 interrupt\-window exiting 并恢复客户机执行。|
|8|EXIT\_REASON\_NMI\_WINDOW|"NMI\-window exiting" VM\-execution control 已设置，且客户机处于 NMI 未被阻塞的状态（即不在 SMM 中或 NMI 投递之后）。这向 VMM 表明客户机现在可以接受 NMI。|VMM 检查是否有待注入的 NMI。如果有，通过 VM\-entry 事件注入机制注入该 NMI，并清除 NMI\-window exiting 控制位。如果没有待处理的 NMI，则禁用 NMI\-window exiting 并恢复客户机执行。|

---

## 2\. 系统与任务管理（退出码 9\-13）

这些退出由管理 CPU 状态、标识或任务切换的指令触发。它们通常需要 VMM 介入以实现正确的虚拟化。

|退出码|名称|触发原因|VMM 处理方式|
|---|---|---|---|
|9|EXIT\_REASON\_TASK\_SWITCH|客户机通过 CALL/JMP 到 TSS 门、NT 标志置位的 IRET 或 IDT 中的任务门尝试任务切换，且 "task switch exiting" VM\-execution control 已设置。|VMM 从 VMCS 字段（`VM_EXIT_INSTRUCTION_INFO` 等）读取任务切换信息，确定源 TSS 和目标 TSS。它在软件中模拟任务切换，更新客户机的 CR3、段寄存器和 TSS 结构，然后恢复客户机执行。如果有硬件辅助任务切换功能则可使用。|
|10|EXIT\_REASON\_CPUID|客户机执行 CPUID 指令，且 "CPUID exiting" VM\-execution control 已设置（无条件退出）。|VMM 读取客户机的 EAX/ECX 输入，模拟 CPUID 返回虚拟化的 CPU 特性信息（隐藏不支持的特性、报告 hypervisor 存在位等），将结果写入客户机 EAX/EBX/ECX/EDX，推进指令指针，并恢复客户机执行。|
|11|EXIT\_REASON\_GETSEC|客户机执行 GETSEC 指令（Intel TXT \- 可信执行技术的一部分），且 "GETSEC exiting" VM\-execution control 已设置。|VMM 通常根据安全策略阻止或模拟 GETSEC。由于 GETSEC 用于 TXT 启动环境，VMM 可能返回错误或受控响应。大多数 VMM 不支持客户机 TXT 启动，会注入 \#UD（未定义操作码）异常。|
|12|EXIT\_REASON\_HLT|客户机执行 HLT 指令，且 "HLT exiting" VM\-execution control 已设置。|VMM 将 vCPU 标记为停机/空闲，调度另一个 vCPU 或将物理 CPU 置于低功耗状态。当中断或其他唤醒事件到达时，VMM 恢复停机的 vCPU。VMM 必须确保客户机在停机期间不消耗 CPU 周期。|
|13|EXIT\_REASON\_INVD|客户机执行 INVD 指令（不写回地使缓存失效），且 "INVD exiting" VM\-execution control 已设置。|VMM 通常将 INVD 模拟为空操作，如果客户机不允许执行 INVD 则注入 \#GP。由于 INVD 可能影响整个系统的缓存状态，VMM 通常不允许客户机直接执行。某些 VMM 可能将其转换为 WBINVD 语义。|

---

## 3\. TLB 与缓存管理（退出码 14\-16、51、54、56\-58、61）

这些退出涉及 TLB 刷新、性能计数器访问和时间戳计数器读取，如果不进行虚拟化，都可能影响系统全局状态。

|Exit Code|Name|Trigger|VMM Handling|
|---|---|---|---|
|14|EXIT\_REASON\_INVLPG|Guest 执行 INVLPG 指令，使 TLB 中特定线性地址的映射失效。当 "INVLPG exiting" VM\-execution control 位为 1 时触发。|VMM 刷新影子页表（Shadow Page Table）中对应虚拟页的 TLB 映射。在使用 EPT 时，该操作可能被透传或仅影响 Guest TLB。VMM 推进 RIP 并恢复 Guest 执行。|
|15|EXIT\_REASON\_RDPMC|Guest 执行 RDPMC 指令，读取性能监视计数器（Performance Monitoring Counter）。当 "RDPMC exiting" VM\-execution control 位为 1 时触发。|VMM 检查 Guest 是否有权限读取 PMC。如果允许，VMM 读取对应 PMC 值并写入 Guest 的 EAX/EDX；如果不允许，注入 \#GP。VMM 推进 RIP 并恢复执行。|
|16|EXIT\_REASON\_RDTSC|Guest 执行 RDTSC 指令，读取时间戳计数器（TSC）。当 "RDTSC exiting" VM\-execution control 位为 1 时触发。|VMM 拦截 TSC 读取以实现 TSC 虚拟化（如 TSC offset、TSC scaling），向 Guest 提供虚拟化的时间戳值。VMM 将处理后的 TSC 值写入 Guest 的 EAX/EDX，推进 RIP 并恢复执行。|
|51|EXIT\_REASON\_RDTSCP|Guest 执行 RDTSCP 指令，读取 TSC 和处理器 IA32\_TSC\_AUX MSR 值。当 "RDTSC exiting" VM\-execution control 位为 1 且 "enable RDTSCP" 为 1 时触发。|VMM 与 RDTSC 类似，拦截并虚拟化 TSC 读取。额外处理 IA32\_TSC\_AUX MSR 的虚拟化。将处理后的值写入 Guest 的 EAX/EDX/ECX，推进 RIP 并恢复执行。|
|54|EXIT\_REASON\_WBINVD|Guest 执行 WBINVD 指令，写回并使所有缓存行失效。当 "WBINVD exiting" VM\-execution control 位为 1 时触发。|VMM 处理该退出以确保缓存一致性。在使用 EPT 时，VMM 可能仅执行 cache flush 操作而不影响其他 Guest。VMM 推进 RIP 并恢复 Guest 执行。|
|56|EXIT\_REASON\_APIC\_WRITE|Guest 向虚拟 APIC 页面写入数据（通过虚拟化 APIC 寄存器写入），且 "APIC\-register virtualization" 或 "virtual\-interrupt delivery" VM\-execution control 位为 1 时触发。VMM 拦截 Guest 对 APIC 寄存器的写入操作。|VMM 解析 Guest 写入的 APIC 寄存器号和数据，模拟 APIC 行为（如设置 ICR 发送 IPI、修改 TPR 等）。如果是 ICR 写入，VMM 执行虚拟 IPI 投递。VMM 推进 RIP 并恢复 Guest 执行。|
|57|EXIT\_REASON\_RDRAND|Guest 执行 RDRAND 指令，且 "RDRAND exiting" VM\-execution control 位为 1 时触发。RDRAND 用于从硬件随机数生成器获取随机数。|VMM 可以选择模拟 RDRAND 指令（提供软件生成的随机数），或直接将指令透传给硬件执行（如果信任 Guest）。如果 Guest 不支持 RDRAND，VMM 注入 \#UD。VMM 推进 RIP 并恢复 Guest 执行。|
|58|EXIT\_REASON\_INVPCID|Guest 执行 INVPCID 指令，按 PCID（进程上下文标识符）使 TLB 失效。当 "INVEPT/INVPCID exiting" VM\-execution control 位为 1 时触发。|VMM 模拟 INVPCID 操作，根据 PCID 类型刷新相应的 TLB 条目（Guest TLB 或 VMM 维护的影子 TLB）。VMM 推进 RIP 并恢复 Guest 执行。|
|61|EXIT\_REASON\_RDSEED|Guest 执行 RDSEED 指令，且 "RDSEED exiting" VM\-execution control 位为 1 时触发。RDSEED 用于从硬件熵源获取种子随机数。|VMM 可以模拟 RDSEED（提供软件熵源），或将指令透传给硬件。如果 Guest 不支持 RDSEED，VMM 注入 \#UD。VMM 推进 RIP 并恢复 Guest 执行。|

---

## 4\. VMX 指令（退出码 18\-27）

这些退出发生在客户机处于 VMX non\-root 操作模式下尝试执行 VMX 指令（VMLAUNCH、VMRESUME 等）时。由于客户机无法直接管理 VMCS 结构，VMM 必须拦截并处理这些指令。

|退出码|名称|触发原因|VMM 处理方式|
|---|---|---|---|
|18|EXIT\_REASON\_VMCALL|客户机执行 VMCALL 指令（hypercall）。这是 VMX 中客户机到宿主机通信的主要机制。|VMM 从客户机寄存器读取 hypercall 参数（通常通过 EAX/ECX 传递调用号和参数）。它处理 hypercall（如 MMIO 处理、半虚拟化 I/O、内存 ballooning），并将结果返回到客户机寄存器。VMM 推进 RIP 并恢复执行。|
|19|EXIT\_REASON\_VMCLEAR|客户机执行 VMCLEAR 指令，尝试清除 VMCS 区域。由于客户机处于 non\-root 操作模式而触发退出。|如果客户机不支持 VMX 指令，VMM 通常注入 \#UD（未定义操作码）；如果支持嵌套虚拟化，则模拟 VMCLEAR（为 L1 hypervisor 维护影子 VMCS 结构）。|
|20|EXIT\_REASON\_VMLAUNCH|客户机执行 VMLAUNCH 指令，尝试启动嵌套客户机。由于客户机处于 non\-root 操作模式而触发退出。|如果支持嵌套虚拟化，VMM（L0）拦截并协助 L1 hypervisor，为 L2 创建影子/合并的 VMCS 并进入 L2。如果不支持，VMM 注入 \#UD 异常。|
|21|EXIT\_REASON\_VMPTRLD|客户机执行 VMPTRLD 指令，尝试加载 VMCS 指针。由于客户机处于 non\-root 操作模式而触发退出。|如果支持嵌套虚拟化，VMM 跟踪 L1 VMCS 指针并相应管理影子 VMCS 结构。如果不支持，注入 \#UD。|
|22|EXIT\_REASON\_VMPTRST|客户机执行 VMPTRST 指令，尝试存储当前 VMCS 指针。由于客户机处于 non\-root 操作模式而触发退出。|如果支持嵌套虚拟化，VMM 将跟踪的 L1 VMCS 指针存储到客户机指定的内存位置。如果不支持，注入 \#UD。|
|23|EXIT\_REASON\_VMREAD|客户机执行 VMREAD 指令，尝试读取 VMCS 字段。由于客户机处于 non\-root 操作模式而触发退出。|如果支持嵌套虚拟化，VMM 从影子 VMCS 读取并将值返回给客户机。VMM 必须维护一致的影子 VMCS 以反映 L1 的期望。如果不支持，注入 \#UD。|
|24|EXIT\_REASON\_VMRESUME|客户机执行 VMRESUME 指令，尝试恢复嵌套客户机。由于客户机处于 non\-root 操作模式而触发退出。|如果支持嵌套虚拟化，VMM（L0）拦截并将 L1 VMCS 与 L0 VMCS 合并，然后进入/恢复 L2 执行。如果不支持，注入 \#UD。|
|25|EXIT\_REASON\_VMWRITE|客户机执行 VMWRITE 指令，尝试写入 VMCS 字段。由于客户机处于 non\-root 操作模式而触发退出。|如果支持嵌套虚拟化，VMM 写入影子 VMCS。对于 VM\-execution control 字段，VMM 可能需要协调 L1 的设置与 L0 的能力（L0 强制使用其子集）。如果不支持，注入 \#UD。|
|26|EXIT\_REASON\_VMXOFF|客户机执行 VMXOFF 指令，尝试退出 VMX 操作。由于客户机处于 non\-root 操作模式而触发退出。|如果支持嵌套虚拟化，VMM 处理 L1 hypervisor 退出 VMX 操作的请求，清理影子 VMCS 结构并标记客户机不再处于 VMX 操作模式。如果不支持，注入 \#UD。|
|27|EXIT\_REASON\_VMXON|客户机执行 VMXON 指令，尝试进入 VMX 操作。由于客户机处于 non\-root 操作模式而触发退出。|如果支持嵌套虚拟化，VMM 为 L1 客户机初始化嵌套 VMX 状态，分配影子 VMCS 结构，并启用 VMX 指令模拟。如果不支持，注入 \#UD。|

---

## 5\. 控制寄存器访问（退出码 28）

MOV to/from CR 指令被拦截，以防止客户机修改影响系统全局行为的关键控制寄存器（如分页、保护机制）。

|退出码|名称|触发原因|VMM 处理方式|
|---|---|---|---|
|28|EXIT\_REASON\_CONTROL\_REGISTER\_ACCESS|客户机执行 MOV 指令访问控制寄存器（CR0、CR3、CR4、CR8），且对应的 CR access exiting 控制位已设置（通过 CR\-read 和 CR\-write VM\-execution controls 位图配置）。|VMM 读取 `VM_EXIT_QUALIFICATION` 以确定：访问类型（读/写）、CR 编号、涉及的通用寄存器，以及是否由 LMSW 或 CLTS 触发。对于写操作，VMM 验证新的 CR 值（例如，确保分页启用时 CR0\.PG 保持置位），更新客户机的虚拟 CR 状态，并可能调整实际 CR 以维持 VMM 控制（如保持 CR0\.PE 置位）。对于读操作，VMM 返回虚拟化的 CR 值。VMM 推进 RIP 并恢复执行。|

---

## 6\. 调试寄存器访问（退出码 29）

MOV to/from DR 指令被拦截，以防止客户机设置硬件断点或修改调试寄存器，从而可能干扰 VMM 自身的调试。

|退出码|名称|触发原因|VMM 处理方式|
|---|---|---|---|
|29|EXIT\_REASON\_DEBUG\_REGISTER\_ACCESS|客户机执行 MOV 指令访问调试寄存器（DR0\-DR7），且 "MOV\-DR exiting" VM\-execution control 已设置。|VMM 读取 `VM_EXIT_QUALIFICATION` 以确定：访问类型（读/写）、DR 编号和涉及的通用寄存器。对于写操作，VMM 将值存储到客户机的虚拟 DR 状态中，并可能有选择地应用到物理 DR（例如，用于客户机硬件断点），同时保留 VMM 自身的调试设置。对于读操作，VMM 返回虚拟化的 DR 值。VMM 推进 RIP 并恢复执行。|

---

## 7\. I/O 指令（退出码 30）

I/O 端口指令（IN、OUT、INS、OUTS）被拦截，用于虚拟化设备 I/O 并对物理端口的访问进行权限控制。

|退出码|名称|触发原因|VMM 处理方式|
|---|---|---|---|
|30|EXIT\_REASON\_IO\_INSTRUCTION|客户机执行 I/O 指令（IN、OUT、INS、OUTS），I/O 位图指示该端口应触发 VM exit，或启用了无条件 I/O exiting。"unconditional I/O exiting" 控制位或按端口的 I/O 位图 A/B 位决定是否退出。|VMM 读取 `VM_EXIT_QUALIFICATION` 以确定：端口号、访问大小（1/2/4 字节）、方向（IN/OUT）、字符串操作（INS/OUTS）和 REP 前缀。它检查 VMM 的 I/O 端口访问策略。对于模拟设备，它读取或写入虚拟设备模型。对于透传设备，它可能代表客户机执行实际 I/O 操作。它更新客户机寄存器（如 IN/OUT 的 RAX、字符串操作的 RSI/RDI、REP 的 RCX），推进 RIP 并恢复执行。|

---

## 8\. MSR 访问（退出码 31\-32）

RDMSR 和 WRMSR 指令被拦截以实现模型特定寄存器的虚拟化，防止客户机读取或修改可能危害系统完整性或暴露宿主机状态的 MSR。

|退出码|名称|触发原因|VMM 处理方式|
|---|---|---|---|
|31|EXIT\_REASON\_RDMSR|客户机执行 RDMSR 指令，且该 MSR 在 MSR\-read 位图中（对应 MSR 索引的位已设置），表明应触发 VM exit。|VMM 从客户机 ECX 读取 MSR 索引。它从客户机保存的 MSR 上下文中查找虚拟 MSR 值或动态计算。对于透传 MSR，它可能执行实际的 RDMSR。它将结果写入客户机 EDX:EAX，推进 RIP 并恢复执行。VMM 确保敏感 MSR（如 SYSENTER\_CS/ESP/EIP、FS/GS base）被正确虚拟化。|
|32|EXIT\_REASON\_WRMSR|客户机执行 WRMSR 指令，且该 MSR 在 MSR\-write 位图中（对应 MSR 索引的位已设置），表明应触发 VM exit。|VMM 从客户机 ECX 读取 MSR 索引，从 EDX:EAX 读取值。它验证该值，存储到客户机的虚拟 MSR 上下文中，并有选择地应用到物理 MSR（例如，更新实际的 FS\_BASE）。对于影响 VM\-execution controls 的 MSR，VMM 将客户机的请求与自身设置进行协调。VMM 推进 RIP 并恢复执行。|

---

## 9\. VM 进入失败（退出码 33\-34、41）

这些退出在 VM entry 失败时发生。CPU 不会切换到 non\-root 操作模式，而是保持在 root 操作模式并记录失败原因。这对于 VMM 的健壮性至关重要。

|Exit Code|Name|Trigger|VMM Handling|
|---|---|---|---|
|33|EXIT\_REASON\_INVALID\_GUEST\_STATE|VM\-entry 时，VMCS 中的 Guest state area 字段不符合一致性检查要求（如 CR0/CR4 保留位不正确、段选择子不一致、activity state 非法组合等），导致 VM\-entry 失败。|VMM 读取 VM\-instruction error 字段获取具体错误原因。由于 Guest state 无效，VMM 无法进入 Guest，需要修复 VMCS 配置或终止 Guest。通常 VMM 记录错误日志并终止对应 vCPU 的执行，或向 Guest 注入错误信息。|
|34|EXIT\_REASON\_MSR\_LOADING|VM\-entry 时，从 VM\-entry MSR\-load area 加载 MSR 值失败（如尝试写入只读 MSR、MSR 地址无效等），导致 VM\-entry 失败。|VMM 读取 VM\-instruction error 字段和 exiting MSR 信息获取具体失败原因。VMM 需要修复 MSR\-load 列表中的问题条目，然后重试 VM\-entry。如果无法修复，终止对应 vCPU 的执行。|
|41|EXIT\_REASON\_MCE\_DURING\_VMENTRY|在 VM\-entry 过程中发生了 Machine Check Exception（MCE），即硬件级别的机器检查异常（如 ECC 错误、总线错误等）在 VM\-entry 期间被检测到。|VMM 将 MCE 视为严重的硬件异常处理。VMM 读取 MCE 相关的 MSRs（如 MCG\_STATUS、MCi\_STATUS）获取错误详情，根据严重程度决定是否终止 Guest 或尝试恢复。由于 MCE 涉及硬件故障，VMM 通常需要记录详细日志并通知上层管理系统。|

---

## 10\. 监控与等待（退出码 36\-40、67\-68）

这些退出涉及 MONITOR/MWAIT 和 PAUSE 指令，用于同步和电源管理。对这些指令的虚拟化对于 Guest 的效率和正确性非常重要。

|Exit Code|Name|Trigger|VMM Handling|
|---|---|---|---|
|36|EXIT\_REASON\_MWAIT\_INSTRUCTION|Guest 执行 MWAIT 指令，且 "MWAIT exiting" VM\-execution control 位为 1 时触发。MWAIT 使 CPU 进入优化等待状态，等待事件或中断唤醒。|VMM 通常将 MWAIT 视为空操作（NOP）处理——跳过指令并推进 RIP，因为虚拟化环境中无法真正让 vCPU 进入低功耗等待。VMM 也可以选择将 MWAIT 转换为等价的 PAUSE 或 HLT 行为。恢复 Guest 执行。|
|37|EXIT\_REASON\_MONITOR\_TRAP\_FLAG|当 "monitor trap flag" VM\-execution control 位为 1 时，Guest 在每次指令执行后触发此退出。这是一种单步调试机制，类似调试器的单步执行。|VMM 用于实现 Guest 单步调试功能。每次退出后 VMM 记录 Guest 状态（如寄存器值），然后推进 RIP 并恢复执行，等待下一次 MTF 退出。VMM 也可根据调试逻辑决定是否暂停 Guest。|
|39|EXIT\_REASON\_MONITOR\_INSTRUCTION|Guest 执行 MONITOR 指令，且 "MONITOR exiting" VM\-execution control 位为 1 时触发。MONITOR 设置一个监控区域，配合 MWAIT 实现"等待写入"的优化机制。|VMM 通常将 MONITOR 视为空操作（NOP）处理——跳过指令并推进 RIP，因为虚拟化环境中 MONITOR/MWAIT 对的监控功能通常由 VMM 而非硬件直接管理。VMM 也可以选择注入 \#UD（如果不支持该特性）。恢复 Guest 执行。|
|40|EXIT\_REASON\_PAUSE\_INSTRUCTION|Guest 执行 PAUSE 指令（spinlock 优化提示），且 "PAUSE exiting" VM\-execution control 位为 1，或 PAUSE 循环超过阈值时触发。PAUSE 指令用于自旋锁等待优化。|VMM 利用 PAUSE 退出实现"PAUSE\-loop exiting"（PLE）功能：当检测到 Guest 处于自旋锁死循环时，VMM 可以调度其他 vCPU 执行，避免浪费 CPU 资源。VMM 推进 RIP 并恢复 Guest 执行，或进行 vCPU 调度切换。|
|67|EXIT\_REASON\_UMWAIT|Guest 执行 UMWAIT 指令，且 "enable user wait and pause" 和 "RDTSC exiting" 两个 VM\-execution control 位同时为 1 时触发。UMWAIT 是用户态等待指令，允许用户态代码在指定时间范围内低功耗等待（基于 TSC）。|VMM 通常将 UMWAIT 视为空操作（NOP）处理——跳过指令并推进 RIP，因为该指令主要用于优化功耗，在虚拟化环境中意义有限。VMM 也可以选择注入 \#UD（如果不支持该特性）。恢复 Guest 执行。|
|68|EXIT\_REASON\_TPAUSE|Guest 执行 TPAUSE 指令，且 "enable user wait and pause" 和 "RDTSC exiting" 两个 VM\-execution control 位同时为 1 时触发。TPAUSE 是用户态定时暂停指令，允许用户态代码在指定 TSC 时间之前暂停执行。|VMM 通常将 TPAUSE 视为空操作（NOP）处理——跳过指令并推进 RIP。与 UMWAIT 类似，该指令在虚拟化环境中主要用于功耗优化，VMM 也可以选择注入 \#UD。恢复 Guest 执行。|

---

## 11\. APIC 虚拟化（退出码 43\-45、52）

这些退出与 APIC（高级可编程中断控制器）虚拟化相关。借助 APIC 虚拟化特性（virtual\-APIC page、posted interrupts），许多 APIC 访问可以由硬件直接处理，但部分仍需要 VMM 介入。

|退出码|名称|触发原因|VMM 处理方式|
|---|---|---|---|
|43|EXIT\_REASON\_TPR\_BELOW\_THRESHOLD|Guest 的 virtual\-APIC TPR（Task Priority Register）被写入低于 TPR 阈值的值，且 "TPR threshold" VM\-execution control 位已设置。这表示 Guest 现在可以接受更低优先级的中断。|VMM 检查是否有之前被 TPR 阈值阻塞的待处理中断。如果有，通过虚拟中断投递或 VM\-entry event injection 注入这些中断。如有需要，更新 TPR 阈值并恢复 Guest 执行。|
|44|EXIT\_REASON\_APIC\_ACCESS|Guest 以 APIC 虚拟化硬件无法完全处理的方式访问 APIC（内存映射的 APIC 页面或通过 MSR 访问）。这可以是对 APIC 页面的内存访问或对 APIC 寄存器的 MSR 访问。|VMM 读取 VM\_EXIT\_QUALIFICATION 以确定：访问类型（读/写）、访问方式（线性/Guest 物理地址）以及 APIC 页面内的偏移量。VMM 使用其虚拟 APIC 模型模拟 APIC 寄存器访问，如有需要则更新 virtual\-APIC page，并可能触发中断重新评估。推进 RIP 并恢复执行。|
|45|EXIT\_REASON\_EOI\_INDUCED|Guest 向 virtual\-APIC page 的 EOI（End of Interrupt）寄存器写入，且 "virtualize APIC accesses" 和 "EOI\-exiting" 控制位的配置使得硬件执行虚拟化 EOI 但仍需触发退出（例如，中断向量在 EOI\-exit bitmap 中）。|VMM 从 virtual\-APIC EOI 寄存器读取中断向量。VMM 执行硬件虚拟化未处理的必要 EOI 处理（例如通知直通设备、更新电平触发中断的路由）。VMM 确认虚拟化 EOI 并恢复 Guest 执行。|
|52|EXIT\_REASON\_VMX\_PREEMPTION\_TIMER|VMX\-preemption timer 在 Guest 执行期间递减至零，且 "VMX\-preemption timer" VM\-execution control 位已设置。该定时器为 VMM 提供了限制 Guest 执行时间的机制。|VMM 利用此机制进行 CPU 时间记账和公平调度。VMM 处理定时器到期的方式包括保存 Guest 的时间片、可能调度其他 vCPU，然后恢复 Guest 执行（可能为下一个时间片重新设置定时器）。VMM 也可将其用于看门狗功能。|

---

## 12\. 描述符表访问（退出码 46\-47）

这些退出由访问描述符表（GDT、IDT、LDT、TSS）的指令触发。VMM 拦截这些指令以维持对 Guest 段系统的控制。

|退出码|名称|触发原因|VMM 处理方式|
|---|---|---|---|
|46|EXIT\_REASON\_ACCESS\_GDTR\_OR\_IDTR|Guest 执行访问 GDTR 或 IDTR 的指令（LGDT、SGDT、LIDT、SIDT），且 "descriptor\-table exiting" VM\-execution control 位已设置。|VMM 读取 VM\_EXIT\_QUALIFICATION 和 VM\_EXIT\_INSTRUCTION\_INFO 以确定指令、操作数类型（寄存器/内存）以及访问的表。对于加载指令（LGDT/LIDT），验证新的表基址/限制并更新 Guest 的虚拟描述符表状态。对于存储指令（SGDT/SIDT），返回虚拟化的表基址/限制。推进 RIP 并恢复执行。|
|47|EXIT\_REASON\_ACCESS\_LDTR\_OR\_TR|Guest 执行访问 LDTR 或 TR 的指令（LLDT、SLDT、LTR、STR），且 "descriptor\-table exiting" VM\-execution control 位已设置。|VMM 读取指令信息以确定操作。对于加载指令（LLDT/LTR），验证新的选择子和描述符，更新 Guest 的虚拟 LDT/TSS 状态，如果 Guest 正在使用则可能更新实际的 LDTR/TR。对于存储指令（SLDT/STR），返回虚拟化的选择子。推进 RIP 并恢复执行。|

---

## 13\. EPT 与内存虚拟化（退出码 48\-50、55、59、62\-64、74\-75、77）

这些退出与扩展页表（EPT）和内存虚拟化特性相关。EPT 允许 VMM 在不使用影子页表的情况下将 Guest 物理地址映射到宿主物理地址，但 EPT 违规和配置错误仍需要 VMM 处理。

|Exit Code|Name|Trigger|VMM Handling|
|---|---|---|---|
|48|EXIT\_REASON\_EPT\_VIOLATION|Guest 访问的虚拟地址对应 EPT 映射不存在、权限不匹配（如读/写/执行权限违反），或 EPT 页表项的 reserved 位被设置。这是 EPT 内存虚拟化的核心退出原因。|VMM 解析 GFN（Guest Frame Number）和访问类型（读/写/执行），检查 Guest 物理地址映射。如果是缺页，VMM 分配宿主物理页并建立 EPT 映射；如果是权限问题，VMM 注入 \#PF 或处理内存保护策略。VMM 恢复 Guest 执行。|
|49|EXIT\_REASON\_EPT\_MISCONFIG|EPT 页表项配置错误，如内存类型保留位设置不正确、可缓存性位无效、或违反 EPT 页表项的保留位规则。与 EPT Violation 不同，这是配置错误而非权限缺失。|VMM 检查 EPT 页表项的配置，修复无效的位组合（如纠正内存类型字段）。如果无法修复，VMM 注入 \#GP 或终止 Guest。VMM 推进 RIP（如果是指令访问）或恢复原操作（如果是数据访问）。|
|50|EXIT\_REASON\_INVEPT|Guest 执行 INVEPT 指令，使 EPT 相关的 TLB 映射失效。当 "INVEPT/INVPCID exiting" VM\-execution control 位为 1 时触发。|VMM 模拟 INVEPT 操作，根据类型（single\-context 或 global）刷新对应的 EPT TLB 条目。VMM 推进 RIP 并恢复 Guest 执行。|
|55|EXIT\_REASON\_XSETBV|Guest 执行 XSETBV 指令，设置扩展控制寄存器 XCR0（控制哪些扩展状态由 XSAVE/XRSTOR 管理）。当 "XSETBV exiting" VM\-execution control 位为 1 时触发。|VMM 检查 Guest 是否有权限执行 XSETBV（需要 CPL=0 且 CR4\.OSXSAVE=1）。VMM 验证写入 XCR0 的值是否合法（不启用未支持的位），更新 Guest 的虚拟 XCR0。如果非法，注入 \#GP。VMM 推进 RIP 并恢复执行。|
|59|EXIT\_REASON\_VMFUNC|Guest 执行 VMFUNC 指令（VM Function），该指令允许 Guest 在不触发 VM exit 的情况下执行特定 VM 功能（如 EPTP 切换）。但当 VMFUNC 指令参数无效或 VMFUNC 未启用时触发退出。|VMM 检查 VMFUNC 的 function 号和参数。如果合法，VMM 执行对应操作（如切换 EPTP 指向不同的 EPT 页表）；如果非法，注入 \#UD 或 \#GP。VMM 推进 RIP 并恢复 Guest 执行。|
|62|EXIT\_REASON\_PML\_FULL|Page Modification Logging（PML）缓冲区已满。当 "enable PML" VM\-execution control 位为 1 时，硬件自动记录 Guest 对 EPT 页面的写操作。当 PML 缓冲区的 512 个条目全部用完时触发。|VMM 刷新 PML 缓冲区，将脏页记录转移到软件数据结构中（如 dirty bitmap），然后清空 PML 缓冲区并恢复 Guest 执行。PML 用于实现高效的脏页追踪，常用于实时迁移（live migration）场景。|
|63|EXIT\_REASON\_XSAVES|Guest 执行 XSAVES 指令，且该指令在当前 VMX 配置下不被允许时触发。XSAVES 用于将扩展处理器状态保存到内存（与 XRSTORS 配对，支持 supervisor\-state 和 user\-state 的保存）。|VMM 检查 Guest 是否有权限执行 XSAVES。如果允许，VMM 模拟该指令（保存 Guest 的扩展处理器状态到 Guest 内存）；如果不允许，注入 \#UD。VMM 推进 RIP 并恢复 Guest 执行。|
|64|EXIT\_REASON\_XRSTORS|Guest 执行 XRSTORS 指令，且该指令在当前 VMX 配置下不被允许时触发。XRSTORS 用于从内存恢复扩展处理器状态（与 XSAVES 配对）。|VMM 检查 Guest 是否有权限执行 XRSTORS。如果允许，VMM 模拟该指令（从 Guest 内存读取状态数据并恢复处理器状态）；如果不允许，注入 \#UD。VMM 推进 RIP 并恢复 Guest 执行。|
|74|EXIT\_REASON\_BUS\_LOCK|Guest 在执行过程中获取了总线锁（bus lock，如通过 LOCK 前缀指令跨缓存行操作触发 split lock），且 "bus lock detection" VM\-execution control 位为 1 时触发。总线锁会严重影响系统整体性能，因为它会阻塞所有核心对总线的访问。|VMM 处理总线锁退出主要用于性能隔离和安全防护。常见策略包括：\(1\) 记录日志并告警；\(2\) 对 Guest 进行节流（throttling），如延迟恢复 Guest 执行以降低其总线锁频率；\(3\) 注入 \#UD 或 \#GP 惩罚恶意 Guest。VMM 推进 RIP 并恢复 Guest 执行。|
|75|EXIT\_REASON\_NOTIFY|当 "notify VM exit" VM\-execution control 位为 1 时，VM 在满足特定条件时触发此退出。Notify VM Exit 是一种安全机制，当 CPU 内部出现无法正常退出 Guest 的异常情况时，强制触发 VM exit 以防止 Guest 挂起系统。|VMM 将此退出视为安全保护机制。VMM 检查退出上下文信息，决定是否可以安全恢复 Guest 执行，或需要终止 Guest 以防止系统级影响。通常用于防止恶意 Guest 利用某些 CPU 行为（如无限循环在 microcode 中）导致系统挂起。|
|77|EXIT\_REASON\_TDCALL|Guest 执行 TDCALL 指令（Intel Trust Domain Extensions, TDX 相关），请求从 Trust Domain（TD）中退出到 VMM 或 TDX module。TDCALL 是 TDX 虚拟化架构中 Guest 向 TDX module 传递控制权的指令。|VMM 解析 TDCALL 的 leaf function 和参数。如果 VMM 支持 TDX 虚拟化，它处理对应的 TDX hypercall（如 TD 内存管理、TD 报告生成等）；如果不支持或请求非法，VMM 可能注入 \#UD。VMM 推进 RIP 并恢复 Guest 执行。|

---

## 14\. INVVPID 指令（退出码 53）

INVVPID 用于使特定虚拟处理器 ID（VPID）作用域内的 TLB 条目失效。启用 VPID 后，CPU 可以在 VM exit 之间缓存 Guest 的 TLB 条目，从而提升性能。

|退出码|名称|触发原因|VMM 处理方式|
|---|---|---|---|
|53|EXIT\_REASON\_INVVPID|Guest 执行 INVVPID 指令（基于 VPID 使 TLB 条目失效），且 "INVVPID exiting" VM\-execution control 位已设置（通常用于支持嵌套虚拟化）。|如果支持嵌套虚拟化，VMM 代表 L1 Guest 执行 VPID 作用域的 TLB 失效操作，使用 L1 Guest 的虚拟 VPID 映射。VMM 确保失效操作的作用域正确，以避免影响其他 Guest 或宿主。推进 RIP 并恢复执行。如果不支持嵌套虚拟化，则注入 \#UD。|

---

## 15\. SGX 相关（退出码 60、65）

Intel SGX（Software Guard Extensions）提供硬件保护的 enclave。与 enclave 相关的指令（ENCLS、ENCLV）被拦截以控制 Guest 对 SGX 的使用。

|退出码|名称|触发原因|VMM 处理方式|
|---|---|---|---|
|60|EXIT\_REASON\_ENCLS|Guest 在 VMX non\-root 操作中执行 ENCLS 指令（enclave 系统指令，用于 SGX enclave 管理 \- ECREATE、EADD、EINIT 等）。"ENCLS exiting" VM\-execution control 位决定是否触发 VM exit。|VMM 从 Guest EAX 读取 ENCLS leaf function。如果支持 SGX 虚拟化，VMM 模拟或中介 ENCLS 操作（例如验证 enclave 参数、管理 EPC \- Enclave Page Cache \- 页面、执行 SGX 策略）。如果 Guest 不支持 SGX 或不允许使用，则注入 \#UD。推进 RIP 并恢复执行。|
|65|EXIT\_REASON\_ENCLV|Guest 在 VMX non\-root 操作中执行 ENCLV 指令（enclave 虚拟指令，用于 SGX 虚拟化支持 \- ETRACK、EWB、ELDU/ELDB 等）。"ENCLV exiting" VM\-execution control 位决定是否触发 VM exit。|VMM 从 Guest EAX 读取 ENCLV leaf function。如果支持 SGX 虚拟化，VMM 为管理 L2 SGX enclave 的 L1 hypervisor 模拟 ENCLV 操作。包括管理 EPC 页面回收、跟踪和换出操作。如果不支持 SGX 虚拟化，则注入 \#UD。推进 RIP 并恢复执行。|

---

**重要说明**

- 退出原因码 5、11、35、42、65\-66、69\-70、72\-73 和 76 要么是保留的、在 Linux 内核中未定义，要么是为未来的 Intel 架构扩展预留的。注意：码 5（IO\_SMI）和 11（GETSEC）在 Intel SDM 中有定义，但在 Linux 内核 vmx\.h 头文件中未定义。码 65（ENCLV）在 Intel SDM 中为 SGX 虚拟化定义，但尚未在 Linux 内核头文件中定义。码 57（RDRAND）、60（ENCLS）、62（PML\_FULL）、63（XSAVES）、64（XRSTORS）、67（UMWAIT）、68（TPAUSE）和 74（BUS\_LOCK）是有效的退出原因，已在上文各自章节中记录。

- VM\_EXIT\_REASON VMCS 字段（偏移 0x4402）为 32 位宽：位 15:0 包含基本退出原因，位 16 表示 VM\-exit 是否由 VM\-entry 失败导致（对应退出码 33、34、41），位 31 表示 VM\-entry 失败是否由不一致性导致。

- VM\_EXIT\_QUALIFICATION 字段为许多退出原因提供附加上下文信息（例如 MOV CR 的 CR 编号、I/O 的端口号、EPT 违规的访问类型）。

- VM\_EXIT\_INSTRUCTION\_INFO 字段为指令引发的 VM exit 提供指令解码信息（例如操作数大小、寻址模式、段覆盖前缀）。

- VM\_EXIT\_INSTRUCTION\_LENGTH 字段提供导致 VM exit 的指令长度，VMM 利用该值来推进 Guest 的 RIP。

- GUEST\_LINEAR\_ADDRESS 和 GUEST\_PHYSICAL\_ADDRESS 字段为内存相关退出提供地址上下文信息。

- 启用 VPID（Virtual Processor ID）和 EPT 可以显著降低 VM\-exit 频率，通过允许 TLB 条目在 VM exit 之间持久保留以及消除影子页表维护来实现。

- Posted interrupts 可以减少中断相关的 VM exit，通过 posted\-interrupt 描述符允许直接向 Guest 投递中断。

- VMCS shadowing（退出原因 23/25 上下文）加速嵌套虚拟化，允许 VMREAD/VMWRITE 在影子 VMCS 上操作，大多数字段无需 VMM 介入。

---

## 退出类别汇总

|类别|退出码|主要用途|
|---|---|---|
|异常与中断|0\-8|事件投递与中断虚拟化|
|系统与任务管理|9\-13|CPU 状态与任务切换虚拟化|
|TLB 与缓存管理|14\-16, 51, 54, 56\-58, 61|TLB 与缓存一致性控制|
|VMX 指令|18\-27|嵌套虚拟化与 hypercall|
|控制寄存器访问|28|分页与保护控制|
|调试寄存器访问|29|硬件调试虚拟化|
|I/O 指令|30|设备 I/O 虚拟化|
|MSR 访问|31\-32|MSR 虚拟化与保护|
|VM\-Entry 失败|33\-34, 41|VM\-entry 健壮性与错误处理|
|监视与等待|36\-40, 67\-68|电源管理与自旋锁优化|
|APIC 虚拟化|43\-45, 52|中断控制器虚拟化|
|描述符表访问|46\-47|段系统虚拟化|
|EPT 与内存虚拟化|48\-50, 55, 59, 62\-64, 74\-75, 77|内存虚拟化与脏页追踪|
|INVVPID|53|VPID 作用域的 TLB 失效|
|SGX 相关|60, 65|SGX enclave 虚拟化|

# 二、AMD SVM VM Exit 退出码

**AMD SVM VM Exit 基础**

AMD 安全虚拟机（SVM）使用 **VMCB（虚拟机控制块）**来控制客户机行为。VMCB 包含两个区域：一个带有拦截位的**控制区域**和一个用于保存客户机状态的**保存区域**。当客户机操作触发拦截时，CPU 执行 **\#VMEXIT**：将客户机状态保存到 VMCB 保存区域，加载宿主机状态，并将控制权转移到 VMM。VMM 从 VMCB 控制区域读取 `EXITCODE` 以确定退出原因并进行相应处理。


关键概念：


- **拦截式退出**在指令提交*之前*触发（类似于陷阱），允许 VMM 进行模拟、跳过或注入事件。


- **NPT（嵌套页表）**为内存虚拟化提供硬件辅助的二维页表转换。


- **AVIC（高级虚拟中断控制器）**虚拟化 APIC，在可能的情况下无需退出即可完成中断投递。


- **SEV\-ES/SEV\-SNP** 加密虚拟化引入了 **VMGEXIT**（通过 GHCB），改变了加密客户机的退出处理模型。


- 退出码 `0x000`\-`0x0A6` 为传统/标准 SVM 退出；`0x400`\-`0x403` 为 NPT 故障退出；`0x100+` 为 SEV\-ES VMGEXIT 事件。

## 1\. CR 读写拦截（0x000–0x009）

控制寄存器（CR）访问拦截通过 VMCB `CR_INTERCEPTS` 字段中的位来启用。每个 CR 的读或写都可以被独立拦截。VMM 通常模拟寄存器访问，检查客户机可见的副作用（例如 CR0/CR4 写入时的分页模式变更），然后恢复客户机运行。

|退出码|名称|触发原因|VMM 处理方式|
|---|---|---|---|
|`0x000`|SVM\_EXIT\_READ\_CR0|客户机执行读取 CR0 的指令（如 `MOV rAX, CR0`）且 VMCB 中 CR0 读拦截位已设置。|VMM 从 VMCB 保存区读取客户机 CR0 值，模拟读取操作（将值放入目标寄存器），推进 RIP 并恢复客户机。|
|`0x001`|SVM\_EXIT\_READ\_CR4|客户机读取 CR4 且 VMCB 中 CR4 读拦截位已设置。|VMM 返回客户机 CR4 值，推进 RIP 并恢复客户机。|
|`0x002`|SVM\_EXIT\_WRITE\_CR0|客户机写入 CR0（如 `MOV CR0, rAX`）且 CR0 写拦截位已设置。|VMM 验证新的 CR0 值，检查分页/PE/PG 模式转换，更新影子/组合 CR0（如使用），推进 RIP 并恢复。可能需要在模式切换时刷新 TLB 或调整 NPT 上下文。|
|`0x003`|SVM\_EXIT\_READ\_CR3|客户机读取 CR3 且 CR3 读拦截位已设置。|VMM 返回客户机 CR3（物理地址或通过 NPT 转换的地址），推进 RIP 并恢复客户机。|
|`0x004`|SVM\_EXIT\_READ\_CR2|客户机读取 CR2（页错误线性地址）且 CR2 读拦截位已设置。|VMM 返回客户机 CR2 值（最近出错的地址），推进 RIP 并恢复客户机。|
|`0x005`|SVM\_EXIT\_WRITE\_CR2|客户机写入 CR2 且 CR2 写拦截位已设置。|VMM 在 VMCB 保存区更新客户机 CR2，推进 RIP 并恢复客户机。|
|`0x006`|SVM\_EXIT\_WRITE\_CR3|客户机写入 CR3（上下文切换 / TLB 刷新）且 CR3 写拦截位已设置。|VMM 更新客户机 CR3，可能刷新客户机 TLB 条目或更新 NPT 根指针，推进 RIP 并恢复。常用于跟踪客户机地址空间切换。|
|`0x007`|SVM\_EXIT\_WRITE\_CR4|客户机写入 CR4 且 CR4 写拦截位已设置。|VMM 验证新的 CR4 值（如 PAE、SMEP、SMAP、VMX 位），更新影子/组合 CR4，推进 RIP 并恢复。可能需要重新评估分页模式。|
|`0x008`|SVM\_EXIT\_READ\_CR8|客户机读取 CR8（任务优先级寄存器 / TPR）且 CR8 读拦截位已设置。|VMM 返回客户机 CR8/TPR 值。如果 AVIC 已启用，可以避免此拦截。VMM 推进 RIP 并恢复客户机。|
|`0x009`|SVM\_EXIT\_WRITE\_CR8|客户机写入 CR8（TPR 更新）且 CR8 写拦截位已设置。|VMM 更新客户机 TPR，可能重新评估待处理的虚拟中断交付（VINTR），推进 RIP 并恢复。启用 AVIC 时，硬件无需退出即可处理 TPR 更新。|

---

## 2\. DR 读写拦截（0x006–0x00F）

调试寄存器（DR）访问拦截通过 VMCB `DR_INTERCEPTS` 字段中的位来启用。这些拦截在读或写 DR0–DR7 的 `MOV` 指令上触发。退出码空间 0x006–0x00F 与 CR 写入共享（见上文），因此 DR 拦截使用此处所述的相同码。

|退出码|名称|触发原因|VMM 处理方式|
|---|---|---|---|
|`0x006`|SVM\_EXIT\_READ\_DR0–DR7|客户机执行 `MOV rAX, DRn`（n=0–7）且 VMCB 中 DR 读拦截位已设置。|VMM 从保存区读取客户机 DR 值或模拟读取（通常返回 0 或安全值以避免泄漏宿主机调试状态），推进 RIP 并恢复客户机。|
|`0x007`|SVM\_EXIT\_WRITE\_DR0–DR7|客户机执行 `MOV DRn, rAX`（n=0–7）且 VMCB 中 DR 写拦截位已设置。|VMM 验证 DR 写入（如确保未在宿主机内存上设置断点），保存或丢弃该值，推进 RIP 并恢复。VMM 可选择遵循客户机调试断点以提供调试支持。|

---

## 3\. 异常拦截（0x040–0x07F）

AMD SVM 允许通过 VMCB 中的 `EXCEPTION_INTERCEPTION` 位图拦截单个 CPU 异常（向量 0–31）。每个异常向量 *n* 映射到退出码 `0x040 + n`。当客户机中发生异常且对应的拦截位被设置时，会在异常交付给客户机处理程序*之前*触发 \#VMEXIT。

|退出码|名称|触发原因|VMM 处理方式|
|---|---|---|---|
|`0x040`|SVM\_EXIT\_EXCP\_DE|客户机触发 \#DE（除零错误）。VMCB 异常拦截位图中 DE 拦截位已设置。|VMM 通常通过 VINTR 机制（设置 `VMCB.control.EVENTINJ`）将异常反射回客户机，注入 \#DE。极少需要特殊 VMM 处理。|
|`0x041`|SVM\_EXIT\_EXCP\_DB|客户机触发 \#DB（调试陷阱/错误，如代码/数据断点或单步执行）。DB 拦截位已设置。|VMM 检查调试条件是否由客户机发起。如果是，向客户机注入 \#DB。如果是宿主机断点，则内部处理。必须仔细区分客户机与宿主机调试事件。|
|`0x042`|SVM\_EXIT\_EXCP\_NMI|客户机有一个待处理的 NMI 且 NMI 拦截位已设置。|VMM 可直接处理 NMI（宿主机 NMI）或通过 VINTR 注入到客户机。如果客户机处于临界区，VMM 可延迟交付。|
|`0x043`|SVM\_EXIT\_EXCP\_BP|客户机执行 `INT3` 且 BP 拦截位已设置。|VMM 通常通过注入异常将 \#BP 反射到客户机。用于客户机调试支持。|
|`0x044`|SVM\_EXIT\_EXCP\_OF|客户机在 OF=1 时执行 `INTO` 且 OF 拦截位已设置。|VMM 通过 VINTR 注入将 \#OF 反射到客户机。|
|`0x045`|SVM\_EXIT\_EXCP\_BR|客户机执行 `BOUNDS` 检查失败且 BR 拦截位已设置。|VMM 将 \#BR 反射到客户机。|
|`0x046`|SVM\_EXIT\_EXCP\_UD|客户机执行未定义/无效操作码且 UD 拦截位已设置。|VMM 可将 \#UD 反射到客户机，或如果该指令属于半虚拟化接口的一部分，则模拟它。常用于不支持的指令模拟。|
|`0x047`|SVM\_EXIT\_EXCP\_NM|客户机在 CR0\.TS=1 时访问 x87 FPU 且 NM 拦截位已设置。|VMM 执行延迟 FPU 保存/恢复：保存宿主机 FPU 状态，恢复客户机 FPU 状态，为客户机清除 CR0\.TS，然后恢复客户机。|
|`0x048`|SVM\_EXIT\_EXCP\_DF|客户机在处理另一个异常时遇到异常且 DF 拦截位已设置。|VMM 反射 \#DF 或根据策略重置/终止客户机。双重错误通常表明客户机操作系统不稳定。|
|`0x049`|SVM\_EXIT\_EXCP\_TS|客户机任务切换引用了无效 TSS 且 TS 拦截位已设置。|VMM 将 \#TS 反射到客户机。在不使用硬件任务切换的现代 64 位客户机中很少见。|
|`0x04A`|SVM\_EXIT\_EXCP\_NP|客户机访问 P=0 的段描述符且 NP 拦截位已设置。|VMM 将 \#NP 反射到客户机。|
|`0x04B`|SVM\_EXIT\_EXCP\_SS|客户机栈段访问失败（如 SS 限长违规）且 SS 拦截位已设置。|VMM 将 \#SS 反射到客户机。|
|`0x04C`|SVM\_EXIT\_EXCP\_GP|客户机触发 \#GP（如在 CPL\>0 时执行特权指令、段限长违规）且 GP 拦截位已设置。|VMM 将 \#GP 反射到客户机。也可用于半虚拟化（客户机尝试本应通过超调用完成的特权操作）。|
|`0x04D`|SVM\_EXIT\_EXCP\_PF|客户机触发 \#PF（页不存在、保护违规）且 PF 拦截位已设置。|VMM 遍历客户机页表以确定错误是客户机真实的还是需要影子/NPT 介入。如果合法，向客户机注入 \#PF 并设置相应的 CR2 和错误码。启用 NPT 时，许多页错误由硬件处理而无需退出。|
|`0x04E`|SVM\_EXIT\_EXCP\_MF|客户机 x87 FPU 通过 FERR\# 发出未屏蔽异常信号且 MF 拦截位已设置。|VMM 将 \#MF 反射到客户机。在使用现代基于 SSE 的浮点时很少见。|
|`0x04F`|SVM\_EXIT\_EXCP\_AC|客户机在 CR0\.AM=1 且 EFLAGS\.AC=1 时触发对齐检查（\#AC）且 AC 拦截位已设置。|VMM 将 \#AC 反射到客户机。|
|`0x050`|SVM\_EXIT\_EXCP\_MC|客户机触发机器检查异常且 MC 拦截位已设置。|VMM 谨慎处理 \#MC — 可反射到客户机、记录错误或终止 VM。机器检查表明硬件错误。|
|`0x051`|SVM\_EXIT\_EXCP\_XM|客户机 SSE/AVX 指令触发未屏蔽的 SIMD 浮点异常且 XM 拦截位已设置。|VMM 将 \#XM（\#XF）反射到客户机。|
|`0x052`|SVM\_EXIT\_EXCP\_VE|客户机因 EPT 违规（Intel）或等效机制遇到 \#VE。在 AMD 上较少见，但可能用于某些虚拟化配置。|VMM 在客户机有 \#VE 处理程序时将 \#VE 反射到客户机。在 AMD 上，NPT 错误通常通过退出码 0x400–0x403 以不同方式处理。|
|`0x053–0x05F`|SVM\_EXIT\_EXCP\_RESERVED|保留的异常向量 19–31。这些向量要么架构未定义，要么用于平台特定目的。|VMM 处理方式因平台而异。通常反射到客户机，如果未定义则视为致命错误。|

**注意：**异常向量 0x060–0x07F 对应向量 32–63，这些*不是* CPU 异常，而是 IRQ 向量。在 AMD SVM 中，中断注入通过 `VINTR` 拦截（退出码 `0x084`）处理，而非按向量的异常拦截。

---

## 4\. 系统指令与事件（0x080–0x091）

这些拦截涵盖 VMM 需要虚拟化的系统级事件和指令，包括中断投递、描述符表访问以及时间戳/性能计数器读取。它们通过 VMCB `INTERCEPTS` 字段中的位来启用。

|退出码|名称|触发原因|VMM 处理方式|
|---|---|---|---|
|`0x080`|SVM\_EXIT\_INTR|客户机运行期间收到外部中断且 VMCB 中 INTR 拦截位已设置。|VMM 读取中断向量，如果是宿主机中断则处理它，或通过 VINTR 注入到客户机。VMM 可对客户机屏蔽某些中断并在宿主机层面处理。|
|`0x081`|SVM\_EXIT\_NMI|客户机运行期间收到 NMI 且 NMI 拦截位已设置。|VMM 确定该 NMI 是给宿主机还是客户机的。宿主机 NMI 直接处理。客户机 NMI 在宿主机 NMI 处理程序完成后通过 VINTR 注入。|
|`0x082`|SVM\_EXIT\_SMI|客户机运行期间收到 SMI 信号且 SMI 拦截位已设置。|VMM 退出到宿主机 SMM 处理程序。客户机被挂起，在 SMM 返回后恢复。SMI 通常对客户机不可见。|
|`0x083`|SVM\_EXIT\_INIT|客户机运行期间收到 INIT 信号且 INIT 拦截位已设置。|VMM 可对客户机执行软重置或延迟 INIT。通常用于客户机重置/重启逻辑。VMM 决定是重置客户机还是忽略 INIT 信号。|
|`0x084`|SVM\_EXIT\_VINTR|客户机有一个待处理的虚拟中断（由 VMM 通过 VINTR 机制注入）已准备好交付，且客户机的中断可交付条件已满足。VINTR 拦截位已设置。|VMM 检查虚拟中断是否可以交付给客户机。如果可以，通过 `VMCB.control.EVENTINJ` 注入并清除虚拟中断源。这是 AMD 中断虚拟化的核心。启用 AVIC 时，许多中断交付可完全避免此退出。|
|`0x085`|SVM\_EXIT\_CR0\_SEL\_WRITE|客户机写入 CR0 且新值改变了影响分页或保护模式的位（PE、PG、CD、NW）。CR0 选择性写拦截位已设置。这是一种*选择性*拦截 — 仅在特定位改变时触发，不同于无条件 CR0 写拦截（0x002）。|VMM 处理分页模式转换，根据需要更新影子页表或 NPT 配置，在需要时刷新 TLB，然后恢复客户机。对于管理客户机在实模式、保护模式和长模式之间的转换至关重要。|
|`0x086`|SVM\_EXIT\_IDTR\_READ|客户机执行 `SIDT`（存储 IDTR）且 IDTR 读拦截位已设置。|VMM 返回影子 IDTR 值（以避免泄漏宿主机 IDT 位置），推进 RIP 并恢复客户机。|
|`0x087`|SVM\_EXIT\_IDTR\_WRITE|客户机执行 `LIDT`（加载 IDTR）且 IDTR 写拦截位已设置。|VMM 保存客户机 IDTR 值，验证它，更新影子 IDTR（如使用），推进 RIP 并恢复。VMM 跟踪客户机 IDT 基地址用于异常注入。|
|`0x088`|SVM\_EXIT\_GDTR\_READ|客户机执行 `SGDT`（存储 GDTR）且 GDTR 读拦截位已设置。|VMM 返回影子 GDTR 值，推进 RIP 并恢复客户机。|
|`0x089`|SVM\_EXIT\_GDTR\_WRITE|客户机执行 `LGDT`（加载 GDTR）且 GDTR 写拦截位已设置。|VMM 保存客户机 GDTR 值，更新影子 GDT（如使用），推进 RIP 并恢复客户机。|
|`0x08A`|SVM\_EXIT\_LDTR\_READ|客户机执行 `SLDT`（存储 LDTR）且 LDTR 读拦截位已设置。|VMM 返回客户机 LDTR 选择子值，推进 RIP 并恢复客户机。|
|`0x08B`|SVM\_EXIT\_LDTR\_WRITE|客户机执行 `LLDT`（加载 LDTR）且 LDTR 写拦截位已设置。|VMM 验证并保存客户机 LDTR 选择子，更新影子 LDT（如使用），推进 RIP 并恢复客户机。|
|`0x08C`|SVM\_EXIT\_TR\_READ|客户机执行 `STR`（存储 TR）且 TR 读拦截位已设置。|VMM 返回客户机 TR 选择子值，推进 RIP 并恢复客户机。|
|`0x08D`|SVM\_EXIT\_TR\_WRITE|客户机执行 `LTR`（加载 TR）且 TR 写拦截位已设置。|VMM 验证并保存客户机 TR 选择子，更新影子 TSS（如使用），推进 RIP 并恢复。在 64 位客户机中很少见。|
|`0x08E`|SVM\_EXIT\_RDTSC|客户机执行 `RDTSC` 且 RDTSC 拦截位已设置。|VMM 返回经过偏移调整的 TSC 值（用于虚拟化客户机时间），推进 RIP 并恢复。VMM 可应用 TSC 偏移以在迁移后提供一致的客户机时间。|
|`0x08F`|SVM\_EXIT\_RDPMC|客户机执行 `RDPMC` 且 RDPMC 拦截位已设置。|VMM 模拟性能计数器读取，返回虚拟化的 PMC 值。VMM 必须确保客户机无法访问宿主机性能计数器。推进 RIP 并恢复。|
|`0x090`|SVM\_EXIT\_PUSHF|客户机执行 `PUSHF`（压入 EFLAGS/RFLAGS）且 PUSHF 拦截位已设置。|VMM 模拟 PUSHF 指令，返回经过清理的标志值（在需要时清除宿主机敏感标志如 IF），推进 RIP 并恢复。用于控制客户机对中断标志状态的可见性。|
|`0x091`|SVM\_EXIT\_POPF|客户机执行 `POPF`（弹出 EFLAGS/RFLAGS）且 POPF 拦截位已设置。|VMM 验证新的标志值，阻止客户机修改宿主机敏感标志（如 IOPL、VIP），应用允许的标志变更，推进 RIP 并恢复。对于虚拟化客户机中断使能（IF）标志至关重要。|

---

## 5\. SVM 指令（0x092–0x09C）

这些拦截涵盖 SVM 特有指令或常见的需虚拟化特权指令。它们由 VMCB `INTERCEPTS` 字段中的位控制。

|退出码|名称|触发原因|VMM 处理方式|
|---|---|---|---|
|`0x092`|SVM\_EXIT\_CPUID|客户机执行 `CPUID` 且 VMCB 中 CPUID 拦截位已设置。|VMM 读取客户机 EAX/ECX 输入，返回虚拟化的 CPUID 结果（隐藏宿主机特性，通过 leaf 0x40000000 告知 hypervisor 存在，模拟特性标志），推进 RIP 并恢复。这是最常被拦截的指令之一。|
|`0x093`|SVM\_EXIT\_RSM|客户机在 SMM 之外执行 `RSM` 且 RSM 拦截位已设置。|VMM 向客户机注入 \#UD（无效操作码），因为 `RSM` 仅在 SMM 中有效。推进 RIP 并恢复。|
|`0x094`|SVM\_EXIT\_IRET|客户机执行 `IRET` 且 IRET 拦截位已设置。|VMM 模拟 IRET，从客户机栈更新客户机 RIP、CS、RFLAGS 和 RSP。对于跟踪客户机中断状态变化（IF 标志、中断影子）至关重要。VMM 可在 IRET 后重新评估待处理的 VINTR 交付。推进 RIP 并恢复。|
|`0x095`|SVM\_EXIT\_SWINT|客户机执行软件中断指令（`INT n`）且 SWINT 拦截位已设置。|VMM 检查向量 *n* 对应的客户机 IDT 表项，验证权限（门类型、DPL），然后向客户机注入中断或在访问无效时注入 \#GP。推进 RIP 并恢复。|
|`0x096`|SVM\_EXIT\_INVD|客户机执行 `INVD`（不回写地使内部缓存失效）且 INVD 拦截位已设置。|VMM 通常将 `INVD` 模拟为空操作（或 `WBINVD`）以防止客户机破坏宿主机缓存状态。推进 RIP 并恢复。|
|`0x097`|SVM\_EXIT\_PAUSE|客户机执行 `PAUSE`（自旋等待提示）且 PAUSE 拦截位已设置。也可能基于 PAUSE 过滤阈值（自旋循环计数超过限制）触发。|VMM 可使用此退出进行自旋锁检测 — 如果客户机 vCPU 正在自旋，VMM 可以调度另一个 vCPU（定向让步）。推进 RIP 并恢复。AMD 支持 PAUSE 过滤器，仅在连续 N 条 PAUSE 指令后才退出。|
|`0x098`|SVM\_EXIT\_HLT|客户机执行 `HLT` 且 HLT 拦截位已设置。|VMM 将 vCPU 标记为暂停，调度另一个 vCPU 或进入宿主机空闲状态，并安排在下一个待处理中断（INTR 或 VINTR）到来时唤醒该 vCPU。当中断到达时，VMM 恢复客户机。客户机在中断唤醒前不会推进 RIP 越过 HLT。|
|`0x099`|SVM\_EXIT\_INVLPG|客户机执行 `INVLPG`（使指定线性地址的 TLB 表项失效）且 INVLPG 拦截位已设置。|VMM 使指定客户机线性地址对应的影子页表项或 NPT TLB 表项失效，推进 RIP 并恢复。启用 NPT 时，CPU 可根据配置在不退出的情况下处理此操作。|
|`0x09A`|SVM\_EXIT\_INVLPGA|客户机执行 `INVLPGA`（AMD 专有指令，用于使当前 ASID 的 TLB 表项失效）且 INVLPGA 拦截位已设置。|VMM 使指定地址和客户机 ASID 对应的 TLB 表项失效，推进 RIP 并恢复。这是 AMD 专有指令，用于半虚拟化客户机。|
|`0x09B`|SVM\_EXIT\_IOIO|客户机执行 I/O 指令（`IN`、`OUT`、`INS`、`OUTS`）且 VMCB 中 IOIO 拦截已配置（通过 IOIO 拦截位图或端口范围）。|VMM 从 VMCB 的 `EXITINFO1`/`EXITINFO2` 字段读取端口号和数据，模拟 I/O 访问（分发给虚拟设备模型），推进 RIP 并恢复。VMM 也可将 I/O 委托给用户空间设备模拟器。|
|`0x09C`|SVM\_EXIT\_MSR|客户机执行 `RDMSR` 或 `WRMSR` 且 VMCB 中 MSR 拦截位已设置。具体 MSR 和访问类型（读/写）记录在 `EXITINFO1` 中。|VMM 从 ECX 读取 MSR 索引，通过返回虚拟化值或验证写入来模拟读或写操作，推进 RIP 并恢复。VMM 维护一组虚拟化的 MSR（如 SYSENTER\_CS/EIP/ESP、STAR、LSTAR 等），并且必须防止客户机访问宿主机敏感的 MSR。|

---

## 6\. 任务切换与停机（0x09D–0x09F）

这些拦截涵盖硬件任务切换和系统关机/冻结条件。

|退出码|名称|触发原因|VMM 处理方式|
|---|---|---|---|
|`0x09D`|SVM\_EXIT\_TASK\_SWITCH|客户机触发硬件任务切换（通过 TSS 门、CALL/RET 到任务门、或 IRET 时 NT 标志置位）且任务切换拦截位已设置。|VMM 模拟任务切换：保存旧 TSS 状态，加载新 TSS，更新 TR，并处理段验证。出错时可注入 \#TS 或 \#GP。在现代 64 位操作系统中任务切换很少见。推进 RIP 并恢复客户机。|
|`0x09E`|SVM\_EXIT\_FERR\_FREEZE|客户机触发 FERR\#（浮点错误）冻结条件 — CPU 冻结指令传递以声明 FERR\#，用于外部 FPU 错误报告机制。FERR\_FREEZE 拦截位已设置。|VMM 处理 FERR\# 冻结，通常向客户机注入 \#MF（数学错误）并清除冻结条件。推进 RIP 并恢复客户机。在使用现代基于 SSE 的浮点时很少见。|
|`0x09F`|SVM\_EXIT\_SHUTDOWN|客户机进入三重错误条件（双重错误处理程序交付期间发生异常）或关闭条件。SHUTDOWN 拦截位已设置。|VMM 处理客户机关闭：通常重置客户机 vCPU（重新初始化状态）或完全终止 VM。VMM 可记录关闭事件用于调试。这是客户机的终止条件。|

---

## 7\. VMRUN/VMMCALL 相关（0x0A0–0x0A2）

这些拦截涵盖管理嵌套虚拟化和客户机到宿主机通信的核心 SVM 指令。

|退出码|名称|触发原因|VMM 处理方式|
|---|---|---|---|
|`0x0A0`|SVM\_EXIT\_VMRUN|客户机执行 `VMRUN`（启动嵌套客户机）且 VMRUN 拦截位已设置。这发生在嵌套虚拟化场景中，L1 虚拟机管理程序尝试启动 L2 客户机。|VMM（L0）处理嵌套虚拟化：验证嵌套 VMCB，通过嵌套 SVM 支持（合并 VMCB 控制字段、ASID 管理）模拟或加速嵌套 VMRUN，并管理 L2 客户机执行。L2 退出时，控制权返回 L1 并携带相应的退出码。|
|`0x0A1`|SVM\_EXIT\_VMMCALL|客户机执行 `VMMCALL`（AMD 的超调用指令，等效于 Intel 的 `VMCALL`）且 VMMCALL 拦截位已设置。|VMM 从客户机 EAX（或按调用约定的其他寄存器）读取超调用号，分派到相应的超调用处理程序，将结果放入客户机寄存器，推进 RIP 并恢复客户机。这是 AMD SVM 客户机的主要半虚拟化接口。|
|`0x0A2`|SVM\_EXIT\_VMLOAD|客户机执行 `VMLOAD`（从 VMCB 加载额外的客户机状态）且 VMLOAD 拦截位已设置。发生在嵌套虚拟化中。|VMM 处理嵌套 VMLOAD：验证源 VMCB，将额外状态（FS、GS、内核 GS 基地址、STAR、LSTAR、CSTAR、SFMASK、SYSENTER MSR）加载到相应寄存器，推进 RIP 并恢复客户机。对于嵌套 SVM，L0 虚拟机管理程序将 L1 VMLOAD 与自身的状态管理合并。|

---

## 8\. VMSAVE 与客户机管理（0x0A3–0x0A6）

这些拦截涵盖状态保存/恢复以及 AMD SVM 特有的全局中断标志管理指令。

|退出码|名称|触发原因|VMM 处理方式|
|---|---|---|---|
|`0x0A3`|SVM\_EXIT\_VMSAVE|客户机执行 `VMSAVE`（将额外的客户机状态保存到 VMCB）且 VMSAVE 拦截位已设置。发生在嵌套虚拟化中。|VMM 处理嵌套 VMSAVE：将额外状态（FS、GS、内核 GS 基地址、STAR、LSTAR、CSTAR、SFMASK、SYSENTER MSR）保存到指定的 VMCB 保存区，推进 RIP 并恢复客户机。与 VMLOAD 互补。|
|`0x0A4`|SVM\_EXIT\_STGI|客户机执行 `STGI`（设置 GIF=1，启用中断）且 STGI 拦截位已设置。|VMM 为客户机启用中断交付（类似于在更高层级设置客户机 IF 标志），可能重新评估待处理中断，推进 RIP 并恢复客户机。VMM 使用 GIF 来控制客户机何时可以接收物理中断和虚拟中断。|
|`0x0A5`|SVM\_EXIT\_CLGI|客户机执行 `CLGI`（设置 GIF=0，禁用中断）且 CLGI 拦截位已设置。|VMM 为客户机禁用中断交付，阻止物理中断和虚拟中断的交付。客户机使用此指令保护临界区。VMM 推进 RIP 并恢复客户机。待处理中断将延迟到执行 STGI 后再交付。|
|`0x0A6`|SVM\_EXIT\_SKINIT|客户机执行 `SKINIT`（安全初始化，用于 DRTM — 动态信任度量根）且 SKINIT 拦截位已设置。|VMM 处理 SKINIT 请求：验证安全启动参数，度量目标镜像（扩展 TPM PCR 寄存器），并模拟安全启动或拒绝该请求。用于在受度量环境中启动可信代码。VMM 必须仔细验证所有参数。|

---

## 9\. NPT 与宿主机相关（0x400–0x403）

NPT（嵌套页表）故障退出发生在客户机的二维页表转换（客户机虚拟地址 → 客户机物理地址 → 宿主机物理地址）在第二级（NPT）转换失败时。当 NPT（嵌套分页）处于活动状态时启用。退出码区分导致故障的访问类型。

|退出码|名称|触发原因|VMM 处理方式|
|---|---|---|---|
|`0x400`|SVM\_EXIT\_NPF|客户机执行内存**读**操作导致 NPT 页错误 — 客户机物理地址没有有效的 NPT 映射，或 NPT 页表条目不允许读访问。|VMM 遍历 NPT 结构，识别导致错误的客户机物理地址（从 `EXITINFO2` 获取），检查访问权限，然后映射该页（例如通过按需分页、内存映射 I/O 模拟或页面迁移），或在客户机物理地址本身无效时向客户机反射 \#PF。VMM 还可通过检查出错地址是否在 MMIO 区域来处理 MMIO 模拟。|
|`0x401`|SVM\_EXIT\_NPF|客户机执行内存**写**操作导致 NPT 页错误 — NPT 页表条目不允许写访问，或客户机物理地址没有有效的 NPT 映射。|VMM 处理方式类似于 NPT\_FAULT\_READ：遍历 NPT，检查写权限，映射页面或模拟 MMIO 写入，或向客户机反射 \#PF。写保护的 NPT 页面常用于脏页跟踪（实时迁移）、写保护客户机页表（影子分页优化）或 MMIO 模拟。|
|`0x402`|SVM\_EXIT\_NPF|客户机执行**指令取指**导致 NPT 页错误 — NPT 页表条目不允许执行访问（NPT 中 NX 位置位），或代码页没有有效的 NPT 映射。|VMM 检查是否应授予执行权限，在适当时将页面映射为可执行，或向客户机反射 \#PF。NPT 执行权限错误用于代码完整性强制执行、宿主机级别的 NX 强制执行，以及影子代码页管理。|
|`0x403`|SVM\_EXIT\_NPF|客户机在**用户模式**（CPL=3）下执行指令取指导致 NPT 页错误。这是一种更细粒度的执行错误，区分用户模式代码执行和管理模式执行。在支持 NPT 用户/管理区分的较新 AMD 处理器上可用。|VMM 处理方式类似于 NPT\_FAULT\_EXECUTE，但需感知错误发生在用户模式下。用于实现更细粒度的代码执行策略（如 W^X 强制执行、用户空间代码完整性）。VMM 可以允许管理模式在同一页面上执行，同时阻止用户模式执行。|

**NPT 故障详情：**在 NPT 故障退出时，`EXITINFO1` 包含故障错误码（位 0 = P 存在，位 1 = 写入，位 2 = 用户，位 3 = RSVD，位 4 = I/D 取指，位 5 = PK），`EXITINFO2` 包含导致故障的*客户机物理地址*。NPT 故障发生在第二级转换；客户机自身的页表（第一级）可能有效也可能无效。如果客户机自身的转换也发生故障，CPU 会优先处理 NPT 故障，VMM 必须先处理 NPT 故障，然后重新进入客户机，客户机将在那里遇到自身的 \#PF。

---

## 10\. SEV\-ES VMGEXIT 事件（0x100\+）

SEV\-ES（安全加密虚拟化 – 加密状态）改变了 VM 退出处理模型。由于客户机的寄存器状态是加密的，VMM 无法通过 VMCB 保存区域直接读取或修改客户机寄存器。相反，SEV\-ES 客户机使用 **VMGEXIT**（VM 客户机消息退出）通过 **GHCB（客户机\-宿主机通信块）**与 VMM 通信。客户机执行 `VMMCALL` 并使用特定的 GHCB 协议，VMM 通过 GHCB 处理请求。

**SEV\-ES/SEV\-SNP 安全说明：**在 SEV\-ES 中，VMM 无法访问加密的客户机寄存器状态。所有寄存器状态交换必须通过 GHCB 进行，客户机在退出前显式填充 GHCB。这防止了 VMM 篡改客户机状态。SEV\-SNP 增加了额外的完整性保护和反向映射表（RMP）检查。

|退出码|名称|触发原因|VMM 处理方式|
|---|---|---|---|
|`0x100`|SVM\_VMGEXIT|SEV\-ES 客户机执行 `VMMCALL`（重新定义为 VMGEXIT）且已配置 GHCB。GHCB 的 `SW_EXIT_CODE` 字段指定了详细的请求类型。|VMM 读取 GHCB 以确定具体请求（SW\_EXIT\_CODE），按照 GHCB 协议处理，将结果写回 GHCB，然后恢复客户机。VMM 必须验证所有 GHCB 字段，不能信任客户机寄存器状态（已加密）。|
|`0x100` \(GHCB: 0x001\)|SVM\_VMGEXIT\_MMIO\_READ|SEV\-ES 客户机通过 GHCB 请求内存映射 I/O 读取。客户机在 GHCB 中放置 MMIO 物理地址和大小。|VMM 从 GHCB 读取 MMIO 地址和大小，代表客户机执行 MMIO 读取，将结果数据写回 GHCB，然后恢复客户机。VMM 必须验证 MMIO 地址位于合法的 MMIO 区域内。|
|`0x100` \(GHCB: 0x002\)|SVM\_VMGEXIT\_MMIO\_WRITE|SEV\-ES 客户机通过 GHCB 请求内存映射 I/O 写入。客户机在 GHCB 中放置 MMIO 物理地址、大小和数据。|VMM 从 GHCB 读取 MMIO 地址、大小和数据，执行 MMIO 写入，然后恢复客户机。VMM 在执行写入前验证 MMIO 区域。|
|`0x100` \(GHCB: 0x003\)|SVM\_VMGEXIT\_NMI\_COMPLETE|SEV\-ES 客户机通知它已完成 NMI 处理。客户机在 GHCB 中设置此项以告知 VMM NMI 已完全处理。|VMM 清除客户机的待处理 NMI 状态并恢复。这是必要的，因为在 SEV\-ES 中，VMM 无法直接观察客户机的中断标志状态。|
|`0x100` \(GHCB: 0x004\)|SVM\_VMGEXIT\_AP\_CREATE|SEV\-ES 客户机请求 VMM 创建/启动一个 AP（应用处理器）vCPU。客户机在 GHCB 中提供 AP 的 vCPU ID、初始 RIP 和其他状态。|VMM 创建或初始化指定的 AP vCPU，从 GHCB 提供的值设置其初始状态，并使其可运行。用于加密虚拟机中的客户机 SMP 启动，此时 VMM 无法直接操控 AP 寄存器状态。|
|`0x100` \(GHCB: 0x005\)|SVM\_VMGEXIT\_AP\_DESTROY|SEV\-ES 客户机请求 VMM 销毁/停止一个 AP vCPU。客户机在 GHCB 中提供 AP 的 vCPU ID。|VMM 停止指定的 AP vCPU，释放相关资源，然后恢复调用的 vCPU。用于加密虚拟机中的客户机 CPU 热插拔或关机。|
|`0x100` \(GHCB: 0x006\)|SVM\_VMGEXIT\_SNP\_PAGE\_STATE\_CHANGE|SEV\-SNP 客户机请求页面状态转换（例如将页面从私有变为共享，或从共享变为私有）。客户机在 GHCB 中提供页面范围和目标状态。|VMM 处理页面状态变更请求，更新 RMP（反向映射页）表项以反映新的页面状态（私有/共享），并在需要时刷新 TLB 表项。对于私有到共享的转换，VMM 可能需要与 hypervisor 的内存管理协调。处理完成后恢复客户机。|
|`0x100` \(GHCB: 0x007\)|SVM\_VMGEXIT\_SNP\_GUEST\_REQUEST|SEV\-SNP 客户机通过 VMM 向 SNP 固件（PSP \- 平台安全处理器）发送请求。客户机在 GHCB 中提供请求数据和响应缓冲区。|VMM 将客户机请求转发给 PSP 固件，等待响应，然后通过 GHCB 将结果返回给客户机。用于认证、密钥推导和其他固件服务。VMM 充当中继，但无法检查加密的请求/响应载荷。|
|`0x100` \(GHCB: 0x008\)|SVM\_VMGEXIT\_SNP\_EXT\_GUEST\_REQUEST|SEV\-SNP 客户机向 SNP 固件发送扩展请求，包括标准 GHCB 之外的额外数据页。用于更大的认证报告。|VMM 将扩展请求转发给 PSP，处理额外的数据页（可能跨越多页），并将结果返回给客户机。VMM 必须处理更大的缓冲区大小并确保正确的页对齐。|
|`0x100` \(GHCB: 0x009\)|SVM\_VMGEXIT\_REGISTER\_GHCB\_GPA|SEV\-ES 客户机向 VMM 注册其 GHCB 的客户机物理地址（GPA）。这通常是客户机发出的第一个 VMGEXIT，用于建立通信通道。|VMM 记录客户机的 GHCB GPA，验证它指向一个有效的共享（未加密）页面，然后恢复客户机。后续的 VMGEXIT 事件将使用此注册的 GHCB 进行通信。|
|`0x100` \(GHCB: 0x00A\)|SVM\_VMGEXIT\_GHCB\_MSR|SEV\-ES 客户机使用简化的 GHCB MSR 协议（用于 GHCB 建立之前的早期启动阶段）。客户机写入 `MSR_AMD64_SEV_ES_GHCB` 并执行 `VMMCALL`。请求和响应编码在 MSR 值中。|VMM 解码 MSR 值以确定请求类型，处理它（如 MMIO 读/写、寄存器交换），将响应写入 GHCB MSR，然后恢复。用于客户机建立完整内存中 GHCB 之前。|
|`0x100` \(GHCB: 0x00B\)|SVM\_VMGEXIT\_SNP\_RUN\_VMPL|SEV\-SNP 客户机请求转换到不同的 VMPL（虚拟机特权级）。VMPL 在加密客户机内提供分层特权隔离。|VMM 验证 VMPL 转换请求，如果允许则更新客户机的 VMPL 上下文，然后恢复客户机。VMPL 转换受 SNP 固件验证和客户机当前 VMPL 的约束。|
|`0x100` \(GHCB: 0x100\+\)|SVM\_VMGEXIT\_HYPERVISOR\_FEATURES|SEV\-ES 客户机通过 GHCB 向 VMM 查询支持的 hypervisor 特性。客户机提供特性查询掩码。|VMM 通过 GHCB 返回支持特性的位掩码（如 AP 创建、页面状态变更、扩展客户机请求），然后恢复客户机。允许客户机在运行时发现 VMM 能力。|

**SEV\-ES 退出处理差异：**

在 SEV\-ES 中，标准 VM 退出（如 `#VC` — SEV\-ES VMM 通信异常）作为异常向量 29（\#VC）交付给客户机。客户机的 \#VC 处理程序然后使用 VMGEXIT 通过 GHCB 与 VMM 通信。这意味着：


1. VMM 无法直接注入中断或异常 — 必须使用 GHCB 协议。


2. 寄存器状态交换是显式的 — 客户机通过 GHCB 选择共享哪些内容。


3. 客户机中的 `#VC` 处理程序必须谨慎编写，以避免重入并处理所有必需的 VMGEXIT 事件。


4. SEV\-SNP 增加了 RMP（反向映射页）强制执行 — VMM 无法将客户机声明为共享的页面映射为私有，反之亦然。

---

## 退出码范围参考汇总

|退出码范围|类别|数量|
|---|---|---|
|`0x000–0x009`|CR 读/写拦截|10|
|`0x006–0x00F`|DR 读/写拦截（与 CR 共享）|2 个独立|
|`0x040–0x05F`|异常拦截（向量 0–31）|32|
|`0x080–0x091`|系统指令/事件|18|
|`0x092–0x09C`|SVM 指令|11|
|`0x09D–0x09F`|任务切换与关闭|3|
|`0x0A0–0x0A2`|VMRUN/VMMCALL 相关|3|
|`0x0A3–0x0A6`|VMSAVE 与客户机管理|4|
|`0x400–0x403`|NPT 错误|4|
|`0x100+`|SEV\-ES VMGEXIT 事件（通过 GHCB）|可变|

**参考文献：**AMD64 架构程序员手册（APM）第 2 卷：系统编程，第 15 章 — 安全虚拟机。有关 SEV\-ES/SEV\-SNP，请参阅 GHCB 规范和 AMD SEV\-SNP 固件 ABI 规范。

# 三、Intel 与 AMD 退出机制对比

Intel VMX 和 AMD SVM 虽然都实现了 x86 硬件虚拟化，但在退出机制的设计哲学、控制结构和处理流程上存在显著差异。本节从控制结构、退出码编码、触发方式、内存虚拟化、中断虚拟化等维度进行系统对比。

|对比维度|Intel VMX|AMD SVM|
|---|---|---|
|**控制结构**|VMCS \(Virtual Machine Control Structure\)，每个 vCPU 一个，包含执行控制、退出控制、入口控制、Guest 状态、Host 状态|VMCB \(Virtual Machine Control Block\)，包含控制区（拦截位、TLB 控制）和保存区（Guest 寄存器状态）|
|**退出码存储**|VMCS 字段 `VM_EXIT_REASON` \(offset 0x4402\)，16\-bit 基本原因码 \+ 状态位（bit 27 enclave, bit 31 entry failure）|VMCB 控制区 `EXITCODE` 字段，64\-bit，直接存储退出码|
|**退出指令**|`VMLAUNCH` / `VMRESUME` 进入 Guest；VMExit 自动切换|`VMRUN` 进入 Guest；VMExit 自动切换回 Host|
|**状态保存**|CPU 自动将 Guest 状态保存到 VMCS Guest\-State Area，加载 Host 状态从 VMCS Host\-State Area|CPU 自动将 Guest 状态保存到 VMCB Save Area；Host 状态从指定 MSR / VMCB Host State 加载|
|**退出原因数量**|\~75\+ 定义的基本退出原因码（0\-75\+），部分保留|\~90\+ 定义退出码（0x000\-0x0A6, 0x400\-0x403, SEV\-ES VMGEXIT）|
|**拦截方式**|基于 VMCS Execution Controls（Primary/Secondary/Tertiary），精细控制每类指令/事件|基于 VMCB 拦截位（Intercept Bits），按指令/事件类型设置位图|
|**内存虚拟化**|EPT \(Extended Page Tables\)，EPT violation/misconfiguration 触发 VMExit（码 48/49）|NPT \(Nested Page Tables\)，NPT fault 按读/写/执行分别退出（码 0x400\-0x403）|
|**中断虚拟化**|Posted Interrupts、APIC Virtualization（APIC\-access、virtual EOI、TPR threshold）|AVIC \(Advanced Virtual Interrupt Controller\)、Virtual Interrupt \(VINTR\) 注入|
|**TLB 管理**|`INVEPT` \(EPT 上下文\)、`INVVPID` \(VPID 上下文\) 指令刷新 TLB|VMCB TLB Control 字段、`INVLPGA` 指令刷新 Guest TLB 条目|
|**Hypercall 机制**|`VMCALL` 指令（退出码 18）|`VMMCALL` 指令（退出码 0x0A1）|
|**Guest 状态恢复**|VMCS Guest\-State Area 自动恢复，含自然宽度字段|VMCB Save Area 恢复；`VMLOAD`/`VMSAVE` 指令辅助加载/保存额外状态|
|**加密虚拟化**|TDX \(Trust Domain Extensions\)，SEAMCALL/TDCALL 机制|SEV / SEV\-ES / SEV\-SNP，VMGEXIT \+ GHCB \(Guest\-Hypervisor Communication Block\)|
|**嵌套虚拟化**|VMCS Shadowing、Virtualize VMX（VMCS 12 → VMCS 02 映射）|Nested SVM（VMCB 嵌套，Host VMCB → Guest VMCB 链式）|
|**I/O 虚拟化**|I/O Bitmap（A/B）、I/O Instruction 退出（码 30），可按端口范围拦截|I/O Permission Bitmap、IOIO 退出（码 0x09B），按端口范围拦截|
|**MSR 虚拟化**|MSR Bitmap（read/write 低/高位图），RDMSR（码 31）/ WRMSR（码 32）|MSR Permission Bitmap，MSR 退出（码 0x09C）统一处理读写|

---

## 关键设计差异详解

**Intel VMX 设计哲学**

Intel 采用 **VMCS 字段驱动** 的设计，通过 Primary/Secondary/Tertiary Execution Controls 实现精细化的退出控制。每个控制位对应一类行为，VMM 可按需开启/关闭。EPT violation 退出不区分访问类型，VMM 需从 EXIT\_QUALIFICATION 字段解析具体是读/写/执行。

VMCS 的优势在于灵活性：VMM 可以非常精确地控制哪些操作触发 VMExit，哪些不触发。但 VMCS 的读写开销较大，因为需要使用 `VMREAD`/`VMWRITE` 指令逐个字段访问。

**AMD SVM 设计哲学**

AMD 采用 **VMCB 位图驱动** 的设计，通过控制区的 Intercept Bits 控制退出行为。NPT fault 按读/写/执行分别使用不同的退出码（0x400\-0x403），VMM 无需额外解析即可知道访问类型。

SVM 的优势在于简洁性：退出码直接编码了更多信息（如 NPT fault 的访问类型），减少了 VMM 的解析开销。VMCB 的整体读取比逐个 VMREAD 更高效，但灵活性略低。

---

## VMExit 处理流程对比

---

## 退出码编码方式对比

|特性|Intel VMX|AMD SVM|
|---|---|---|
|**基本退出码宽度**|16\-bit（bits 15:0）|64\-bit|
|**状态位**|Bit 27: enclave mode；Bit 31: VM\-entry failure|无独立状态位，退出码本身包含全部信息|
|**辅助信息字段**|`EXIT_QUALIFICATION`、`IDT_VECTORING_INFO`、`GUEST_LINEAR_ADDRESS` 等 VMCS 字段|`EXITINFO1`、`EXITINFO2`、`EXITINTINFO` 等 VMCB 控制区字段|
|**NPT/EPT 退出区分**|统一码 48（EPT violation），需从 `EXIT_QUALIFICATION` 解析读/写/执行|分别使用 0x400\(读\)、0x401\(写\)、0x402\(执行\)、0x403\(用户态执行\)|
|**CR 访问退出**|统一码 28（MOV to/from CR），需从 `EXIT_QUALIFICATION` 解析 CR 编号和读/写|每个 CR 独立退出码（0x000\-0x009），直接编码 CR 编号和读/写|
|**MSR 访问退出**|分两个退出码：31（RDMSR）、32（WRMSR）|统一码 0x09C，需从 `EXITINFO1` 判断读/写|

---

## 高级虚拟化特性对比

|特性|Intel VMX|AMD SVM|
|---|---|---|
|**中断虚拟化**|Posted Interrupts（将中断直接 posted 到 Guest，无需 VMExit）；APIC Virtualization（virtual EOI、TPR threshold、APIC\-access page）|AVIC（硬件虚拟化本地 APIC，直接交付虚拟中断，无需 VMExit）；VINTR 注入机制|
|**页表虚拟化**|EPT \+ VPID（Virtual Processor ID，避免 TLB flush）；EPT violation/misconfiguration 退出|NPT \+ ASID（Address Space ID，类似 VPID）；NPT fault 按类型分别退出|
|**嵌套虚拟化**|VMCS Shadowing（减少 nested VMExit 开销）；VMFUNC（Guest 可自主切换 EPTP）|Nested SVM（VMCB 嵌套链）；支持 L1 hypervisor 管理 L2 Guest|
|**加密虚拟化**|TDX \(Trust Domain Extensions\)：SEAM \(Secure Arbitration Mode\)、SEAMCALL/TDCALL、Secure EPT|SEV / SEV\-ES / SEV\-SNP：内存加密、VMGEXIT \+ GHCB 通信、Reverse Map Table \(RMP\)|
|**Preemption Timer**|VMX Preemption Timer（码 52），倒计时触发 VMExit，用于 Guest 时间片管理|无专用 Preemption Timer 退出码；使用 Host 计时器 \+ VINTR/INTR 实现类似功能|
|**I/O 虚拟化**|I/O Bitmap A/B（按端口范围拦截）；支持 APIC\-access page 虚拟化|I/O Permission Bitmap；支持 AVIC 对 LAPIC 的虚拟化|
|**VMFUNC**|VM Functions（码 59），允许 Guest 在不触发 VMExit 的情况下执行特定操作（如 EPTP 切换）|无直接等价物；可通过 VMMCALL 实现类似功能但需 VMExit|

---

**总结**

Intel VMX 和 AMD SVM 在 VMExit 机制上的核心差异在于设计哲学：

- **Intel** 采用 VMCS 字段驱动 \+ 统一退出码 \+ EXIT\_QUALIFICATION 解析的模式，灵活性强但解析开销略高

- **AMD** 采用 VMCB 位图驱动 \+ 细分退出码 \+ EXITINFO 直接编码的模式，解析开销低但灵活性略低

- 两者在内存虚拟化（EPT vs NPT）、中断虚拟化（Posted Interrupt vs AVIC）、加密虚拟化（TDX vs SEV\-SNP）上各有特色，但都遵循 x86 虚拟化的核心原则：trap\-and\-emulate \+ 硬件加速

- 随着虚拟化技术演进，两者都在不断减少 mandatory VMExit 的数量，通过硬件辅助（如 APIC virtualization、EPT/NPT、VPID/ASID）将更多操作从 trap\-and\-emulate 转变为 passthrough

---

## 参考文档

- Intel SDM Vol\. 3D, Appendix C — VMX 基本退出原因

- Intel SDM Vol\. 3C, Chapter 23\-34 — VMX 架构

- AMD APM Vol\. 2, Chapter 15 — 安全虚拟机（SVM）

- Linux 内核：arch/x86/include/uapi/asm/vmx\.h

- Linux 内核：arch/x86/include/uapi/asm/svm\.h

- Intel TDX 架构规范

- AMD SEV\-SNP 固件规范

> （注：部分内容可能由 AI 生成）
