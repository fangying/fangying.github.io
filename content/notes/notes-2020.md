Title:  Notes 2020
Date: 2020-2-20 23:00
Modified: 2020-2-20 23:00
Tags: Notes
Slug: notes-220
Status: draft
Authors: Yori Fang
Summary: Notes

## 2020个人笔记

* start_apic_timer函数中对guest周期性timer的period设定有个最小值，不能小于这个值。
* 磁盘格式分为：厚制备卷，厚制备延迟置零卷，精简制备卷；裸设备映射分为：虚拟裸设备映射和物理裸设备映射。
* 存储QoS使用iotune，虚拟机存储热迁移，存储快照（离线创建，在线创建）和存储快照还原
* SPDK高性能磁盘技术

* virtio-net中断申请失败

vp_find_vqs -> vp_find_vqs_msix -> vp_request_msix_vectors -> pci_alloc_irq_vectors_affinity
-> _pci_enable_msix_range -> _pci_enable_msix -> msix_capability_init -> pci_msi_setup_msi_irqs
-> msi_domain_alloc_irqs -> _irq_dmain_alloc_irqs -> irq_domain_alloc_irqs_hierachchy

spi中断走GIC irq_domain
msi走ITS的irq_domain