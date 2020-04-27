Title:  Article Archive 2020 Reading Plan
Date: 2020-1-19 23:00
Modified: 2020-1-19 23:00
Tags: virtualization
Category: utils
Slug: reading2020
Status: published
Authors: Yori Fang
Summary: Reading Plan 2020

## 2020年学习计划

一转眼2019已经过了，制定的2019年阅读计划执行并不好。2019年上半年工作上太忙碌了，压得喘不过气来，所以阅读较少。
2019年下半年有执行一部分的阅读计划，但个人时间利用率并不高，欠了很多阅读债务。
作为一个在虚拟化领域工作快4年的人了，好多特性还没有系统的学习过，真的很汗颜。
2020年伊始告别了我的台式机入手了BP16寸，可以很方便的带到公众场合学习，所以2020年一定要恶补一下相关领域的知识，
不然出去混真的混不开。这里简单的制定一下2020年的学习计划，当然计划是活动的，所以随时更新。

* 学习dpdk和vhost-user方案的原理和代码；
* 学习openvswitch的原理和基本知识；
* 学习一些存储方面的知识，包括但不限于spdk等基本内容；
* 如果有时间要学习RSIC-V相关的知识，并补齐arm64的基本原理。
* 继续学习和使用Rust编程语言，Rust是系统编程和基础软件开发的不二之选。

2020好好学习，天天向上，加油！

## 阅读笔记摘要

### 1. [ACPI基础知识学习](https://uefi.org/sites/default/files/resources/ACPI_6_3_final_Jan30.pdf)

ACPI的学习资料最好的还是ACPI Spec文档，但阅读文档总是让人觉得卷帙浩繁。这次主要看了下ACPI Spec Chapter 4和ACPI
Chapter 5，这两个章节分别描述了ACPI 硬件接口和软件编程模型，让我们明白ACPI标准是如何在为OS体统更好的电源管理能力的同时
又为硬件厂商提供高度的灵活性。尤其是Chapter5，非常适合OS设计人员阅读，该章节介绍了ACPI System Description Table Achitecture，
方便我们理解ACPI里面的系统描述表的具体结构和作用。

总体上，ACPI固件定义两种数据结构：data tables 和 defination blocks，data tables里提供了给设备驱动程序的元数据，
defination blocks里面则包含了OS可以执行的Byte Code，defination blocks可以用一种叫做ASL语言来定义和描述。
ASL(ACPI Source language)是ACPI中用来描述硬件信息以及硬件操作给OSPM的表达式语言（相当于源代码），
通过ASL Compiler编译后生成了AML（ACPI Machine Language）格式，不同的AML模块组合在一起构成了ACPI Firmware，
是一种与OS平台无关的格式。详情可以看ACPI Spec，也可以看这里一个关于ASL的Tutorial，
可以快速了解ASL的基本语法:[https://acpica.org/sites/acpica/files/asl_tutorial_v20190625.pdf](https://acpica.org/sites/acpica/files/asl_tutorial_v20190625.pdf)
另外还有一个文章带你快速了解ACPI的架构：[https://acpica.org/sites/acpica/files/ACPI-Introduction.pdf](https://acpica.org/sites/acpica/files/ACPI-Introduction.pdft)


QEMU里面的i440fx主板对应的南桥芯片组是piix4，它包含了一个IDE Controller，一个USB Controller，一个PCI-ISA bridge和
RTC, PIT, PICs等设备。其中piix4里面包含了一个PM模块（本质是一个PCI设备），这个PM设备便是芯片组支持ACPI的接口。
同理，Q35主板上我们拥有一个叫做ich9的芯片组，它除了集成了AHCI controller，USB controller, network adapter, audio adapter, PCI-E and PCI bus LPC bus for the SuperIO devices等一堆设备之外，也具备一个Power Management模块，负责ACPI规范的支持。具体可以参考：https://wiki.qemu.org/Features/Q35。

x86平台上QEMU初始化主板的最后阶段，pc_machine_done -> acpi_setup 初始化x86的ACPI子系统。
arm64平台上virt主板最后初始化阶段，virt_machine_done -> virt_acpi_setup 初始化aarch64的ACPI子系统。
ACPI提供了CPU热插拔、内存热插拔以及pci/pcie 热插拔相关接口给操作系统。

### 2.0 QEMU FwCfg机制

QEMU使用fw_cfg设备向OS呈现系统固件(firmware)信息， 
其中主要包括：device bootorder，ACPI和SMBIOS tables，VM UUID，SMP/NUMA，
kenerl/initrd images for direct (Linux) kernel booting等（fw_cfg直接把硬件信息报告给OS）。

fw_cfg设备对外提供了3个关键寄存器用来完成设备操作，x86上使用PIO方式，arm上使用MMIO方式访问寄存器。
```
=== x86, x86_64 Register Locations ===
                               
Selector Register IOport: 0x510
Data Register IOport:     0x511
DMA Address IOport:       0x514
                              
=== ARM Register Locations ===
                                             
Selector Register address: Base + 8 (2 bytes)
Data Register address:     Base + 0 (8 bytes)
DMA Address address:       Base + 16 (8 bytes)
```

Select Register是Write Only的，通过写这个寄存器来选择要操作的Firmware。
Data Register是WR的，通过读Data Register内容可以将Select Register选中的固件内容按Byte读取出来。
DMA Address寄存器为fw_cfg提供了DMA方式访问固件的能力，相对于按Byte读取固件，可以提升固件读取的速率。

除此之外，fw_cfg还提供了ACPI接口给OS访问固件使用，其ACPI描述表信息中包含了固件目录信息（FW_CFG_FILE_DIR），
具体格式可以参考一下：[fw_cfg ACPI数据结构](https://richardweiyang.gitbooks.io/understanding_qemu/fw_cfg/01-spec.html)

除了能由ACPI，DTB进行fw_cfg实例化之外，也可以直接配置内核引导参数使用fw_cfg，
很显然这种方法是为了适用于QEMU直接引导内核的场景。

```
 * The fw_cfg device may be instantiated via either an ACPI node (on x86
 * and select subsets of aarch64), a Device Tree node (on arm), or using
 * a kernel module (or command line) parameter with the following syntax:
 *
 *      [qemu_fw_cfg.]ioport=<size>@<base>[:<ctrl_off>:<data_off>[:<dma_off>]]
 * or
 *      [qemu_fw_cfg.]mmio=<size>@<base>[:<ctrl_off>:<data_off>[:<dma_off>]]
 *
 * where:
 *      <size>     := size of ioport or mmio range
 *      <base>     := physical base address of ioport or mmio range
 *      <ctrl_off> := (optional) offset of control register
 *      <data_off> := (optional) offset of data register
 *      <dma_off> := (optional) offset of dma register
 *
 * e.g.:
 *      qemu_fw_cfg.ioport=12@0x510:0:1:4	(the default on x86)
 * or
 *      qemu_fw_cfg.mmio=16@0x9020000:8:0:16	(the default on arm)
 */

```

这里可以参考：

1. [https://wiki.osdev.org/QEMU_fw_cfg](https://wiki.osdev.org/QEMU_fw_cfg)
1. [https://git.qemu.org/?p=qemu.git;a=blob;f=docs/specs/fw_cfg.txt](https://git.qemu.org/?p=qemu.git;a=blob;f=docs/specs/fw_cfg.txt)
1. [https://github.com/torvalds/linux/blob/master/drivers/firmware/qemu_fw_cfg.c](https://github.com/torvalds/linux/blob/master/drivers/firmware/qemu_fw_cfg.c)
1. [https://www.kernel.org/doc/Documentation/devicetree/bindings/arm/fw-cfg.txt](https://www.kernel.org/doc/Documentation/devicetree/bindings/arm/fw-cfg.txt)

### 3. FDT、ACPI和SMBIOS的区别与联系

TODO

SMBIOS Mappings[https://gist.github.com/smoser/290f74c256c89cb3f3bd434a27b9f64c](https://gist.github.com/smoser/290f74c256c89cb3f3bd434a27b9f64c)

### 4. QEMU Direct Boot引导内核

TODO

glue load_elf elf_ops.h

### 5.内核大锁的讨论

https://kernelnewbies.org/BigKernelLock

### 6. PVH Boot引导方式

[https://patchwork.kernel.org/cover/10722233/](https://patchwork.kernel.org/cover/10722233/)
PVH特性的目的是为了让QEMU支持内核的快速启动，可以跳过固件直接引导一个未经压缩的内核，
听上去是不是有点酷。在KVM之前，Xen上就已经有支持Linux和FreeBSD的PVH guests和ABI。



1. [For a Microkernel, a BIG Lock is fine !](https://ts.data61.csiro.au/publications/nicta_slides/8768.pdf)

## 阅读清单

1. [perf event原理和使用方法](https://blog.csdn.net/pwl999/article/details/80514271)
1. [perf 原理和代码分析](https://blog.csdn.net/pwl999/article/list/1)
