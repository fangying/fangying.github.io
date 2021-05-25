Title:  Virtio Spec Overview
Date: 2019-9-13 23:00
Modified: 2019-9-13 23:00
Tags: virtualization,virtio,virtio-net,virtio-scsi,virtio-blk,virtqueue
Slug: virtio-overview
Status: published
Authors: Yori Fang
Summary: virtio overview

## 摘要

半虚拟化设备(Virtio Device)在当前云计算虚拟化场景下已经得到了非常广泛的应用，
并且现在也有越来越多的物理设备也开始支持Virtio协议，即所谓的`Virtio Offload`，
通过将virtio协议卸载到硬件上（例如virtio-net网卡卸载，virtio-scsi卸载）让物理机和虚拟机都能够获得加速体验。
本文中我们来重点了解一下virtio技术中的一些关键点，方便我们加深对半虚拟化的理解。
本文适合对IO虚拟化有一定了解的人群阅读，本文的目的是对想要了解virtio内部机制的读者提供帮助。

在开始了解virtio之前，我们先思考一下几个相关问题：

* virtio设备有哪几种呈现方式?
* virtio-pci设备的配置空间都有哪些内容？
* virtio前端和后端基于共享内存机制进行通信，它是凭什么可以做到无锁的？
* virtio机制中有那几个关键的数据结构？virtio配置接口存放在哪里？virtio是如何工作的？
* virtio前后端是如何进行通信的？irqfd和ioeventfd是什么回事儿？在virtio前后端通信中是怎么用到的？
* virtio设备支持MSIx，在qemu/kvm中具体是怎么实现对MSIx的模拟呢？
* virtio modern相对于virtio legay多了哪些新特性？

## 0. 简单了解一下Virtio Spec协议

virtio协议标准最早由IBM提出，virtio作为一套标准协议现在有专门的技术委员会进行管理，
具体的标准可以访问[`virtio`官网](http://docs.oasis-open.org/virtio/virtio/v1.0/virtio-v1.0.html)，
开发者可以向技术委员会提供新的virtio设备提案（`RFC`），经过委员会通过后可以增加新的virtio设备类型。

组成一个virtio设备的四要素包括：
**设备状态域，`feature bits`，设备配置空间，一个或者多个`virtqueue`**。
其中设备状态域包含6种状态：

* ACKNOWLEDGE（1）：GuestOS发现了这个设备，并且认为这是一个有效的virtio设备；
* DRIVER (2) : GuestOS知道该如何驱动这个设备；
* FAILED (128) : GuestOS无法正常驱动这个设备，Something is wrong；
* FEATURES_OK (8) : GuestOS认识所有的feature，并且feature协商一完成；
* DRIVER_OK (4) : 驱动加载完成，设备可以投入使用了；
* DEVICE_NEEDS_RESET (64) ：设备触发了错误，需要重置才能继续工作。

`feature bits`用来标志设备支持那个特性，其中bit0-bit23是特定设备可以使用的`feature bits`，
bit24-bit37预给队列和feature协商机制，bit38以上保留给未来其他用途。
例如：对于virtio-net设备而言，feature bit0表示网卡设备支持checksum校验。
`VIRTIO_F_VERSION_1`这个feature bit用来表示设备是否支持virtio 1.0 spec标准。
 
 在virtio协议中，所有的设备都使用virtqueue来进行数据的传输。
 **每个设备可以有0个或者多个virtqueue，每个virtqueue占用2个或者更多个4K的物理页**。
 virtqueue有`Split Virtqueues`和`Packed Virtqueues`两种模式，
 在`Split virtqueues`模式下virtqueue被分成若干个部分，
 每个部分都是前端驱动或者后端单向可写的（不能两端同时写）。
 每个virtqueue都有一个16bit的queue size参数，表示队列的总长度。
 每个virtqueue由3个部分组成：
 
```
	+-------------------+--------------------------------+-----------------------+
	| Descriptor Table  |   Available Ring  (padding)    |       Used Ring       |
	+-------------------+--------------------------------+-----------------------+
```
 
 * Descriptor Table：存放IO传输请求信息；
 * Available Ring：记录了Descriptor Table表中的I/O请求下发信息，前端Driver可写后端只读；
 * Used Ring：记录Descriptor Table表中已被提交到硬件的信息，前端Driver只读后端可写。
 
整个virtio协议中设备IO请求的工作机制可以简单地概括为：

1.  前端驱动将IO请求放到`Descriptor Table`中，然后将索引更新到`Available Ring`中，最后kick后端去取数据；
1.  后端取出IO请求进行处理，然后将结果刷新到`Descriptor Table`中再更新`Using Ring`，然后发送中断notify前端。

从virtio协议可以了解到**virtio设备支持3种设备呈现模式**：

* Virtio Over PCI BUS，依旧遵循PCI规范，挂在到PCI总线上，作为virtio-pci设备呈现；
* Virtio Over MMIO，部分不支持PCI协议的虚拟化平台可以使用这种工作模式，直接挂载到系统总线上；
* Virtio Over Channel I/O：主要用在s390平台上，virtio-ccw使用这种基于channel I/O的机制。

其中，Virtio Over PCI BUS的使用比较广泛，作为PCI设备需按照规范要通过PCI配置空间来向操作系统报告设备支持的特性集合，
这样操作系统才知道这是一个什么类型的virtio设备，并调用对应的前端驱动和这个设备进行握手，进而将设备驱动起来。
QEMU会给virtio设备模拟PCI配置空间，对于virtio设备来说PCI Vendor ID固定为0x1AF4，
PCI Device ID 为 0x1000到0x107F之间的是virtio设备。
同时，在不支持PCI协议的虚拟化平台上，virtio设备也可以直接通过MMIO进行呈现，
virtio-spec 4.2 [Virtio Over MMIO](https://docs.oasis-open.org/virtio/virtio/v1.1/csprd01/virtio-v1.1-csprd01.html#x1-1440002)有针对virtio-mmio设备呈现方式的详细描述，mmio相关信息可以直接通过内核参数报告给Linux操作系统。
本文主要基于virtio-pci展开讨论。

前面提到virtio设备有`feature bits`，`virtqueue`等四要素，那么在virtio-pci模式下是如何呈现的呢？
从virtio spec来看，老的virtio协议和新的virtio协议在这一块有很大改动。
virtio legacy（virtio 0.95）协议规定，对应的配置数据结构（virtio common configuration structure）
应该存放在设备的BAR0里面，我们称之为`virtio legay interface`，其结构如下：

``` 
                       virtio legacy ==> Mapped into PCI BAR0 
	+------------------------------------------------------------------+ 
	|                    Host Feature Bits[0:31]                       | 
	+------------------------------------------------------------------+
	|                    Guest Feature Bits[0:31]                      |
	+------------------------------------------------------------------+
	|                    Virtqueue Address PFN                         |
	+---------------------------------+--------------------------------+
	|           Queue Select          |           Queue Size           |
	+----------------+----------------+--------------------------------+
	|   ISR Status   | Device Stat    |           Queue Notify         |
	+----------------+----------------+--------------------------------+
	|       MSI Config Vector         |         MSI Queue Vector       |
	+---------------------------------+--------------------------------+
```

对于新的`virtio modern`，协议将配置结构划分为5种类型：
```
/* Common configuration */ 
#define VIRTIO_PCI_CAP_COMMON_CFG        1 
/* Notifications */ 
#define VIRTIO_PCI_CAP_NOTIFY_CFG        2
/* ISR Status */ 
#define VIRTIO_PCI_CAP_ISR_CFG           3 
/* Device specific configuration */ 
#define VIRTIO_PCI_CAP_DEVICE_CFG        4 
/* PCI configuration access */ 
#define VIRTIO_PCI_CAP_PCI_CFG           5 
```
以上的每种配置结构是直接映射到virtio设备的BAR空间内，那么如何指定每种配置结构的位置呢？
答案是通过`PCI Capability list`方式去指定，这和物理PCI设备是一样的，体现了virtio-pci的协议兼容性。
```
struct virtio_pci_cap { 
        u8 cap_vndr;    /* Generic PCI field: PCI_CAP_ID_VNDR */ 
        u8 cap_next;    /* Generic PCI field: next ptr. */ 
        u8 cap_len;     /* Generic PCI field: capability length */ 
        u8 cfg_type;    /* Identifies the structure. */ 
        u8 bar;         /* Where to find it. */ 
        u8 padding[3];  /* Pad to full dword. */ 
        le32 offset;    /* Offset within bar. */ 
        le32 length;    /* Length of the structure, in bytes. */ 
};
```
只是略微不同的是，virtio-pci的Capability有一个统一的结构，
其中`cfg_type`表示Cap的类型，`bar`表示这个配置结构被映射到的BAR空间号。
这样每个配置结构都可以通过BAR空间直接访问，或者通过PCI配置空间的`VIRTIO_PCI_CAP_PCI_CFG`域进行访问。
每个Cap的具体结构定义可以参考virtio spec 4.1.4.3小节。
为了方便理解这里以一张virtio-net网卡为例：
```
[root@localhost ~]# lspci -vvvs 04:00.0
04:00.0 Ethernet controller: Red Hat, Inc. Virtio network device (rev 01)
	Subsystem: Red Hat, Inc. Device 1100
	Physical Slot: 0-1
	Control: I/O+ Mem+ BusMaster+ SpecCycle- MemWINV- VGASnoop- ParErr- Stepping- SERR+ FastB2B- DisINTx+
	Status: Cap+ 66MHz- UDF- FastB2B- ParErr- DEVSEL=fast >TAbort- <TAbort- <MAbort- >SERR- <PERR- INTx-
	Latency: 0
	Interrupt: pin A routed to IRQ 21
	Region 1: Memory at fe840000 (32-bit, non-prefetchable) [size=4K]
	Region 4: Memory at fa600000 (64-bit, prefetchable) [size=16K]
	Expansion ROM at fe800000 [disabled] [size=256K]
	Capabilities: [dc] MSI-X: Enable+ Count=10 Masked-
		Vector table: BAR=1 offset=00000000
		PBA: BAR=1 offset=00000800
	Capabilities: [c8] Vendor Specific Information: VirtIO: <unknown>
		BAR=0 offset=00000000 size=00000000
	Capabilities: [b4] Vendor Specific Information: VirtIO: Notify
		BAR=4 offset=00003000 size=00001000 multiplier=00000004
	Capabilities: [a4] Vendor Specific Information: VirtIO: DeviceCfg
		BAR=4 offset=00002000 size=00001000
	Capabilities: [94] Vendor Specific Information: VirtIO: ISR
		BAR=4 offset=00001000 size=00001000
	Capabilities: [84] Vendor Specific Information: VirtIO: CommonCfg
		BAR=4 offset=00000000 size=00001000
```
MSI-X的vector table和PBA放到了BAR1里面，
BAR4里放了common cfg，设备isr状态信息，device cfg，driver notify信息等。

# 1. 前后端数据共享

传统的纯模拟设备在工作的时候，会触发频繁的陷入陷出，
而且IO请求的内容要进行多次拷贝传递，严重影响了设备的IO性能。
virtio为了提升设备的IO性能，采用了共享内存机制，
***前端驱动会提前申请好一段物理地址空间用来存放IO请求，然后将这段地址的GPA告诉QEMU***。
前端驱动在下发IO请求后，QEMU可以直接从共享内存中取出请求，然后将完成后的结果又直接写到虚拟机对应地址上去。
**整个过程中可以做到直投直取，省去了不必要的数据拷贝开销**。

**`Virtqueue`是整个virtio方案的灵魂所在**。每个virtqueue都包含3张表，
`Descriptor Table`存放了IO请求描述符，`Available Ring`记录了当前哪些描述符是可用的，
`Used Ring`记录了哪些描述符已经被后端使用了。

```
                          +------------------------------------+
                          |       virtio  guest driver         |
                          +-----------------+------------------+
                            /               |              ^
                           /                |               \
                          put            update             get
                         /                  |                 \
                        V                   V                  \
                   +----------+      +------------+        +----------+
                   |          |      |            |        |          |
                   +----------+      +------------+        +----------+
                   | available|      | descriptor |        |   used   |
                   |   ring   |      |   table    |        |   ring   |
                   +----------+      +------------+        +----------+
                   |          |      |            |        |          |
                   +----------+      +------------+        +----------+
                   |          |      |            |        |          |
                   +----------+      +------------+        +----------+
                        \                   ^                   ^
                         \                  |                  /
                         get             update              put
                           \                |                /
                            V               |               /
                           +----------------+-------------------+
                           |	   virtio host backend          |
                           +------------------------------------+
```
`Desriptor Table`中存放的是一个一个的`virtq_desc`元素，每个`virq_desc`元素占用16个字节。

```
+-----------------------------------------------------------+
|                        addr/gpa [0:63]                    |
+-------------------------+-----------------+---------------+
|         len [0:31]      |  flags [0:15]   |  next [0:15]  |
+-------------------------+-----------------+---------------+
```
其中，addr占用64bit存放了单个IO请求的GPA地址信息，例如addr可能表示某个DMA buffer的起始地址。
len占用32bit表示IO请求的长度，flags的取值有3种，
`VIRTQ_DESC_F_NEXT`表示这个IO请求和下一个`virtq_desc`描述的是连续的，
`IRTQ_DESC_F_WRITE`表示这段buffer是write only的，
`VIRTQ_DESC_F_INDIRECT`表示这段buffer里面放的内容是另外一组buffer的`virtq_desc`（相当于重定向），
next是指向下一个`virtq_desc`的索引号（前提是`VIRTQ_DESC_F_NEXT` & flags）。

`Available Ring`是前端驱动用来告知后端那些IO buffer是的请求需要处理，每个Ring中包含一个`virtq_avail`占用8个字节。
其中，flags取值为`VIRTQ_AVAIL_F_NO_INTERRUPT`时表示前端驱动告诉后端：
“当你消耗完一个IO buffer的时候，不要立刻给我发中断”（防止中断过多影响效率）。
idx表示下次前端驱动要放置`Descriptor Entry`的地方。

```
+--------------+-------------+--------------+---------------------+
| flags [0:15] |  idx [0:15] |  ring[0:15]  |  used_event [0:15]  |
+--------------+-------------+--------------+---------------------+
```
Used Ring结构稍微不一样，flags的值如果为`VIRTIO_F_EVENT_IDX`并且前后端协商`VIRTIO_F_EVENT_IDX` feature成功,
那么Guest会将used ring index放在available ring的末尾，告诉后端说：
“Hi 小老弟，当你处理完这个请求的时候，给我发个中断通知我一下”，
同时host也会将avail_event index放到used ring的末尾，告诉guest说：
“Hi 老兄，记得把这个idx的请求kick给我哈”。
`VIRTIO_F_EVENT_IDX`对virtio通知/中断有一定的优化，在某些场景下能够提升IO性能。

```c
/* The Guest publishes the used index for which it expects an interrupt
 * at the end of the avail ring. Host should ignore the avail->flags field. */
/* The Host publishes the avail index for which it expects a kick
 * at the end of the used ring. Guest should ignore the used->flags field. */
 
struct virtq_used { 
#define VIRTQ_USED_F_NO_NOTIFY  1 
        le16 flags; 
        le16 idx; 
        struct virtq_used_elem ring[ /* Queue Size */]; 
        le16 avail_event; /* Only if VIRTIO_F_EVENT_IDX */ 
}; 
 
/* le32 is used here for ids for padding reasons. */ 
struct virtq_used_elem { 
        /* Index of start of used descriptor chain. */ 
        le32 id; 
        /* Total length of the descriptor chain which was used (written to) */ 
        le32 len; 
};
```

原理就到这里，后面会以virtio网卡为例进行详细流程说明。
    
## 2. 前后端通信机制（irqfd 与 ioeventfd）

共享内存方式解决了传统设备IO过程中内存拷贝带来的性能损耗问题，除此之外前端驱动和后端驱动的通信问题也是有可以改进的地方。
Virtio前后端通信概括起来只有两个方向，即GuestOS通知QEMU和QEMU通知GuestOS。
当前端驱动准备好IO buffer之后，需要通知后端（QEMU），告诉后端：
“小老弟，我有一波IO请求已经准备好了，你帮我处理一下”。
前端通知出去后，就可以等待IO结果了（操作系统可以进行一次调度），这时候vCPU可以去干点其他的事情。
后端收到消息后开始处理IO请求，当IO请求处理完成之后，后端就通过中断机制通知GuestOS：
“老哥，你的IO给你处理好了，你来取一下”。
前后端通信机制如下图所示：

```
             +-------------+                +-------------+
             |             |                |             |
             |             |                |             |
             |   GuestOS   |                |     QEMU    |
             |             |                |             |
             |             |                |             |
             +---+---------+                +----+--------+
                 |     ^                         |    ^
                 |     |                         |    |
             +---|-----|-------------------------|----|---+
             |   |     |                irqfd    |    |   |
             |   |     +-------------------------+    |   |
             |   |  ioeventfd                         |   |
             |   +------------------------------------+   |
             |                   KVM                      |
             +--------------------------------------------+

```

前端驱动通知后端比较简单，QEMU设置一段特定的MMIO地址空间，前端驱动访问这段MMIO触发VMExit，
退出到KVM后利用`ioeventfd`机制通知到用户态的QEMU，QEMU主循环（main_loop poll）
检测到ioeventfd事件后调用callback进行处理。

```c
前端驱动通知后端：
内核流程mark一下，PCI设备驱动流程这个后面可以学习一下，先扫描PCI bus发现是virtio设备再扫描virtio-bus。
worker_thread --> process_one_work --> pciehp_power_thread --> pciehp_enable_slot --> 
pciehp_configure_device --> pci_bus_add_devices --> pci_bus_add_device --> device_attach --> 
__device_attach --> bus_for_each_drv --> __device_attach_driver --> driver_probe_device --> 
pci_device_probe --> local_pci_probe --> virtio_pci_probe --> register_virtio_device --> 
device_register --> device_add --> bus_probe_device --> device_initial_probe 
--> __device_attach --> bus_for_each_drv --> __device_attach_driver -->
driver_probe_device --> virtio_dev_probe --> virtnet_probe (网卡设备驱动加载的入口)

static int virtnet_probe(struct virtio_device *vdev) 
{
    ......
    virtio_device_ready(vdev);
}

/**
 * virtio_device_ready - enable vq use in probe function
 * @vdev: the device
 *
 * Driver must call this to use vqs in the probe function.
 *
 * Note: vqs are enabled automatically after probe returns.
 */
static inline
void virtio_device_ready(struct virtio_device *dev)
{
        unsigned status = dev->config->get_status(dev);

        BUG_ON(status & VIRTIO_CONFIG_S_DRIVER_OK);
        dev->config->set_status(dev, status | VIRTIO_CONFIG_S_DRIVER_OK);
}

# QEMU/KVM后端的处理流程如下：
# 前端驱动写Status位，val & VIRTIO_CONFIG_S_DRIVER_OK，这时候前端驱动已经ready
virtio_pci_config_write  --> virtio_ioport_write --> virtio_pci_start_ioeventfd
--> virtio_bus_set_host_notifier --> virtio_bus_start_ioeventfd --> virtio_device_start_ioeventfd_impl
--> virtio_bus_set_host_notifier
    --> virtio_pci_ioeventfd_assign
        --> memory_region_add_eventfd
            --> memory_region_transaction_commit
              --> address_space_update_ioeventfds
                --> address_space_add_del_ioeventfds
                  --> kvm_io_ioeventfd_add/vhost_eventfd_add
                    --> kvm_set_ioeventfd_pio
                      --> kvm_vm_ioctl(kvm_state, KVM_IOEVENTFD, &kick)
```

其实，这就是QEMU的`Fast MMIO`实现机制。
我们可以看到，QEMU会为每个设备MMIO对应的MemoryRegion注册一个ioeventfd。
最后调用了一个KVM_IOEVENTFD ioctl到KVM内核里面，而在KVM内核中会将MMIO对应的（gpa,len,eventfd）信息会注册到KVM_FAST_MMIO_BUS上。
这样当Guest访问MMIO地址范围退出后（触发`EPT Misconfig`），KVM会查询一下访问的GPA是否落在某段MMIO地址空间range内部，
如果是的话就直接写eventfd告知QEMU，QEMU就会从coalesced mmio ring page中取MMIO请求
（注：pio page和 mmio page是QEMU和KVM内核之间的共享内存页，已经提前mmap好了）。

```c
#kvm内核代码virt/kvm/eventfd.c中
kvm_vm_ioctl(KVM_IOEVENTFD)
  --> kvm_ioeventfd
    --> kvm_assign_ioeventfd
      --> kvm_assign_ioeventfd_idx

# MMIO处理流程中（handle_ept_misconfig）最后会调用到ioeventfd_write通知QEMU。
/* MMIO/PIO writes trigger an event if the addr/val match */
static int
ioeventfd_write(struct kvm_vcpu *vcpu, struct kvm_io_device *this, gpa_t addr,
                int len, const void *val)
{
        struct _ioeventfd *p = to_ioeventfd(this);

        if (!ioeventfd_in_range(p, addr, len, val))
                return -EOPNOTSUPP;

        eventfd_signal(p->eventfd, 1);
        return 0;
}
```

不了解`MMIO`是如何模拟的童鞋，可以结合本站的文章[`MMIO`模拟实现分析](https://kernelgo.org/mmio.html)去了解一下，
如果还是不懂的可以在文章下面评论。

**后端通知前端，是通过中断的方式**，QEMU/KVM中有一套完整的中断模拟实现框架，

如果对QEMU/KVM中断模拟不熟悉的童鞋，
建议阅读一下这篇文章：[`QEMU学习笔记-中断`](https://www.binss.me/blog/qemu-note-of-interrupt/)。
对于virtio-pci设备，可以通过Cap呈现MSIx给虚拟机，这样在前端驱动加载的时候就会尝试去使能MSIx中断，
后端在这个时候建立起MSIx通道。

前端驱动加载(probe)的过程中，会去初始化`virtqueue`，这个时候会去申请MSIx中断并注册中断处理函数：

```c
virtnet_probe
  --> init_vqs
    --> virtnet_find_vqs
      --> vi->vdev->config->find_vqs [vp_modern_find_vqs]
        --> vp_find_vqs
          --> vp_find_vqs_msix // 为每virtqueue申请一个MSIx中断，通常收发各一个队列
            --> vp_request_msix_vectors // 主要的MSIx中断申请逻辑都在这个函数里面
              --> pci_alloc_irq_vectors_affinity // 申请MSIx中断描述符(__pci_enable_msix_range)
                --> request_irq  // 注册中断处理函数
               
	       // virtio-net网卡至少申请了3个MSIx中断：
                // 一个是configuration change中断（配置空间发生变化后，QEMU通知前端）
                // 发送队列1个MSIx中断，接收队列1MSIx中断
```

在QEMU/KVM这一侧，开始模拟MSIx中断，具体流程大致如下：
```c
virtio_pci_config_write
  --> virtio_ioport_write
    --> virtio_set_status
      --> virtio_net_vhost_status
        --> vhost_net_start
          --> virtio_pci_set_guest_notifiers
            --> kvm_virtio_pci_vector_use 
              |--> kvm_irqchip_add_msi_route //更新中断路由表
              |--> kvm_virtio_pci_irqfd_use  //使能MSI中断
                 --> kvm_irqchip_add_irqfd_notifier_gsi
                   --> kvm_irqchip_assign_irqfd
                  
# 申请MSIx中断的时候，会为MSIx分配一个gsi，并为这个gsi绑定一个irqfd，然后调用ioctl KVM_IRQFD注册到内核中。               
static int kvm_irqchip_assign_irqfd(KVMState *s, int fd, int rfd, int virq,
                                    bool assign)
{
    struct kvm_irqfd irqfd = {
        .fd = fd,
        .gsi = virq,
        .flags = assign ? 0 : KVM_IRQFD_FLAG_DEASSIGN,
    };

    if (rfd != -1) {
        irqfd.flags |= KVM_IRQFD_FLAG_RESAMPLE;
        irqfd.resamplefd = rfd;
    }

    if (!kvm_irqfds_enabled()) {
        return -ENOSYS;
    }

    return kvm_vm_ioctl(s, KVM_IRQFD, &irqfd);
}

# KVM内核代码virt/kvm/eventfd.c
kvm_vm_ioctl(s, KVM_IRQFD, &irqfd)
  --> kvm_irqfd_assign
    --> vfs_poll(f.file, &irqfd->pt) // 在内核中poll这个irqfd

```

从上面的流程可以看出，**QEMU/KVM使用`irqfd`机制来模拟MSIx中断**，
即设备申请MSIx中断的时候会为MSIx分配一个gsi（这个时候会刷新irq routing table），
并为这个gsi绑定一个`irqfd`，最后在内核中去`poll`这个`irqfd`。
当QEMU处理完IO之后，就写MSIx对应的irqfd，给前端注入一个MSIx中断，告知前端我已经处理好IO了你可以来取结果了。

例如，virtio-scsi从前端取出IO请求后会取做DMA操作（DMA是异步的，QEMU协程中负责处理）。
当DMA完成后QEMU需要告知前端IO请求已完成（Complete），那么怎么去投递这个MSIx中断呢？
答案是调用`virtio_notify_irqfd`注入一个MSIx中断。

```c
#0  0x00005604798d569b in virtio_notify_irqfd (vdev=0x56047d12d670, vq=0x7fab10006110) at  hw/virtio/virtio.c:1684
#1  0x00005604798adea4 in virtio_scsi_complete_req (req=0x56047d09fa70) at  hw/scsi/virtio-scsi.c:76
#2  0x00005604798aecfb in virtio_scsi_complete_cmd_req (req=0x56047d09fa70) at  hw/scsi/virtio-scsi.c:468
#3  0x00005604798aee9d in virtio_scsi_command_complete (r=0x56047ccb0be0, status=0, resid=0) at  hw/scsi/virtio-scsi.c:495
#4  0x0000560479b397cf in scsi_req_complete (req=0x56047ccb0be0, status=0) at hw/scsi/scsi-bus.c:1404
#5  0x0000560479b2b503 in scsi_dma_complete_noio (r=0x56047ccb0be0, ret=0) at hw/scsi/scsi-disk.c:279
#6  0x0000560479b2b610 in scsi_dma_complete (opaque=0x56047ccb0be0, ret=0) at hw/scsi/scsi-disk.c:300
#7  0x00005604799b89e3 in dma_complete (dbs=0x56047c6e9ab0, ret=0) at dma-helpers.c:118
#8  0x00005604799b8a90 in dma_blk_cb (opaque=0x56047c6e9ab0, ret=0) at dma-helpers.c:136
#9  0x0000560479cf5220 in blk_aio_complete (acb=0x56047cd77d40) at block/block-backend.c:1327
#10 0x0000560479cf5470 in blk_aio_read_entry (opaque=0x56047cd77d40) at block/block-backend.c:1387
#11 0x0000560479df49c4 in coroutine_trampoline (i0=2095821104, i1=22020) at util/coroutine-ucontext.c:115
#12 0x00007fab214d82c0 in __start_context () at /usr/lib64/libc.so.6
```

在`virtio_notify_irqfd `函数中，会去写`irqfd`，给内核发送一个信号。

```c
void virtio_notify_irqfd(VirtIODevice *vdev, VirtQueue *vq)
{
    ...
     /*
     * virtio spec 1.0 says ISR bit 0 should be ignored with MSI, but
     * windows drivers included in virtio-win 1.8.0 (circa 2015) are
     * incorrectly polling this bit during crashdump and hibernation
     * in MSI mode, causing a hang if this bit is never updated.
     * Recent releases of Windows do not really shut down, but rather
     * log out and hibernate to make the next startup faster.  Hence,
     * this manifested as a more serious hang during shutdown with
     *
     * Next driver release from 2016 fixed this problem, so working around it
     * is not a must, but it's easy to do so let's do it here.
     *
     * Note: it's safe to update ISR from any thread as it was switched
     * to an atomic operation.
     */
    virtio_set_isr(vq->vdev, 0x1);
    event_notifier_set(&vq->guest_notifier);   //写vq->guest_notifier，即irqfd
}
```

QEMU写了这个`irqfd`后，KVM内核模块中的irqfd poll就收到一个`POLL_IN`事件，然后将MSIx中断自动投递给对应的LAPIC。
大致流程是：`POLL_IN` -> `kvm_arch_set_irq_inatomic` -> `kvm_set_msi_irq`, `kvm_irq_delivery_to_apic_fast`

```c
static int
irqfd_wakeup(wait_queue_entry_t *wait, unsigned mode, int sync, void *key)
{
        if (flags & EPOLLIN) {
                idx = srcu_read_lock(&kvm->irq_srcu);
                do {
                        seq = read_seqcount_begin(&irqfd->irq_entry_sc);
                        irq = irqfd->irq_entry;
                } while (read_seqcount_retry(&irqfd->irq_entry_sc, seq));
                /* An event has been signaled, inject an interrupt */
                if (kvm_arch_set_irq_inatomic(&irq, kvm,
                                             KVM_USERSPACE_IRQ_SOURCE_ID, 1,
                                             false) == -EWOULDBLOCK)
                        schedule_work(&irqfd->inject);
                srcu_read_unlock(&kvm->irq_srcu, idx);
        }

```

这里还有一点没有想明白，结合代码和调试来看，virtio-blk/virtio-scsi的msi中断走irqfd机制，
但是virtio-net（不开启vhost的情况下）不走irqfd，而是直接调用`virtio_notify`/`virtio_pci_notify`，
最后通过KVM的ioctl投递中断？
从代码路径上来看，后者明显路径更长，谁知道原因告诉我一下!!!。
https://patchwork.kernel.org/patch/9531577/
```
Once in virtio_notify_irqfd, once in virtio_queue_guest_notifier_read.

Unfortunately, for virtio-blk + MSI + KVM + old Windows drivers we need the one in virtio_notify_irqfd.
For virtio-net + vhost + INTx we need the one in virtio_queue_guest_notifier_read. 
这显然路径更长啊。 
```

Ok，到这里virtio前后端通信机制已经明了，最后一个小节我们以virtio-net为例，梳理一下virtio中的部分核心代码流程。


## 3. virtio核心代码分析，以virtio-net为例

这里我们已virtio-net网卡为例，在没有使用vhost的情况下（网卡后端收发包都走QEMU处理），
后端收发包走vhost的情况下有些不同，后面单独分析。

### 3.1 前后端握手流程
QEM模拟PCI设备对GuestOS进行呈现，设备驱动加载的时候尝试去初始化设备。

```c
# 先在PCI总线上调用probe设备，调用了virtio_pci_probe，然后再virtio-bus上调用virtio_dev_probe
# virtio_dev_probe最后调用到virtnet_probe
pci_device_probe --> local_pci_probe --> virtio_pci_probe --> register_virtio_device --> 
device_register --> device_add --> bus_probe_device --> device_initial_probe 
--> __device_attach --> bus_for_each_drv --> __device_attach_driver --> driver_probe_device --> 
virtio_dev_probe --> virtnet_probe

# 在virtio_pci_probe里先尝试以virtio modern方式读取设备配置数据结构，如果失败则尝试virio legacy方式。
# 对于virtio legacy，我们前面提到了virtio legacy协议规定设备的配置数据结构放在PCI BAR0里面。
/* the PCI probing function */
int virtio_pci_legacy_probe(struct virtio_pci_device *vp_dev)
{
        rc = pci_request_region(pci_dev, 0, "virtio-pci-legacy");  //将设备的BAR0映射到物理地址空间
        vp_dev->ioaddr = pci_iomap(pci_dev, 0, 0);   //获得BAR0的内核地址
}

#对于virtio modern，通过capability方式报告配置数据结构的位置，配置数据结构有5种类型。
int virtio_pci_modern_probe(struct virtio_pci_device *vp_dev)
{
        /* check for a common config: if not, use legacy mode (bar 0). */
        common = virtio_pci_find_capability(pci_dev, VIRTIO_PCI_CAP_COMMON_CFG,
                                            IORESOURCE_IO | IORESOURCE_MEM,
                                            &vp_dev->modern_bars);

        /* If common is there, these should be too... */
        isr = virtio_pci_find_capability(pci_dev, VIRTIO_PCI_CAP_ISR_CFG,
                                         IORESOURCE_IO | IORESOURCE_MEM,
                                         &vp_dev->modern_bars);
        notify = virtio_pci_find_capability(pci_dev, VIRTIO_PCI_CAP_NOTIFY_CFG,
                                            IORESOURCE_IO | IORESOURCE_MEM,
                                            &vp_dev->modern_bars);
                                            
        /* Device capability is only mandatory for devices that have
        * device-specific configuration.
        */
        device = virtio_pci_find_capability(pci_dev, VIRTIO_PCI_CAP_DEVICE_CFG,
                                            IORESOURCE_IO | IORESOURCE_MEM,
                                            &vp_dev->modern_bars);

        err = pci_request_selected_regions(pci_dev, vp_dev->modern_bars,
                                            "virtio-pci-modern");
                                        sizeof(struct virtio_pci_common_cfg), 4,
                                        0, sizeof(struct virtio_pci_common_cfg),
                                        NULL);
        // 将配virtio置结构所在的BAR空间MAP到内核地址空间里                                
        vp_dev->common = map_capability(pci_dev, common,
                                        sizeof(struct virtio_pci_common_cfg), 4,
                                        0, sizeof(struct virtio_pci_common_cfg),
                                        NULL);
        ......                              
}

# 接着来到virtio_dev_probe里面看下：
static int virtio_dev_probe(struct device *_d)
{
        /* We have a driver! */
        virtio_add_status(dev, VIRTIO_CONFIG_S_DRIVER);     // 更新status bit，这里要写配置数据结构

        /* Figure out what features the device supports. */
        device_features = dev->config->get_features(dev);   // 查询后端支持哪些feature bits
        
        // feature set协商，取交集
        err = virtio_finalize_features(dev); 
        
        // 调用特定virtio设备的驱动程序probe，例如: virtnet_probe, virtblk_probe
        err = drv->probe(dev); 
}
```

再看下`virtnet_probe`里面的一些关键的流程，这里包含了virtio-net网卡前端初始化的主要逻辑。

```c
static int virtnet_probe(struct virtio_device *vdev)
{
       // check后端是否支持多队列，并按情况创建队列
       /* Allocate ourselves a network device with room for our info */
        dev = alloc_etherdev_mq(sizeof(struct virtnet_info), max_queue_pairs);
        
        // 定义一个网络设备并配置一些属性，例如MAC地址
        dev->ethtool_ops = &virtnet_ethtool_ops;
	       SET_NETDEV_DEV(dev, &vdev->dev);
 
        // 初始化virtqueue
        err = init_vqs(vi);
        
        // 注册一个网络设备
        err = register_netdev(dev);
        
        // 写状态位DRIVER_OK，告诉后端，前端已经ready
        virtio_device_ready(vdev);
        
        // 将网卡up起来
        netif_carrier_on(dev);
}
```
其中关键的流程是`init_vqs`，在`vp_find_vqs_msix`流程中会尝试去申请MSIx中断，这里前面已经有分析过了。
其中，"configuration changed" 中断服务程序`vp_config_changed`， 
virtqueue队列的中断服务程序是 `vp_vring_interrupt`。

```c
init_vqs --> virtnet_find_vqs --> vi->vdev->config->find_vqs --> vp_modern_find_vqs
--> vp_find_vqs --> vp_find_vqs_msix

static int vp_find_vqs_msix(struct virtio_device *vdev, unsigned nvqs,
		struct virtqueue *vqs[], vq_callback_t *callbacks[],
		const char * const names[], bool per_vq_vectors,
		const bool *ctx,
		struct irq_affinity *desc)
{
        /* 为configuration change申请MSIx中断 */
	err = vp_request_msix_vectors(vdev, nvectors, per_vq_vectors,
			      per_vq_vectors ? desc : NULL);
        for (i = 0; i < nvqs; ++i) {
		 // 创建队列 --> vring_create_virtqueue --> vring_create_virtqueue_split --> vring_alloc_queue
	         vqs[i] = vp_setup_vq(vdev, queue_idx++, callbacks[i], names[i],
                                ctx ? ctx[i] : false,
                                msix_vec);
		// 每个队列申请一个MSIx中断
                err = request_irq(pci_irq_vector(vp_dev->pci_dev, msix_vec),
                                  vring_interrupt, 0,
                                  vp_dev->msix_names[msix_vec],
                                  vqs[i]);
	}
```

`vp_setup_vq`流程再往下走就开始分配共享内存页，至此建立起共享内存通信通道。
值得注意的是一路传下来的callbacks参数其实传入了发送队列和接收队列的回调处理函数，
好家伙，从`virtnet_find_vqs`一路传递到了`__vring_new_virtqueue`中最终赋值给了`vq->vq.callback`。

```
static struct virtqueue *vring_create_virtqueue_split(
        unsigned int index,
        unsigned int num,
        unsigned int vring_align,
        struct virtio_device *vdev,
        bool weak_barriers,
        bool may_reduce_num,
        bool context,
        bool (*notify)(struct virtqueue *),
        void (*callback)(struct virtqueue *),
        const char *name)
{
       /* TODO: allocate each queue chunk individually */
        for (; num && vring_size(num, vring_align) > PAGE_SIZE; num /= 2) {
		// 申请物理页，地址赋值给queue
                queue = vring_alloc_queue(vdev, vring_size(num, vring_align),
                                          &dma_addr,
                                          GFP_KERNEL|__GFP_NOWARN|__GFP_ZERO);
        }


        queue_size_in_bytes = vring_size(num, vring_align);
        vring_init(&vring, num, queue, vring_align); // 确定 descriptor table, available ring, used ring的位置。
}
```

我们看下如果`virtqueue`队列如果收到MSIx中断消息后，会调用哪个`hook`来处理？

```c
irqreturn_t vring_interrupt(int irq, void *_vq)
{
        struct vring_virtqueue *vq = to_vvq(_vq);

        if (!more_used(vq)) {
                pr_debug("virtqueue interrupt with no work for %p\n", vq);
                return IRQ_NONE;
        }

        if (unlikely(vq->broken))
                return IRQ_HANDLED;

        pr_debug("virtqueue callback for %p (%p)\n", vq, vq->vq.callback);
        if (vq->vq.callback)
                vq->vq.callback(&vq->vq);

        return IRQ_HANDLED;
}
EXPORT_SYMBOL_GPL(vring_interrupt);
```

不难想到中断服务程序里面会调用队列上的callback。
我们再回过头来看下`virtnet_find_vqs`，原来接受队列的回调函数是`skb_recv_done`，发送队列的回调函数是`skb_xmit_done`。

```
static int virtnet_find_vqs(struct virtnet_info *vi)
{
       /* Allocate/initialize parameters for send/receive virtqueues */
        for (i = 0; i < vi->max_queue_pairs; i++) {
		callbacks[rxq2vq(i)] = skb_recv_done;
		callbacks[txq2vq(i)] = skb_xmit_done;
	}
}
```

OK，这个小节就到这里。Are you clear ?

### 3.2 virtio-net网卡收发在virtqueue上的实现

这里以virtio-net为例（非vhost-net模式）来分析一下网卡收发报文在virtio协议上的具体实现。
virtio-net模式下网卡收发包的流程为： 

* 收包：Hardware => Host Kernel => Qemu => Guest
* 发包：Guest => Host Kernel => Qemu => Host Kernel => Hardware

#### 3.2.1 virtio-net网卡发包

前面我们看到virtio-net设备初始化的时候会创建一个`net_device`设备：
`virtnet_probe` -> `alloc_etherdev_mq`注册了`netdev_ops` = `&virtnet_netdev`，
这里`virtnet_netdev`是网卡驱动的回调函数集合（收发包和参数设置）。

```c
static const struct net_device_ops netdev_ops = {
        .ndo_open               = rio_open,
        .ndo_start_xmit = start_xmit,
        .ndo_stop               = rio_close,
        .ndo_get_stats          = get_stats,
        .ndo_validate_addr      = eth_validate_addr,
        .ndo_set_mac_address    = eth_mac_addr,
        .ndo_set_rx_mode        = set_multicast,
        .ndo_do_ioctl           = rio_ioctl,
        .ndo_tx_timeout         = rio_tx_timeout,
};
```

网卡发包的时候调用`ndo_start_xmit`，将TCP/IP上层协议栈扔下来的数据发送出去。
对应到virtio网卡的回调函数就是`start_xmit`，从代码看就是将skb发送到virtqueue中，
然后调用virtqueue_kick通知qemu后端将数据包发送出去。

Guest内核里面的virtio-net驱动发包：
```c
内核驱动 virtio_net.c
start_xmit
	// 将skb放到virtqueue队列中
 	-> xmit_skb -> sg_init_table,virtqueue_add_outbuf -> virtqueue_add
	// kick通知qemu后端去取
	virtqueue_kick_prepare && virtqueue_notify 
	// kick次数加1
	sq->stats.kicks++
```

Guest Kick后端从KVM中VMExit出来退出到Qemu用户态（走的是ioeventfd）由Qemu去将数据发送出去。
大致调用的流程是：
`virtio_queue_host_notifier_read` -> `virtio_net_handle_tx_bh` -> `virtio_net_flush_tx`
-> `virtqueue_pop`拿到发包(skb) -> `qemu_sendv_packet_async`

```c
Qemu代码virtio-net相关代码:
virtio_queue_host_notifier_read -> virtio_queue_notify_vq
    -> vq->handle_output -> virtio_net_handle_tx_bh 队列注册的时候，回注册回调函数
        -> qemu_bh_schedule -> virtio_net_tx_bh
            -> virtio_net_flush_tx
	        -> virtqueue_pop
		-> qemu_sendv_packet_async // 报文放到发送队列上，写tap设备的fd去发包
		    -> tap_receive_iov -> tap_write_packet
		    
// 最后调用 tap_write_packet 把数据包发给tap设备投递出去
```

#### 3.2.2 virtio-net网卡收包

网卡收包的时候，tap设备先收到报文，对应的virtio-net网卡tap设备fd变为可读，
Qemu主循环收到POLL_IN事件调用回调函数收包。

```c
tap_send -> qemu_send_packet_async -> qemu_send_packet_async_with_flags
    -> qemu_net_queue_send
        -> qemu_net_queue_deliver
	    -> qemu_deliver_packet_iov
	        -> nc_sendv_compat
		    -> virtio_net_receive
		        -> virtio_net_receive_rcu
```

virtio-net网卡收报最终调用了`virtio_net_receive_rcu`，
和发包类似都是调用`virtqueue_pop`从前端获取virtqueue element，
将报文数据填充到vring中然后`virtio_notify`注入中断通知前端驱动取结果。

这里不得不吐槽一下，为啥收包函数取名要叫`tap_send`。

## 4. 参考文献

1. [virtio spec v1.1 ](https://docs.oasis-open.org/virtio/virtio/v1.1/csprd01/virtio-v1.1-csprd01.html)
1. [Towards a De-Facto Standard For Virtual](https://ozlabs.org/~rusty/virtio-spec/virtio-paper.pdf)
1. https://github.com/qemu/qemu/blob/master/hw/net/virtio-net.c
1. https://github.com/torvalds/linux/blob/master/drivers/net/virtio_net.c
