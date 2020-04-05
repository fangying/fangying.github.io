Title: Discuss On X86 APIC Virtualization
Date: 2019-10-20 23:00
Modified: 2019-10-20 23:00
Tags: apicv
Slug: x86_apicv
Authors: Yori Fang
Summary: X86 APICv
Status: published

关于x86的LAPIC虚拟化，这里再记录讨论讨论。

1. APIC-Access Page 和 Virtual-APIC Page的区别是啥？
1. VT-x Posted Interrupt的实现原理是什么？（可以对比一下VT-d Posted Interrupt）

## 0. APIC Virtualizaiton 原理

在看LAPIC虚拟化章节(Intel SDM Chatper 29)的时候，发现和LAPIC虚拟化相关的有2个重要的Physcal Page，
即APIC-Access Page和Virtual-APIC Page，那么这两个物理页在vCPU APIC虚拟化中的作用是什么？

在回答这个问题之前，需要先了解一下APIC的基本知识。

在x86上，APIC寄存器在系统初始化的时候默认被映射到在0xFEE00000H为起始位置的一个4K物理页上。
在MP系统上，APIC寄存器被映射到物理地址空间上，软件可以选择改变APIC寄存器的页基地址，
每个逻辑CPU可以选择将自己的APIC寄存器reload到自己设定的地方。

```
The Pentium 4, Intel Xeon, and P6 family processors permit the starting address of the APIC registers 
to be relocated from FEE00000H to another physical address by modifying the value in the 24-bit base address
field of the IA32_APIC_BASE MSR. This extension of the APIC architecture is provided to help resolve conflicts
with memory maps of existing systems and to allow individual processors in an MP system to map their APIC
registers to different locations in physical memory.
```

在X86上软件程序可以通过**3种方式**访问逻辑CPU的LAPIC寄存器：

1. 如果APIC工作在xAPIC模式下，可以通过MMIO方式访问基地的为IA32_APIC_BASE MSR的一个4-KByte物理页方式访问。
1. 如果APIC工作在x2APIC模式下，可以通过使用RDMSR和WRMSR指令访问APIC寄存器。
1. 在64-bit模式下，可以通过使用MOV CR8指令访问APIC的TPR寄存器（Task Priority Register）。

那么在虚拟化场景下我们也要支持上面的3种访问模式，为此VMCS提供了若干个APIC虚拟化相关的控制域：

1. **APIC-Access address**：如果"virtualize APIC accessess"控制域为1，
那么VMCS会使用一个4-KByte的物理页(APIC-access page)来辅助APIC虚拟化，
当vCPU访问这个page的时候会产生VM exits。
注意：只有处理器支持设置"virtualize APIC accessess"特性时APIC-access page才会存在。
1. **Virtual-APIC address**：处理器使用这个物理虚拟化*某些*APIC寄存器和管理虚拟中断。virtual-APIC page可以通过下面的操作访问:
   - MOV CR8指令；
   - 访问APIC-access页，前提是"virtualize APIC accesses"是enable的；
   - 使用RDMSR和WRMSR指令，前提是ECX范围是800H-8FFH（表示APIC MSR范围）并且"virtualize x2APIC mode"模式是enable的。
   注意：只有"use TPR shadow"使能的条件下才会存在"virtual-APIC page", "virtual-APIC page"存在的唯一目的是为了对TPR寄存器进行shadow。
1. **TPR Threshold**： 这个域的Bits 3:0 定义了VTPR的Bits 7:4 fall上限。
如果"virtual-interrupt delivery"为0，那么VM exit（例如：mov CR8）会减小TPR threshold的值。
只有处理器使能了"use TPR shadow"，TPR Threshold才会存在。
1. **EOI-exit bitmap**：这个域用来控制哪些操作写APIC EOI寄存器后触发VM exits：
    - EOI_EXIT0：包含bit掩码控制vector0(bit0)-vector63(bit63)的EOI；
    - EOI_EXIT1：包含bit掩码控制vector64(bit64)-vector127(bit127)的EOI；
    - EOI-EXIT2: 包含bit掩码控制vector128(bit128)-vector191(bit191)的EOI；
    - EOI-EXIT3: 包含bit掩码控制vector192(bit192)-vector255(bit255)的EOI。
1. **Posted-interrupt notification vector**: 对于支持VT-x Posted Interrupt的处理器，
该域的lower 8bit包含了一个用来通知vCPU中断已投递的中断向量。
1. **Posted-interrupt descriptor address**: 对于支持VT-x Posted Interrupt的处理器，
该域包含了vCPU的Posted Interrupt Descriptor数据结构的物理地址。


看到这里就开始觉得：APIC的虚拟化也是挺复杂的，VMCS提供了非常细粒度的控制策略来辅助APIC的虚拟化工作。

SDM Chapter 29将APIC虚拟化的要点总结了一下：

1. **virtual-interrupt delivery**: VMM直接写Virtual-APIC Page的VIRR寄存器就能给vCPU投递中断。
1. **use TPR shadow**：主要是shadow TPR寄存器，当guest执行mov CR8给TPR赋值时，TPR寄存器的值会自动映射到Virtual-APIC Page上。
1. **virtualize APIC accessess**：vCPU可以通过MMIO方式访问APIC寄存器；
1. **virtualize x2APIC mode**：使能基于MSR方式对APIC寄存器的访问（x2API虚拟化）；
1. **APIC register virtualization**： 控制APIC寄存器的访问方式（MMIO/MSR BASED）将MMIO写APIC-access page操作重定向到virtual-APIC page上。
1. **Process posted interrupts**：VT-x Posted Interrupt 特性，配置Posted Interrupt Descriptor Adress和 Notification Vector，
当目标处理器接受到中断后，硬件自动将中断请求信息copy到virtual-APIC page上。

因此，我们可以看出：
**APIC-Access Page的作用主要是让vCPU能过通过MMIO方式访问到特定的APIC寄存器，
Virtual-APIC Page的作用是虚拟中断投递，shadow TPR和部分关键APIC寄存器的虚拟化（VTPR,VPPR,VEOI,VISR,VIRR,VICR）。**
当使能了"APIC-register virtualization"时，Reads form the APIC-access Page时将会被虚拟化，
并且当vCPU访问APIC-access Page的时候硬件会自动返回virtual-APIC Page对应offset处的内容（相当于重定向）。
对于APIC-write操作，除了写APIC的一些关键寄存器（例如：vTPR，vEOI，vICR等）不需要VM exit（有硬件辅助加速），
其他的大部分page offset写操作都会触发 APIC-write VM exits然后由VMM进行模拟（具体细节参考：SMD Chapter 29.4.2和29.4.3）。

**注意**：当Guest直接通过GPA方式访问APIC-access Page的时候必然会触发APIC-access exit。**尼玛，真的被搞晕了！！！**

```
1. Even when addresses are translated using EPT (see Section 28.2), the determination of whether an APIC-access VM exit occurs depends on an access’s physical address, not its guest-physical address
```


## 1. APIC虚拟化代码分析
The secret is APIC-access page and virtual-APIC page.
```c
        if (cpu_has_vmx_tpr_shadow() && !init_event) {
                vmcs_write64(VIRTUAL_APIC_PAGE_ADDR, 0);
                if (cpu_need_tpr_shadow(vcpu))
                        vmcs_write64(VIRTUAL_APIC_PAGE_ADDR,
                                ¦   ¦__pa(vcpu->arch.apic->regs));
                vmcs_write32(TPR_THRESHOLD, 0);
        }

```
Here is a reply I received from a colleague:

It is correct that the only function of the virtual-APIC page is to shadow the TPR.

There are three address of interest, all of which are physical addresses (meaning that they are not subject to any kind of translation).

1. IA32_APIC_BASE. This address is contained in an MSR. This is the address at which that actual hardware APIC is mapped. Accesses to this physical address (e.g., if this physical address is the output of paging) will access the memory-mapped registers of the actual hardware APIC. It is expected that a VMM will not map this physical address into the address space of any guest. That means the following: (1) if EPT is in use, no EPT PTE should contain this address; (2) if EPT is not in use, no ordinary PTE should have this address while a guest is running. (See #2 below for an exception.) It is also expected that the VMM will not allow any guest software to access the IA32_APIC_BASE MSR.

2. APIC-access address. This is the address of the APIC-access page and is programmed via a field in the VMCS. The CPU will treat specially guest accesses to physical addresses on this page. For most cases, such accesses cause VM exits. The only exceptions are reads and writes of offset 080H (TPR) on the page. See item #3 for how they are treated. The relevant accesses are defined as follows: (1) if EPT is in use, accesses that use an EPT PTE that contains the APIC-address; (2) if EPT is not in use, accesses that use an ordinary PTE that contains the APIC-access address. NOTE: the APIC-access address take priority over the address in IA32_APIC_BASE. If both have the same value and are programmed into a PTE, accesses through that PTE are virtualized (cause VM exits in most cases) and do not access the actual hardware APIC. This is an exception to statements in #1 (that the address in IA32_APIC_BASE not appear in PTEs while a guest is running).

3. Virtual-APIC address. This is the address of the virtual-APIC page and is programmed via a field in the VMCS. The CPU uses this field in three situations: (1) MOV to/from CR8; (2) RDMSR/WRMSR to MSR 808H; and (3) for accesses to offset 080H (TPR) on the APIC-access page. If the CPU detects an access to offset 080H on the APIC-access page (see above), it will redirect the access to offset 080H on the virtual-APIC page. It is expected that a VMM will not map this physical address into the address space of any guest, except guests for which the virtual-APIC address is identical to the APIC-access address.

The APIC-access address and the virtual-APIC address were made distinct from each other to support guests with multiple virtual processors. In such a situation, the virtual processors could all be supported with a single hierarchy of EPT paging structures. This hierarchy would include an EPT PTE with an address that is the APIC-access address for all the virtual processors. That is, the VMCS of each virtual processor would include this address as its APIC-access address. But these VMCS's would each have its own virtual-APIC address.

In this way, the virtual processors of a single guest can be supported by a single hierarchy of EPT paging structures while each having its own virtual APIC.

David Ott


## 3. Refs

https://www.linux-kvm.org/images/7/70/2012-forum-nakajima_apicv.pdf

https://software.intel.com/en-us/forums/virtualization-software-development/topic/284386

https://www.spinics.net/lists/kvm/msg85565.html

https://cloud.tencent.com/developer/column/75113

https://blog.csdn.net/wanthelping/article/details/47069077
