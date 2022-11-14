Title: KVM中的HperV增强
Date: 2022-11-11 20:20
Tags: hyperv
Slug: hyperv-enlightenment


![hyperv-logo](https://www.pikpng.com/pngl/m/361-3613517_microsoft-hyper-v-logo-microsoft-hyper-v-logo.png)

本文不是为了分析HyperV，而是来分析一下当前KVM中对hyperv的一些增强的支持，这些HyperV增强能过对KVM场景下Windows虚拟机的性能有提升帮助。
在大多数场景下通过软件模拟的硬件性能会比较差，为此KVM实现了自己的半虚拟化接口。
Linux虚拟机通常能够在半虚拟化下工作的很好，因为内核本身会同步支持半虚拟化。
但通常来说为一些闭源的操作系统来实现这些就比较困难了，例如Microsoft Windows。
为此KVM在x86上为Windows Guest实现了HyperV启迪（HyperV Enlightenment），
这些特性会让Windows和HyperV的Guest认为他们运行在HyperV兼容的Hypervisor上，
这样Guest就会自动开启一些半虚拟化的性能优化。

### 设置HyperV启迪

默认情况下Qemu/KVM不会开启任何的HyperV启迪，qemu支持将单个的启迪特性通过cpu flags配置传入来尝试使能，例如：
```
qemu-system-x86_64 --enable-kvm --cpu host,hv_relaxed,hv_vpindex,hv_time, ...
```
libvirt的HyperV特性对应的XML配置为：
```
<features>
  <acpi/>
  <apic/>
  <pae/>
  <hyperv>
    <relaxed state='on'/>
    <vapic state='on'/>
    <spinlocks state='on' retries='8191'/>
    <vpindex state='on'/>
    <synic state='on'/>
    <stimer state='on'/>
    <reset state='on'/>
  </hyperv>
</features>
<clock offset='localtime'>
  <timer name='rtc' tickpolicy='catchup'/>
  <timer name='pit' tickpolicy='delay'/>
  <timer name='hpet' present='no'/>
  <timer name='hypervclock' present='yes'/>
</clock>
```
有时候特性之间可能会有依赖关系，qemu需要检测配置的合法性。
Qemu通过模拟CPUID 0x40000000..0x4000000A来对Guest呈现HyerV标志，
KVM将这些CPUID存放在0x40000100..0x40000101分枝上。

### HyperV启迪特性

#### hv-relaxed

这个特性的作用是告诉Guest OS去关闭watchdog超时，某些Windows版本依旧会有watchdog超时及时它看到了hypervisor呈现的这个CPU flag。

#### hv-vapic

用来提供半虚拟化的VP Assit Page MSR来让Guest的APIC更加高效。并且这个启迪特性允许半虚拟化（Exitless）的EOI处理。
（有点类似于让Windows也支持上APICv）

#### hv-spinlocks

半虚拟化的spinlocks。这个参数表示当发生了多少次spinlock争抢之后将这个信息告诉给hypervisor。
如果配置为0xffffffff则表示永远不通知hyervisor。

#### hv-vpindex

为Guest提供HV_X64_MSR_VP_INDEX (0x40000002) MSR来呈现Virtual processor index信息。
这个启迪需要和hv-synic，hv-timer还有其他需要让Guest知道自己的Virtual processor index的特性一起使用。
例如：当Guest要做HyperCall的时候就需要将VP Index作为参数传入。

#### hv-runtime

为Guest提供HV_X64_MSR_VP_RUNTIME (0x40000010) MSR，这个MSR以100ns为单位保存了virtual processor的运行时间。
它能够帮助Guest操作系统计算steal time（也就是vcpu被其他任务抢占的时间）。

#### hv-crash

为Guest提供HV_X64_MSR_CRASH_P0..HV_X64_MSR_CRASH_P5 (0x40000100..0x40000105) and HV_X64_MSR_CRASH_CTL (0x40000105) MSR两个MSR。
当Guest发生Crash的时候会去写这两个MSR，HV_X64_MSR_CRASH_P0..HV_X64_MSR_CRASH_P5 MSRs包含了额外的crash信息。
这些信息能狗通过QAPI打印到qemu的日志中。注意：与under geuine HyperV不同的是，write to HV_X64_MSR_CRASH_CTL会导致Guest关机。
这样会有效阻止Windows产生crash dump。

#### hv-time

为Guest使能两个专属的HyperV时钟源，基于MSR的HyperV时钟源（HV_X64_MSR_TIME_REF_COUNT, 0x40000020）和
可引用的TSC页（通HV_X64_MSR_REFERENCE_TSC, 0x40000021这个MSR来使能）。
每个时钟源都是per-guest的，Reference TSC page时钟源允许exit-less方式来读取time stamp。
使用这个启动特性可以显著地提升所有跟timestamp有关的操作。

#### hv-synic

为Guest使能合成的中断控制器（对LAPIC的扩展）。当这个特性被使能之后，能够为Guest提供额外的SynIC Msg和Events。
这是实现VMBus设备（qemu中暂时还不提供）的前提条件。并且，这个特性是实现HyperV synthetic timers所必须的。
通过HV_X64_MSR_SCONTROL..HV_X64_MSR_EOM (0x40000080..0x40000084) and HV_X64_MSR_SINT0..HV_X64_MSR_SINT15 (0x40000090..0x4000009F)
这两个定时器可以来控制SynIC。

依赖于：**hv-vpindex**

#### hv-stimer

使能HyperV合成定时器。对每个vCPU而言可以通过HV_X64_MSR_STIMER0_CONFIG..HV_X64_MSR_STIMER3_COUNT (0x400000B0..0x400000B7) MSR
来控制4个定时器。这些定时器可以工作在single-shot或者periodic模式。
必须知道的是，当这个启迪特性没有使能的时候，某些特定的Windows版本会转而使用HPET（甚至是RTC当HPET不可用的时候），
这会导致显著的CPU开销，即使vCPU在处于IDLE状态的时候。

依赖于： **hv-vpindex, hv-synic, hv-time**

#### hv-tlbflush

为Guest使能半虚拟化的TLB shutdown机制。在x86架构上，远程vCPU的TLB Flush过程要求发送IPI并等待其他CPU执行完TLB Flush。
在虚拟化场景下当IPI到达的时候，一些vCPU可能恰好没有被调度执行或者没有在请求Flush（又或者TLB Flush会被延迟到vCPU被调度进来执行）。
hv-tlbflush启迪实现了hypervisr层面对TLB Flush的优化。

依赖于：**hv-vpindex**

#### hv-ipi

使能半虚拟化的IPI发送机制。HvCallSendSyntheticClusterIpi hypercall会支持同时发送给大于64个vCPU的场景，
如果使用APIC来完成需要超过1次的访问，并且会退出到hypervisor中。

依赖于：**hv-vpindex**

#### hv-vendor-id=xxx

这个可以将HyperV的CPUID 0x40000000.EBX-EDX 标志改为定义的内容。这个参数不能超过12个子符。
根据spec约定，Guest不应当直接使用这个信息。
注意：hypervisor-vendor-id不是一个启迪特性，因此当没有其他启迪特性配置的时候它是不生效的。

#### hv-reset

为Guest提供HV_X64_MSR_RESET (0x40000003) MSR并且允许Guest写这个寄存器来触发重启，
即使这个特性使能了，这也不是一个推荐的Windows重启方式，所以它可能是用不到的。

#### hv-frequency

为Guest提供HV_X64_MSR_TSC_FREQUENCY (0x40000022) and HV_X64_MSR_APIC_FREQUENCY (0x40000023)两个MSR
来允许Guest获取它的TSC/APIC频率。

#### hv-reenlightenment

这特性适用于Nested嵌套虚拟化场景，目标是在KVM Guest上运行HyperV。
当特性使能之后会提供HV_X64_MSR_REENLIGHTENMENT_CONTROL (0x40000106), HV_X64_MSR_TSC_EMULATION_CONTROL (0x40000107)and HV_X64_MSR_TSC_EMULATION_STATUS (0x40000108) MSR这3个MSR并且允许Guest在TSC频率发生改变的时候收到通知，
并保持使用老的频率直到hyervisor可以切换到新的频率为止。
因此，和**hv-frequencies**特性一起使用的时候允许KVM上的运行的HyperV可以使用稳定的时钟源。

注意，KVM并没有全量支持re-enlightenment notifications，并且并不模拟TSC Access当虚拟机迁移之后。
因此‘tsc-frequency=’这个CPU配置项也必须要指定来保证热迁移成功。
目的端端CPU要么和源端保持一样的CPU频率或者支持TSC Scaling这个CPU特性。

#### hv-evmcs

这也为Nested嵌套虚拟化场景准备的，目标是在KVM上运行HyperV。
当被使能之后，它为Guest提供Version 1版本的 Enlightened VMCS。
这个特性在L0（KVM）和L1（HyperV）Hyervisor之间实现了半虚拟化这样可以帮助L2跑的更快。这个特性只在Intel平台上有用。

依赖于： **hv-vapic**

#### hv-stimer-direct

HyperV spec中允许两种模式的synthetic timer。
”classic“模式：超时Event被作为SynIC message来投递，
“direct”模式：Event被作为正常的interrupt来投递。
我们知道，在HyperV嵌套虚拟化场景下只能在direct模式下使用synthetic timers，
因此，**hv-stimer-direct**必须要使能。

依赖于：**hv-vpindex, hv-synic, hv-time, hv-stimer**

#### hv-avic (hv-apicv)

这个特性告诉Guest使用HyperV SynIC和基于硬件辅助虚拟化的APICv/AVIC。
通常HyperV SynIC会禁止这些硬件Feature并且建议Guest使用半虚拟化的AutoEOI feature。
注意：在旧的硬件（without APICv/AVIC support）上使能这个feature会对Guest性能有副作用。

#### hv-no-noarch-coresharing = on/off/auto

这个特性告诉Guest虚拟机的处理器不会share同一个物理core除非有被上报为相邻的SMT threads。
Windows和HyperV Guest需要知道这个信息来合适的消除SMT相关的CPU vulnerabilities。

当这个选择被设置为Auto时，Qemu只有在KVM报告non-architectural coresharing的时候才会使能它。
这意味着，超线程是不支持的或者完全被host禁用掉了。同时这个设置也会阻止往SMT配置不同的目的端做热迁移。
当这个选项设置为on，Qemu都会使能这个feature而不管host的配置如何。
为了保证Guest的安全性，只有在需要呈现正确的vCPU拓扑和vCPU绑定关系的时候才会用到。

#### hv-version-id-build, hv-version-id-major, hv-version-id-minor, hv-version-id-spack, hv-version-id-sbranch, hv-version-id-snumber

这些配置会改变HyperV版本标的CPUID 0x40000002.EAX-EDX信息，默认值是WS2016。
*   **hv-version-id-build** 设置‘Build Number’（32bits）
*   **hv-version-id-major** 设置‘Major Version’（16bits）
*   **hv-version-id-minor** 设置'Minor Version'（16bits）
*   **hv-version-id-spack** 设置‘Service Pack’ (32bits)
*   **hv-version-id-sbranch** 设置'Service Branch'（8bits）
*   **hv-version-id-snumber** 设置‘Service Number’ (24bits)

注意：**hv-version-id-x**不是启迪特性，因此在没有其他启迪特性配置的时候不会使能这个HyperV标志。

#### hv-syndbg

使能HyperV synthetic调试接口，这是一个由Windows Kernel Debugger用来发送数据包的通道，而不是通过串口/网络发送。
当被使能之后，这个启迪特性能提供额外的通信辅助给Guest：SynDbg消息。
这个新的通信通道被Windows kernel Debugger用来发送数据包而不是通过seiral/network，
相对其他通道而言有显著的性能提升。
这个启迪特性需要一个VMBus设备（-device vmbus-bridge,irq=15)。

依赖于：**hv-relaxed, hv_time, hv-vapic, hv-vpindex, hv-synic, hv-runtime, hv-stimer**


#### hv-emsr-bitmap

这个启迪特性适用于Nested场景，目标是运行在KVM上的HyperV Guest。
当该特性被使能后，它允许L0（KVM）和L1（HyperV）的hypervisor来合作以避免在发生vmexit的时候更新L2的MSR Bitmap。
而且这个特性在VMX（Intel）和SVM（AMD）上都支持，在VMX的实现上需要**hv-evmcs**特性被使能。

#### hv-xmm-input

HyperV spec允许我们通过XMM寄存器（XMM Fast Hypercall Input）来为某些hypercall传递参数。
当使用这个特性的时候，能够加速hypercall的处理流程因为KVM可以避免读Guest的内存。

#### hv-tlbflush-ext

允许扩展传递给HyperV TLB flush hypercalls（HvFlushVirtualAddressList/HvFlushVirtualAddressListEx）的GVA范围。

依赖于：**hv-tlbflush**

#### hv-tlbflush-direct

这个启迪特性适用于Nested嵌套虚拟化场景，目标是在KVM上运行的HyperV Guest。
当该特性被使能之后，允许L0（KVM）直接处理L2 Guest的TLB flush hypercalls而不需要发生VM-Exit到L1 hypervisor。
而且这个特性在VMX（Intel）和SVM（AMD）上都适用，VMX上的实现需要**hv-evmcs**特性被guest使能。

依赖于：**hv-vapic**

### 补充的features

#### hv-passthrough

在某些场景下（例如，开发过程中）需要使用Qemu来‘pass-through’模式，然后给Windows Guest所有KVM支持的启迪特性。
这个pass-through模式可以由配置‘hv-passthrough’ CPU flag。
注意：**hv-passthrough**选项仅仅使能了Qemu支持的启迪特性，并且将hv-spinlocks和hv-vendor-id从KVM拷贝到QEMU。
**hv-passthrough**会覆盖其他的hyperv配置项。

#### hv-enforce-cpuid

当HyperV的CPUID接口暴漏的是，KVM默认会允许Guest使用当前KVM所有可以支持的HyperV启迪特性，
而不管是否有些特性是不是没有被CPUID声明为Guest可见。
**hv-enforce-cpuid**特性改变了只允许Guest使用暴漏的HyperV启迪特性的默认行为。

### 有用的参考链接

Hyper-V顶级功能spec和其他信息：

* https://github.com/MicrosoftDocs/Virtualization-Documentation
* https://docs.microsoft.com/en-us/virtualization/hyper-v-on-windows/tlfs/tlfs


