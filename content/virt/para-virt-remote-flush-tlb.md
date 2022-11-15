Title: 半虚拟化Remote TLB Flush
Date: 2022-11-13 20:20
Tags: pv-tlb-flush
Slug: para-virt-remote-tlb-flush

原文：[https://lwn.net/Articles/500188/](https://lwn.net/Articles/500188/)

远程的tlb flush api在BareMetal场景下是采用的一种busy wait的方式，在这种场景下是OK的。
但是在Guest内部如果也采用这种方式，那么目的端的vCPU很可能被被抢占（不在调度）或者处于block状态。
在这种场景下，发起Remote TLB flush的vCPU一方就很可能会busy-waitting很长一段时间。

这种现象很容易在Gang Scheduling测试中发现到，而且这个问题的一种处理方式就是使用半虚拟化的
`flush_tlb_others_ipi`。这组patch实现了半虚拟化的tlb flush方案来确保不会等待处于sleeping状态的vCPU。
并且所有处于sleeping状态的vCPU在进入Guest模式时候会立刻flush自己的TLB。
这个Idea在这里被讨论过：

[https://lkml.org/lkml/2012/2/20/157](https://lkml.org/lkml/2012/2/20/157)

而且这组patch引入了不止一处对`get_user_pages_fast(gup_fast)`无锁页遍历的依赖关系。
`gup_fast`关闭了中断并且假设这段时间这个Page不会被释放掉。
这在`flush_tlb_others_ipi`中是没问题的，因为它会等待所有的IPI都被处理掉然后结果返回。
在新的方案中，由于不再等待所有睡眠的vCPU，这个假设就不再合理了。
因此`HAVE_RCU_TABLE_FREE`被引入来释放这些页。
这会确保所有的cpu会在释放页之前，至少调用一次`smp_callback`过程。

这组patch依赖于ticketlocks[1] and KVM Paravirt Spinlock patches[2]


Nikunj A. Dadhania (6):
      KVM Guest: Add VCPU running/pre-empted state for guest
      KVM-HV: Add VCPU running/pre-empted state for guest
      KVM: Add paravirt kvm_flush_tlb_others
      KVM: export kvm_kick_vcpu for pv_flush
      KVM: Introduce PV kick in flush tlb
      Flush page-table pages before freeing them

Peter Zijlstra (1):
      kvm,x86: RCU based table free