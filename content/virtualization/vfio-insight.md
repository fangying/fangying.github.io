Title: Insight Into VFIO
Date: 2018-5-28 23:00
Modified: 2018-5-28 23:00
Tags: virtualization
Slug: vfio-insight
Authors: Yori Fang
Summary: VFIO Insight Into VFIO

本文则主要探讨一下VFIO实现中的关键点，主要包括：

* VFIO中如实现对直通设备的I/O地址空间访问的？
* VFIO中如何实现MSI/MSI-X，Interrupt Remapping，以及Posted Interrupt的支持？
* VFIO中是如何建立DMA Remapping映射关系？
* VFIO中又是如何支持设备热插拔的？

上面4个问题你能回答上来吗？

--------------------

### 1.VFIO中如实现对直通设备的I/O地址空间访问？ ###

在设备直通的场景下guest OS到底该如何访问设备I/O空间？
有两种方法可选：

方法A：直接呈现，将设备在主机上的PCI BAR呈现给guest，并通过VMCS的I/O bitmap和EPT页表使guest访问设备的PIO和MMIO都不引起VM-Exit，这样guest驱动程序可以直接访问设备的I/O地址空间。

方法B：建立转换表，呈现虚拟的PCI BAR给guest，当guest访问到虚拟机的I/O地址空间时VMM截获操作并通过转换表将I/O请求转发到设备在主机上的I/O地址空间上。

方法A看起来很高效，因为直接呈现的方式下不引入VM-Exit，但实际上是有问题的！
**原因是**：
设备的PCI BAR空间是由host的BIOS配置并由host操作系统直接使用的，
guest的PCI BAR空间是由guest的虚拟BIOS（例如Seabios）配置的，
那么问题来了，到底该由谁来配置设备的PCI BAR空间呢？肯定不能两个都生效否则就打架了！
我们应该阻止guest来修改真实设备的PCI BAR地址以防止造成host上PCI设备的BAR空间冲突导致可能出现的严重后果。

所以我们要选择方案B，建立转换表，明白这一点很重要！

对于直通设备的PIO访问而言，通过设置VMCS的I/O bitmap控制guest访问退出到VMM中然后通过转换表（模拟的方式）将PIO操作转发到真实物理设备上。对于MMIO的访问，可以通过EPT方式将虚拟的MMIO地址空间映射到物理设备的MMIO地址空间上，这样guest访问MMIO时并不需要VM-Exit。

**直通设备的PCI Config Space模拟**

PCI配置空间是用来报告设备I/O信息的区域，可以通过PIO或者MMIO方式进行访问。
设备直通场景的配置空间并不直接呈现给guest而是由VFIO配合qemu进行模拟的。

vfio_realize函数中，
QEMU会读取物理设备的PCI配置空间以此为基础然后对配置空间做些改动然后呈现给虚拟机。
```c
    /* Get a copy of config space */  // 读取设备的原始PCI Config Space信息
    ret = pread(vdev->vbasedev.fd, vdev->pdev.config,
                MIN(pci_config_size(&vdev->pdev), vdev->config_size),
                vdev->config_offset);   // 调用vfio-pci内核中的vfio_pci_read实现
    ......              
    /* vfio emulates a lot for us, but some bits need extra love */
    vdev->emulated_config_bits = g_malloc0(vdev->config_size);
    // 我们可以选择性的Enable/Disable一些Capability
    /* QEMU can choose to expose the ROM or not */
    memset(vdev->emulated_config_bits + PCI_ROM_ADDRESS, 0xff, 4);
    /* QEMU can also add or extend BARs */
    memset(vdev->emulated_config_bits + PCI_BASE_ADDRESS_0, 0xff, 6 * 4);
    // 调用vfio_add_emulated_word修改模拟的PCI配置空间信息
    vfio_add_emulated_word
    /*
     * Clear host resource mapping info.  If we choose not to register a
     * BAR, such as might be the case with the option ROM, we can get
     * confusing, unwritable, residual addresses from the host here.
     */
    memset(&vdev->pdev.config[PCI_BASE_ADDRESS_0], 0, 24);
    memset(&vdev->pdev.config[PCI_ROM_ADDRESS], 0, 4);
    vfio_bars_prepare(vdev);    // 重点分析
    vfio_bars_register(vdev);   // 重点分析
    vfio_add_capabilities(vdev, errp);
```
通常MSI/MSIX等信息都需要被QEMU修改，因为这些都是QEMU使用VFIO去模拟的。

**直通设备MMIO（BAR空间）映射**

vfio_realize函数中会对直通设备的MMIO空间进行映射，大致包含以下几个步骤:

* 调用vfio_populate_device从VFIO中查询出设备的BAR空间信息
* 把设备的MMIO（BAR空间）重映射（mmap）到QEMU进程的虚拟地址空间
* 将该段虚拟机地址空间标记为RAM类型注册给虚拟机

这样一来，guest访问MMIO地址空间时直接通过EPT翻译到HPA不需要VM-Exit。我们分析下具体流程：

```c
vfio_realize
    |-> vfio_populate_device
            |-> vfio_region_setup  
                    |-> vfio_get_region_info   // call ioct VFIO_DEVICE_GET_REGION_INFO
                    |-> memory_region_init_io  // init region->mem MR as I/O
    |-> vfio_bars_prepare -> vfio_bar_prepare  // probe info of each pci bar from PCI cfg space
    |-> vfio_bars_register -> vfio_bar_register
            |-> memory_region_init_io // int bar->mr
            |-> memory_region_add_subregion // add bar->mr into region->mem MR
            |-> vfio_region_mmap
                |-> mmap // map device bar space into QEMU process address space -> iova
                |-> memory_region_init_ram_device_ptr // register iova into VM  physical AS
                |-> memory_region_add_subregion // add region->mmaps[i].mem into region->mem MR
            |-> pci_register_bar
```

为了方便理解这个过程，我画了一张示意图：

![vfio-pci-bar](../images/vfio_pci_bar.svg)

QEMU首先调用vfio_region_mmap，
通过mmap region->vbasedev->fd 把设备MMIO映射到QEMU进程的虚拟地址空间，
这实际上通过调用vfio-pci内核驱动vfio_pci_mmap -> remap_pfn_range，
*remap_pfn_range*是内核提供的API，
可以将一段连续的物理地址空间映射到进程的虚拟地址空间，
这里用它将设备的BAR空间的MMIO先映射到QEMU进程的虚拟地址空间再注册给虚拟机。

```c
static int vfio_pci_mmap(void *device_data, struct vm_area_struct *vma)
{
    req_len = vma->vm_end - vma->vm_start;     // MMIO size
    vma->vm_pgoff = (pci_resource_start(pdev, index) >> PAGE_SHIFT) + pgoff;  // MMIO page address 
    return remap_pfn_range(vma, vma->vm_start, vma->vm_pgoff,
            req_len, vma->vm_page_prot);

}
```

再来看下QEMU是如何注册这段虚拟地址(IOVA)到虚拟机的。

vfio_region_mmap调用memory_region_init_ram_device_ptr把前面mmap过来的
这段IOVA作为RAM类型设备注册给虚拟机。
```c
int vfio_region_mmap(VFIORegion *region) 
{
    name = g_strdup_printf("%s mmaps[%d]",
                               memory_region_name(region->mem), i);
    memory_region_init_ram_device_ptr(&region->mmaps[i].mem,
                                        memory_region_owner(region->mem),
                                        name, region->mmaps[i].size,
                                        region->mmaps[i].mmap);
    memory_region_add_subregion(region->mem, region->mmaps[i].offset,
                                &region->mmaps[i].mem);                                    
}
```
memory_region_init_ram_device_ptr中会标志 mr->ram = true，
那么QEMU就会通过kvm_set_phys_mem注册这段内存给虚拟机（是RAM类型才会建立EPT映射关系），
这样KVM就会为这段地址空间建立EPT页表，
虚拟机访问设备的MMIO空间时通过EPT页表翻直接访问不需要VM-Exit。
例如，网卡的收发包场景，虚拟机可以直接操作真实网卡的相关寄存器（MMIO映射）而没有陷入先出开销，大幅度提升了虚拟化场景下的I/O性能。

```c
static void kvm_set_phys_mem(KVMMemoryListener *kml,
                             MemoryRegionSection *section, bool add)
{
    if (!memory_region_is_ram(mr)) {  // mr->ram = true 会注册到KVM
        if (writeable || !kvm_readonly_mem_allowed) {
            return;
        } else if (!mr->romd_mode) {
            /* If the memory device is not in romd_mode, then we actually want
             * to remove the kvm memory slot so all accesses will trap. */
            add = false;
        }
    }

    ram = memory_region_get_ram_ptr(mr) +   section->offset_within_region +  
          (start_addr - section->offset_within_address_space);
    kvm_set_user_memory_region  // 作为RAM设备注册到KVM中
}
```

### 2.VFIO中如何实现MSI/MSI-X，Interrupt Remapping，以及Posted Interrupt的支持？ ###

对于VFIO设备直通而言，设备中断的处理方式共有4种:

* INTx 最传统的PCI设备引脚Pin方式
* MSI/MSI-X方式
* Interrupt Remapping方式
* VT-d Posted Interrupt方式

那么它们分别是如何设计实现的呢？
这里我们来重点探索一下MSI/MSI-X的实现方式以及VT-d Posted Interrupt方式。
如果忘了MSI和MSI-X的知识点可以看下《[PCI Local Bus Specification 
 Revision 3.0](https://www.xilinx.com/Attachment/PCI_SPEV_V3_0.pdf)》的Chapter 6有比较详细的介绍。

先看下QEMU这边中断初始化和中断使能相关的函数调用关系图：
```c
vfio_realize
    |-> vfio_get_device       // get device info: num_irqs, num_regions, flags
    |-> vfio_msix_early_setup // get MSI-X info: table_bar,table_offset, pba_ -> pci_device_route_intx_to_irqbar,pba_offset, entries
        |-> vfio_pci_fixup_msix_region
        |-> vfio_pci_relocate_msix
    |-> vfio_add_capabilities
            |-> vfio_add_std_cap
                |-> vfio_msi_setup  -> msi_init
                |-> vfio_msix_setup -> msix_init
    |-> vfio_intx_enable    // enable intx
        |-> pci_device_route_intx_to_irq
        |-> event_notifier_init &vdev->intx.interrupt
        |-> ioctl VFIO_DEVICE_SET_IRQS

kvm_cpu_exec
   ...
    |-> vfio_pci_write_config
            |-> vfio_msi_enable 
                    |-> event_notifier_init        // init eventfd as irqfd
                    |-> vfio_add_kvm_msi_virq  ... -> kvm_irqchip_assign_irqfd
                    |-> vfio_enable_vectors false 
            |-> vfio_msix_enable
                |-> vfio_msix_vector_do_use -> msix_vector_use
                |-> vfio_msix_vector_release
                |-> msix_set_vector_notifiers
```

从图中可以看出，直通设备初始化时候会从物理设备的PCI配置空间读取INTx、MSI、MSI-X的相关信息并且进行一些必要的初始化（setup）再进行中断使能（enable）的。
根据调试的结果来看，INTx的enable是最早的，
而MSI/MSI-X初始化是在guest启动后进行enable。

这里以MSI-X为例，
首先调用vfio_msix_early_setup函数从硬件设备的PCI配置空间查询MSI-X相关信息包括:

* MSI-X Table Size ：MSI-X Table 大小
* MSI-X Table BAR Indicator ：MSI-X Table存放的BAR空间编号
* MSI-X Table Offset ：存放MSI-X Table在Table BAR空间中的偏移量
* MSI-X PBA BIR ：存放MSI-X 的Pending Bit Array的BAR空间编号
* MSI-X PBA Offset ：存放MSI-X Table在PBA BAR空间中的偏移量

获取必要信息之后，通过vfio_msix_setup来完成直通设备的MSI-X的初始化工作，
包括调用pci_add_capability为设备添加PCI_CAP_ID_MSIX Capability，
并注册MSI-X的BAR空间到虚拟机的物理地址空间等。

```c
static void vfio_msix_early_setup(VFIOPCIDevice *vdev, Error **errp)
{
    if (pread(fd, &ctrl, sizeof(ctrl),
              vdev->config_offset + pos + PCI_MSIX_FLAGS) != sizeof(ctrl)) {
        error_setg_errno(errp, errno, "failed to read PCI MSIX FLAGS");
        return;
    }

    if (pread(fd, &table, sizeof(table),
              vdev->config_offset + pos + PCI_MSIX_TABLE) != sizeof(table)) {
        error_setg_errno(errp, errno, "failed to read PCI MSIX TABLE");
        return;
    }

    if (pread(fd, &pba, sizeof(pba),
              vdev->config_offset + pos + PCI_MSIX_PBA) != sizeof(pba)) {
        error_setg_errno(errp, errno, "failed to read PCI MSIX PBA");
        return;
    }

    ctrl = le16_to_cpu(ctrl);
    table = le32_to_cpu(table);
    pba = le32_to_cpu(pba);

    msix = g_malloc0(sizeof(*msix));
    msix->table_bar = table & PCI_MSIX_FLAGS_BIRMASK;
    msix->table_offset = table & ~PCI_MSIX_FLAGS_BIRMASK;
    msix->pba_bar = pba & PCI_MSIX_FLAGS_BIRMASK;
    msix->pba_offset = pba & ~PCI_MSIX_FLAGS_BIRMASK;
    msix->entries = (ctrl & PCI_MSIX_FLAGS_QSIZE) + 1;
}
static int vfio_msix_setup(VFIOPCIDevice *vdev, int pos, Error **errp)
{

    vdev->msix->pending = g_malloc0(BITS_TO_LONGS(vdev->msix->entries) *
                                    sizeof(unsigned long));
    ret = msix_init(&vdev->pdev, vdev->msix->entries,
                    vdev->bars[vdev->msix->table_bar].mr,
                    vdev->msix->table_bar, vdev->msix->table_offset,
                    vdev->bars[vdev->msix->pba_bar].mr,
                    vdev->msix->pba_bar, vdev->msix->pba_offset, pos,
                    &err);
    memory_region_set_enabled(&vdev->pdev.msix_pba_mmio, false);
    if (object_property_get_bool(OBJECT(qdev_get_machine()),
                                 "vfio-no-msix-emulation", NULL)) {
        memory_region_set_enabled(&vdev->pdev.msix_table_mmio, false);
    }
}

```
最后guest启动后调用vfio_msix_enable使能MSI-X中断。

### irqfd 和 ioeventfd ###

我们知道QEMU本身有一套完整的模拟PCI设备INTx、MSI、MSI-X中断机制，
其实现方式是irqfd（QEMU中断注入到guest）和ioeventfd（guest中断通知到QEMU），
内部实现都是基于内核提供的eventfd机制。

看代码的时候一直没明白设备中断绑定的irqfd是在什么时候注册的，从代码上看不是中断enable时候。
后来结合代码调试才明白，
原来中断enable时候将设备的MSI/MSI-X BAR空间映射用MMIO方式注册给了虚拟机（参考msix_init, msi_init函数实现），
当虚拟机内部第一次访问MSI-X Table BAR空间的MMIO时会退出到用户态完成irqfd的注册，
调用堆栈为：

```c
#0  kvm_irqchip_assign_irqfd
#1   in kvm_irqchip_add_irqfd_notifier_gsi 
#2   in vfio_add_kvm_msi_virq 
#3   in vfio_msix_vector_do_use 
#4   in vfio_msix_vector_use 
#5   in msix_fire_vector_notifier
#6   in msix_handle_mask_update 
#7   in msix_table_mmio_write 
#8   in memory_region_write_accessor
#9   in access_with_adjusted_size 
#10  in memory_region_dispatch_write 
#11  in address_space_write_continue 
#12  in address_space_write 
#13  in address_space_rw 
#14  in kvm_cpu_exec 
```
关于irqfd的社区patch可以从这里获取[https://lwn.net/Articles/332924](https://lwn.net/Articles/332924/)。

备注：Alex Williamson在最新的VFIO模块中加入新特性，支持直接使用物理设备的MSIX BAR空间，
这样一来可以直接将物理设备的MSI-X BAR空间直接mmap过来然后呈现给虚拟机，
guest直接使用而不用再进行模拟了。
```
commit ae0215b2bb56a9d5321a185dde133bfdd306a4c0
Author: Alexey Kardashevskiy <aik@ozlabs.ru>
Date:   Tue Mar 13 11:17:31 2018 -0600

    vfio-pci: Allow mmap of MSIX BAR

    At the moment we unconditionally avoid mapping MSIX data of a BAR and
    emulate MSIX table in QEMU. However it is 1) not always necessary as
    a platform may provide a paravirt interface for MSIX configuration;
    2) can affect the speed of MMIO access by emulating them in QEMU when
    frequently accessed registers share same system page with MSIX data,
    this is particularly a problem for systems with the page size bigger
    than 4KB.

    A new capability - VFIO_REGION_INFO_CAP_MSIX_MAPPABLE - has been added
    to the kernel [1] which tells the userspace that mapping of the MSIX data
    is possible now. This makes use of it so from now on QEMU tries mapping
    the entire BAR as a whole and emulate MSIX on top of that.

    [1] https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=a32295c612c57990d17fb0f41e7134394b2f35f6

    Signed-off-by: Alexey Kardashevskiy <aik@ozlabs.ru>
    Reviewed-by: David Gibson <david@gibson.dropbear.id.au>
    Signed-off-by: Alex Williamson <alex.williamson@redhat.com>
```


### 3. VFIO中是如何建立DMA Remapping映射关系？ ###

前面的文章中我们反复提到VT-d DMA Remapping的原理和意义，那么在vfio中这又是如何实现的呢？

实现的原理其实不难，我们知道QEMU会维护虚拟机的物理地址空间映射关系，
而VT-d DMA Remapping需要建立GPA->HVA地址空间的映射关系，
那么当虚拟机的地址空间布局发生变化时我们都会尝试更新对应的DMA Remapping关系，
这是通过vfio_memory_listener来实现的。

```c
static const MemoryListener vfio_memory_listener = {
    .region_add = vfio_listener_region_add,
    .region_del = vfio_listener_region_del,
};
```

vfio_connect_container函数中会将vfio_memory_listener注册给QEMU的物理地址空间address_space_memory，
这样vfio_memory_listener会监听虚拟机的物理地址空间变化，
调用对应的回调函数更新DMA Remapping关系。

```c
memory_listener_register(&container->listener, container->space->as);
```

那么说了很久的IOMMU页表是如何创建和更新的呢？
看下vfio_listener_region_add/vfio_listener_region_del函数的实现就知道。
在该函数中先check对应的section是否是RAM（只对RAM类型的区域进行DMA Remapping），
再进行一些Sanity Check后调用vfio_dma_map将映射关系建立起来，
所以重点还是在于vfio_dma_map的函数实现。

```c
static void vfio_listener_region_add(MemoryListener *listener,
                                     MemoryRegionSection *section)
{
    VFIOContainer *container = container_of(listener, VFIOContainer, listener);
    hwaddr iova, end;
    Int128 llend, llsize;
    void *vaddr;
    int ret;
    VFIOHostDMAWindow *hostwin;
    bool hostwin_found;

    if (vfio_listener_skipped_section(section)) {   // do dma_map only if MRS is RAM type
        trace_vfio_listener_region_add_skip(
                section->offset_within_address_space,
                section->offset_within_address_space +
                int128_get64(int128_sub(section->size, int128_one())));
        return;
    }

    if (unlikely((section->offset_within_address_space & ~TARGET_PAGE_MASK) !=
                 (section->offset_within_region & ~TARGET_PAGE_MASK))) {
        error_report("%s received unaligned region", __func__);
        return;
    }

    iova = TARGET_PAGE_ALIGN(section->offset_within_address_space);
    llend = int128_make64(section->offset_within_address_space);
    llend = int128_add(llend, section->size);
    llend = int128_and(llend, int128_exts64(TARGET_PAGE_MASK));

    if (int128_ge(int128_make64(iova), llend)) {
        return;
    }
    end = int128_get64(int128_sub(llend, int128_one()));

    if (container->iommu_type == VFIO_SPAPR_TCE_v2_IOMMU) {
        hwaddr pgsize = 0;

        /* For now intersections are not allowed, we may relax this later */
        QLIST_FOREACH(hostwin, &container->hostwin_list, hostwin_next) {
            if (ranges_overlap(hostwin->min_iova,
                               hostwin->max_iova - hostwin->min_iova + 1,
                               section->offset_within_address_space,
                               int128_get64(section->size))) {
                ret = -1;
                goto fail;
            }
        }

        ret = vfio_spapr_create_window(container, section, &pgsize);
        if (ret) {
            goto fail;
        }

        vfio_host_win_add(container, section->offset_within_address_space,
                          section->offset_within_address_space +
                          int128_get64(section->size) - 1, pgsize);
#ifdef CONFIG_KVM
        if (kvm_enabled()) {
            VFIOGroup *group;
            IOMMUMemoryRegion *iommu_mr = IOMMU_MEMORY_REGION(section->mr);
            struct kvm_vfio_spapr_tce param;
            struct kvm_device_attr attr = {
                .group = KVM_DEV_VFIO_GROUP,
                .attr = KVM_DEV_VFIO_GROUP_SET_SPAPR_TCE,
                .addr = (uint64_t)(unsigned long)&param,
            };

            if (!memory_region_iommu_get_attr(iommu_mr, IOMMU_ATTR_SPAPR_TCE_FD,
                                              &param.tablefd)) {
                QLIST_FOREACH(group, &container->group_list, container_next) {
                    param.groupfd = group->fd;
                    if (ioctl(vfio_kvm_device_fd, KVM_SET_DEVICE_ATTR, &attr)) {
                        error_report("vfio: failed to setup fd %d "
                                     "for a group with fd %d: %s",
                                     param.tablefd, param.groupfd,
                                     strerror(errno));
                        return;
                    }
                    trace_vfio_spapr_group_attach(param.groupfd, param.tablefd);
                }
            }
        }
#endif
    }

    hostwin_found = false;
    QLIST_FOREACH(hostwin, &container->hostwin_list, hostwin_next) {
        if (hostwin->min_iova <= iova && end <= hostwin->max_iova) {
            hostwin_found = true;
            break;
        }
    }

    if (!hostwin_found) {
        error_report("vfio: IOMMU container %p can't map guest IOVA region"
                     " 0x%"HWADDR_PRIx"..0x%"HWADDR_PRIx,
                     container, iova, end);
        ret = -EFAULT;
        goto fail;
    }

    memory_region_ref(section->mr);     // increase ref of MR by one

    if (memory_region_is_iommu(section->mr)) {      // guest IOMMU emulation
        VFIOGuestIOMMU *giommu;
        IOMMUMemoryRegion *iommu_mr = IOMMU_MEMORY_REGION(section->mr);

        trace_vfio_listener_region_add_iommu(iova, end);
        /*
         * FIXME: For VFIO iommu types which have KVM acceleration to
         * avoid bouncing all map/unmaps through qemu this way, this
         * would be the right place to wire that up (tell the KVM
         * device emulation the VFIO iommu handles to use).
         */
        giommu = g_malloc0(sizeof(*giommu));
        giommu->iommu = iommu_mr;
        giommu->iommu_offset = section->offset_within_address_space -
                               section->offset_within_region;
        giommu->container = container;
        llend = int128_add(int128_make64(section->offset_within_region),
                           section->size);
        llend = int128_sub(llend, int128_one());
        iommu_notifier_init(&giommu->n, vfio_iommu_map_notify,
                            IOMMU_NOTIFIER_ALL,
                            section->offset_within_region,
                            int128_get64(llend));
        QLIST_INSERT_HEAD(&container->giommu_list, giommu, giommu_next);

        memory_region_register_iommu_notifier(section->mr, &giommu->n);
        memory_region_iommu_replay(giommu->iommu, &giommu->n);

        return;
    }

    /* Here we assume that memory_region_is_ram(section->mr)==true */

    vaddr = memory_region_get_ram_ptr(section->mr) +        // get hva
            section->offset_within_region +
            (iova - section->offset_within_address_space);

    trace_vfio_listener_region_add_ram(iova, end, vaddr);

    llsize = int128_sub(llend, int128_make64(iova));        // calc map size

    if (memory_region_is_ram_device(section->mr)) {
        hwaddr pgmask = (1ULL << ctz64(hostwin->iova_pgsizes)) - 1;

        if ((iova & pgmask) || (int128_get64(llsize) & pgmask)) {
            trace_vfio_listener_region_add_no_dma_map(
                memory_region_name(section->mr),
                section->offset_within_address_space,
                int128_getlo(section->size),
                pgmask + 1);
            return;
        }
    }

    ret = vfio_dma_map(container, iova, int128_get64(llsize),   // do VFIO_IOMMU_MAP_DMA
                       vaddr, section->readonly);
    if (ret) {
        error_report("vfio_dma_map(%p, 0x%"HWADDR_PRIx", "
                     "0x%"HWADDR_PRIx", %p) = %d (%m)",
                     container, iova, int128_get64(llsize), vaddr, ret);
        if (memory_region_is_ram_device(section->mr)) {
            /* Allow unexpected mappings not to be fatal for RAM devices */
            return;
        }
        goto fail;
    }

    return;

fail:
    if (memory_region_is_ram_device(section->mr)) {
        error_report("failed to vfio_dma_map. pci p2p may not work");
        return;
    }
    /*
     * On the initfn path, store the first error in the container so we
     * can gracefully fail.  Runtime, there's not much we can do other
     * than throw a hardware error.
     */
    if (!container->initialized) {
        if (!container->error) {
            container->error = ret;
        }
    } else {
        hw_error("vfio: DMA mapping failed, unable to continue");
    }
}

```

vfio_dma_map函数中会传入建立DMA Remapping的基本信息，
这里是用数据结构vfio_iommu_type1_dma_map来描述，
然后交给内核去做DMA Remapping。

```c
    struct vfio_iommu_type1_dma_map map = {
        .argsz = sizeof(map),
        .flags = VFIO_DMA_MAP_FLAG_READ,    // flags
        .vaddr = (__u64)(uintptr_t)vaddr,   // HVA
        .iova = iova,                       // iova -> gpa
        .size = size,                       // map size
    };
```

该函数对应的内核调用栈见下面的图，其主要流程包含2个步骤，简称pin和map：

*  vfio_pin_pages_remote 把虚拟机的物理内存都pin住，物理内存不能交换
*  vfio_iommu_map 创建虚拟机domain的IOMMU页表，DMA Remapping地址翻译时候使用

值得注意的是在pin步骤中，
pin虚拟机物理内存是调用get_user_pages_fast来实现的，
如果虚拟机的内存未申请那么会先将内存申请出来，
这个过程可能会非常耗时并且会持有进程的mmap_sem大锁。

```c
vfio_dma_do_map
--------------------------------------------------------------
vfio_pin_map_dma
    |-> vfio_pin_pages_remote   // pin pages in memory
        |-> vaddr_get_pfn
            |get_user_pages_fast
                |gup_pud_range
                    gup_pud_range
                        gup_pte_range
                            get_page   // pin page, without mm->mmap_sem held
                |get_user_pages_unlocked
                    __get_user_pages_locked
                        __get_user_pages
                            |handle_mm_fault
                                __handle_mm_fault // do_page_fault process
                                    alloc pud->pmd->pte
                                    handle_pte_fault
                                        do_anonymous_page
                                            alloc_zeroed_user_highpage_movable
                                            ... alloc page with __GFP_ZERO
                            |_get_page
                                atomic_inc(&page_count) // pin page
            |get_user_pages_remote
                __get_user_pages_locked

    |-> vfio_iommu_map  // create IOMMU domain page table
        |-> iommu_map
            |-> intel_iommu_map     // intel-iommu.c
                |-> domain_pfn_mapping
                    |-> pfn_to_dma_pte
```

同理，vfio_listener_region_add回调函数实现了DMA Remapping关系的反注册。

### 4. VFIO中又是如何支持设备热插拔的？ ###

vfio热插拔仍然是走的QEMU设备热插拔流程，大致流程如下：

```c
qdev_device_add
    |-> device_set_realized
        |-> hotplug_handler_plug
            |-> piix4_device_plug_cb
                |-> piix4_send_gpe // inject ACPI GPE to guest OS
        |-> pci_qdev_realize
                |-> vfio_realize
```

device_set_realized函数负责将设备上线，
piix4_send_gpe函数中会注入一个ACPI GPE事件通知GuestOS，
vfio_realize函数负责整个vfio的设备初始化流程。
那么vfio_realize中主要做了哪些事情呢？
可以用下面这一张图概括~[点击链接查看原图](https://kernelgo.org/images/qemu-vfio.svg)

vfio_realize的具体流程这里就不再展开免得啰嗦！
感兴趣的请自己分析代码去，所有的vfio实现细节都在这里面。

![vfio-pci-bar](../images/qemu-vfio.svg)
