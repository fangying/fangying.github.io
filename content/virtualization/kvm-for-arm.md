---
author: Yori Fang
title: KVM for ARM64
date: 2020-04-11 23:00
status: draft
slug: kvm-for-arm
tags: KVM, aarch64
---

这篇文章我们结合ARM虚拟化原理来梳理一下aarch64平台上KVM的具体实现。
对于熟悉x86上KVM内核模块的人来说，理清思路应该不难，
学习的时候重点对照一下x86来比较一下aarch64和x86两个平台上的异同点，
相得益彰进一步加深对系统虚拟机的理解。

## 0. ARM64硬件辅助虚拟化原理回顾

引入硬件辅助虚拟化之后ARM64的运行级别共有4个级别：

![ARM Exception Level](../images/aarch64_exception_levels_2.svg)

* 新增一个特权模式EL2，是hypversior的运行级别。
* EL0（Guest App）和EL1模式下执行一些特权操作会陷出到EL2模式进行模拟。
* ARM64也提供一些特定寄存器，guest可以直接访问这些寄存器从而加速虚拟机切换。
* 中断路由
* 新增HVC(Hypervisor Call)指令，从而可以让guest os必要时候可以主动进入EL2，
  执行特定的hypervisor接口调用。

在x86上GuestOS用户态和内核态运行在Non-Root模式的Ring0和Ring3模式下，
Host内核态和KVM运行在Root模式下。Non-Root模式和Root模式二者是正交的，
Guest执行敏感指令触发模式切换。
在ARM64平台上硬件辅助虚拟化引入了VHE[1](https://developer.arm.com/architectures/learn-the-architecture/armv8-a-virtualization/virtualization-host-extensions)(Virtualization Host Extensions)特性，
在ARM64下根据CPU是否支持VHE分两种情况：

* 1.如果支持VHE特性，那么HostOS内核和KVM都在EL2下执行，减少EL1和EL2模式之间的切换次数；
* 2.在不支持VHE的CPU上，KVM部分代码必须在EL2执行（例如捕获Guest异常退出），
  其他KVM代码和Host Linux内核都在EL1下执行，Hypervisor在进行资源管理和虚拟机调度的时候需要
  在EL1和EL2之间进Context Switch所以显然效率要低一些。


## 1.ARM64 KVM内核代码基本流程分析


### 1.1 KVM初始化关键
```c
arm_init
call kvm_init
    -> kvm_arch_init    // virt/kvm/arm/arm.c
        -> !is_hyp_mode_available    /* 判断是否支持SVC模式 */
        -> is_kernel_in_hyp_mode
        -> kvm_arch_requires_vhe     /* 判断 */
        foreach_online_cpu(cpu) {
            smp_call_function_single -> check_kvm_target_cpu

        }
        -> init_common_resources
        -> kvm_arm_init_sve
        -> init_hyp_mode
        -> init_subsystems
        -> 
```

### 1.2 Two Stage地址翻译

```
kvm_handle_guest_abort
  -> user_mem_abort
```

## 1. KVM for ARM

Supervisor calls (SVC)：请求特权操作或者从操作系统那边获取系统资源，使用svc指令。
指令格式是： SVC + NUMBER



## 参考文献

* 1.[https://developer.arm.com/architectures/learn-the-architecture/armv8-a-virtualization/virtualization-host-extensions]https://developer.arm.com/architectures/learn-the-architecture/armv8-a-virtualization/virtualization-host-extensions
* 1.[]