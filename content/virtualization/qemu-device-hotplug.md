---
author: Yori Fang
title:  Memory Hotplug & CPU Hotplug
date:   2020-04-26 23:00
status: published
slug:   qemu-device-hotplug
tags:   Memory Hotplug
---

在虚拟化场景下Guest的设备由软件进行模拟，所以可以比较方便地实现设备热插、热拔，
在不影响虚拟机正常运行的情况下，动态调整设备数目可以达到在线调整Guest算力资源的目的。
x86 platform上已经支持了Memory和CPU的hotplug/hotunplug等高级特性，aarch64现在也已经跟上。
这篇文章整理一下最近openEuler上合入的Memory和CPU hotplug特性。

## 1. Memory Hotplug 特性

QEMU 4.2版本给我们带来了期待已久的Memory Hotplug特性，相关实现patch可以patchworks上获取到：

[https://patchwork.kernel.org/cover/11150345/](https://patchwork.kernel.org/cover/11150345/)

在ARM64平台上没有PIO空间（PIO是x86独有的），为了支持memory hotplug event signaling，
于是使用了GED(Generic Event Device)设备来完成事件通知机制。
有点好奇什么是GED设备？翻阅了ACPI Spec才知道，
GED是ACPI 6.1规范在Hardware Reduced模式下定义的一个事件通知设备，
ARM64上的内存热插使用这个设备通知Guest。
备注：这有个疑问是，为啥不像x86上一样用ACPI GPE（General-Purpose Event）来做这个事情呢?

`generic_event_device.c`中定义了GED设备类型，为了支持hotplug这个设备
实现了两个qom interface，`TYPE_HOTPLUG_HANDLER`和`TYPE_ACPI_DEVICE_IF`。
前者定义了hotplug相关的hook，后者定义了acpi相关的hook，体现了OOB设计的思想。

```c
static const TypeInfo acpi_ged_info = {
    .name          = TYPE_ACPI_GED,
    .parent        = TYPE_SYS_BUS_DEVICE,   // 挂载到sysbus
    .instance_size = sizeof(AcpiGedState),  // 设备状态
    .instance_init  = acpi_ged_initfn,      // 设备实例化函数
    .class_init    = acpi_ged_class_init,   // 类初始化函数
    .interfaces = (InterfaceInfo[]) {       // 实现接口列表
        { TYPE_HOTPLUG_HANDLER },
        { TYPE_ACPI_DEVICE_IF },
        { }
    }
};
```

实现了2个相关interface之后，需要为Memory Hotplug定义自己的hook函数（但实际上只需实现一部分接口）。
所以，这里对应的实现是`acpi_ged_device_plug_cb`和`acpi_ged_send_event`。

```c
static void acpi_ged_class_init(ObjectClass *class, void *data)
{
    DeviceClass *dc = DEVICE_CLASS(class);
    HotplugHandlerClass *hc = HOTPLUG_HANDLER_CLASS(class);
    AcpiDeviceIfClass *adevc = ACPI_DEVICE_IF_CLASS(class);

    dc->desc = "ACPI Generic Event Device";
    device_class_set_props(dc, acpi_ged_properties); // 定义了properties
    dc->vmsd = &vmstate_acpi_ged;       // 热迁移状态保存和恢复

    hc->plug = acpi_ged_device_plug_cb; // hotplug callback 回调

    adevc->send_event = acpi_ged_send_event; // hotplug event事件注入
}
```

GED设备状态里面维护了6个成员：

* `parent_obj`用来将设备挂载到Sysbus下
* `memhp_state`用来描述MemoryHotplug状态
* `container_memhp`这个MR Container MMIO区域，长度24字节
* `ged_state`用来描述GED状态
* `ged_event_bitmap`事件bitmap
* `irq`设备有一个GPIO中断，给谁用的？

```c
typedef struct AcpiGedState {
    SysBusDevice parent_obj;        // 挂载到sysbus下
    MemHotplugState memhp_state;    // MemoryHotplug状态
    MemoryRegion container_memhp;   // MR
    GEDState ged_state;             // GED状态
    uint32_t ged_event_bitmap;      // event bitmap
    qemu_irq irq;                   // irq
} AcpiGedState;
```

这个GED设备存在的唯一意义就是帮助完成Memory Hotplug。
有必要了解一下这个GED设备，根据
[ACPI Spec Chapter 5.6.9 Interrupt-signaled ACPI events](https://uefi.org/sites/default/files/resources/ACPI_6_3_final_Jan30.pdf)章节，
GED设备使用_CRS（Current Resource Setting）描述中断，使用_EVT对象来映射ACPI事件。
例如：下面的ASL中定义了3个中断及其回调函数

```
Device (\_SB.GED1) 
{
    Name(HID,”ACPI0013”)
    Name(_CRS, ResourceTemplate () 
    {
        Interrupt(ResourceConsumer, Level, ActiveHigh, Exclusive) {41}
        Interrupt(ResourceConsumer, Edge, ActiveHigh, Shared) {42}
        Interrupt(ResourceConsumer, Level, ActiveHigh, ExclusiveAndWake) {43}
    }
    Method (_EVT,1) { // Handle all ACPI Events signaled by the Generic Event Device(GED1)
        Switch (Arg0) // Arg0 = GSIV of the interrupt
        {
            Case (41) { // interrupt 41 
                Store(One, ISTS) // clear interrupt status register at device X 
                                // which is mapped via an operation region 
                Notify (\_SB.DEVX, 0x0) // insertion request 
            } 
            Case (42) { // interrupt 42 
                Notify (\_SB.DEVX, 0x3) // ejection request 
            }
            Case (43) { // interrupt 43 
                Store(One, ISTS) // clear interrupt status register at device X 
                                 // which is mapped via an operation region 
                Notify (\_SB.DEVX, 0x2) // wake event
            }
        }
    } //End of Method 
} //End of GED1 Scope
```

Memory Hotplug实现的重点部分是ACPI表的那一部分。
为了支持Memory Hotplug需要提前做的事情有2个：

* ARM64上virt主板初始化的时候要创建GED设备
* 主板创建完成之后开始构建GED ACPI表，如果配置了numa要构建srat表

```c
machvirt_init
    -> vms->acpi_dev = create_acpi_ged(vms) // 创建ged设备

virt_machine_done   
    -> virt_acpi_setup
        -> virt_acpi_build
            -> build_dsdt
                -> build_ged_aml    // build GED ACPI table
                -> build_memory_hotplug_aml // build DIMM hotplug ACPI table
            -> build_srat   // numa节点>0的时候要呈现SRAT
```

### 1.1 创建ged设备

GED设备创建的时候做哪些事情？

* 创建ged设备
* 设置了属性`ged-event`当前只支持了2个事件：powerdown事件和hotplug事件
* 设置了ged设备和dimm设备的mmio基地址
* 连接了ged设备的GPIO
  
设备属性`ged-event`是32bit的，理论上可以支持很多事件。
而且可以看到，设备的ACPI和PCDIMM基地址是提前分配好的（静态的）。

```c
static inline DeviceState *create_acpi_ged(VirtMachineState *vms)
{
    DeviceState *dev;
    MachineState *ms = MACHINE(vms);
    int irq = vms->irqmap[VIRT_ACPI_GED];
    uint32_t event = ACPI_GED_PWR_DOWN_EVT;

    if (ms->ram_slots) {
        event |= ACPI_GED_MEM_HOTPLUG_EVT;
    }

    dev = qdev_create(NULL, TYPE_ACPI_GED);
    qdev_prop_set_uint32(dev, "ged-event", event);

    sysbus_mmio_map(SYS_BUS_DEVICE(dev), 0, vms->memmap[VIRT_ACPI_GED].base);
    sysbus_mmio_map(SYS_BUS_DEVICE(dev), 1, vms->memmap[VIRT_PCDIMM_ACPI].base);
    sysbus_connect_irq(SYS_BUS_DEVICE(dev), 0, qdev_get_gpio_in(vms->gic, irq));

    qdev_init_nofail(dev);  // 设备实例化，调用realize函数

    return dev;
}
```
这里隐含了的是，ged设备在实例化的时候`acpi_ged_initfn`里调用了`acpi_memory_hotplug_init`。
此时，会为DIMM设备创建好一个名为`acpi-mem-hotplug`的MemoryRegion，
作为一段MMIO呈现给Guest OS，Guest可以读写这个MR来查询DIMM slot状态，
并支持Memory Hot-unplug这个高级特性。

### 1.2 构建ged的acpi表

ged设备的ACPI信息方在DSDT(Differentiated System Description Table)表中，
在函数`build_ged_aml`来构建AML信息：

```c
void build_ged_aml(Aml *table, const char *name, HotplugHandler *hotplug_dev,
                   uint32_t ged_irq, AmlRegionSpace rs, hwaddr ged_base)
{
    AcpiGedState *s = ACPI_GED(hotplug_dev);
    Aml *crs = aml_resource_template();     // 创建_CRS，描述中断信息
    Aml *evt, *field;
    Aml *dev = aml_device("%s", name);
    Aml *evt_sel = aml_local(0);
    Aml *esel = aml_name(AML_GED_EVT_SEL);

    /* _CRS interrupt */  // 定义了一个_CRS中断，编号irqmap[VIRT_ACPI_GED] + ARM_SPI_BASE
    aml_append(crs, aml_interrupt(AML_CONSUMER, AML_EDGE, AML_ACTIVE_HIGH,
                                  AML_EXCLUSIVE, &ged_irq, 1));

    aml_append(dev, aml_name_decl("_HID", aml_string("ACPI0013")));
    aml_append(dev, aml_name_decl("_UID", aml_string(GED_DEVICE)));
    aml_append(dev, aml_name_decl("_CRS", crs));

    /* Append IO region */      // 添加EVT_REG和EVT_SEL寄存器
    aml_append(dev, aml_operation_region(AML_GED_EVT_REG, rs,
               aml_int(ged_base + ACPI_GED_EVT_SEL_OFFSET),
               ACPI_GED_EVT_SEL_LEN));
    field = aml_field(AML_GED_EVT_REG, AML_DWORD_ACC, AML_NOLOCK,
                      AML_WRITE_AS_ZEROS);
    aml_append(field, aml_named_field(AML_GED_EVT_SEL,
                                      ACPI_GED_EVT_SEL_LEN * BITS_PER_BYTE));
    aml_append(dev, field);

    /*
     * For each GED event we:
     * - Add a conditional block for each event, inside a loop.
     * - Call a method for each supported GED event type.
     *
     * The resulting ASL code looks like:
     *
     * Local0 = ESEL
     * If ((Local0 & One) == One)
     * {
     *     MethodEvent0()
     * }
     *
     * If ((Local0 & 0x2) == 0x2)
     * {
     *     MethodEvent1()
     * }
     * ...
     */
    evt = aml_method("_EVT", 1, AML_SERIALIZED);
    {
        Aml *if_ctx;
        uint32_t i;
        uint32_t ged_events = ctpop32(s->ged_event_bitmap);

        /* Local0 = ESEL */
        aml_append(evt, aml_store(esel, evt_sel));

        for (i = 0; i < ARRAY_SIZE(ged_supported_events) && ged_events; i++) {
            uint32_t event = s->ged_event_bitmap & ged_supported_events[i];

            if (!event) {
                continue;
            }

            if_ctx = aml_if(aml_equal(aml_and(evt_sel, aml_int(event), NULL),
                                      aml_int(event)));
            switch (event) {
            case ACPI_GED_MEM_HOTPLUG_EVT:  // 调用Memory Slot扫描函数
                aml_append(if_ctx, aml_call0(MEMORY_DEVICES_CONTAINER "."
                                             MEMORY_SLOT_SCAN_METHOD));
                break;
            case ACPI_GED_PWR_DOWN_EVT:
                aml_append(if_ctx,          // 调用回调函数，似乎是用来关机
                           aml_notify(aml_name(ACPI_POWER_BUTTON_DEVICE),
                                      aml_int(0x80)));
                break;
            default:
                /*
                 * Please make sure all the events in ged_supported_events[]
                 * are handled above.
                 */
                g_assert_not_reached();
            }

            aml_append(evt, if_ctx);
            ged_events--;
        }

        if (ged_events) {
            error_report("Unsupported events specified");
            abort();
        }
    }

    /* Append _EVT method */
    aml_append(dev, evt);

    aml_append(table, dev);
}
```

除此之外，还要构建DIMM支持Hotplug的ACPI表，它的实现函数是`build_memory_hotplug_aml`。
在这个表里面存放了当前主板上内存的插槽信息`max_slot_num`，
插槽状态信息，和插槽扫描函数(`MEMORY_SLOT_SCAN_METHOD`)等关键信息。
Guest在boot的时候会去解析这些表的信息，当事件到来时就调用对应的函数来处理
Memory Hotplug/unplug事件。

当配置了Guest Numa的时候，还要去呈现SRAT（System Resource Affinity Table）表。
这个过程是在`build_srat`中实现，目的是为了呈现资源亲和性。

### 1.3 Linux arm64 内核支持memory hotplug

QEMU 4.1支持arm64 memory hotplug之后当然也需要Linux kernel进行支持，
相关的内核patch可以在patchwork上获取到（看pw历史记录有助于了解patch review的过程）：

[https://patchwork.kernel.org/patch/10724455/](https://patchwork.kernel.org/patch/10724455/)

对应的内核git commit是:

[https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=4ab215061554ae2a4b78744a5dd3b3c6639f16a7](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=4ab215061554ae2a4b78744a5dd3b3c6639f16a7)

不得不说的是，有点气人，尽管没几行代码但这个patch我看不懂！！！ 

### 1.4 测试arm64虚拟机的Memory Hotplug功能

Launch qemu虚拟机进程，初始配置8G内存2个numa node，最大支持内存512G内存。

```
/usr/bin/qemu-system-aarch64 \
    -M virt,usb=off,accel=kvm,gic-version=3 \
    -cpu host \
    -smp sockets=1,cores=4 \
    -m size=8G,slots=128,maxmem=512G \
    -numa node,nodeid=0,cpus=0-1,mem=4G \
    -numa node,nodeid=1,cpus=2-3,mem=4G \
    -chardev socket,id=qmp,path=/var/run/qemu-qmp.qmp,server,nowait \
    -mon chardev=qmp,mode=control \
    -nodefaults \
    -drive file=/usr/share/edk2/aarch64/QEMU_EFI-pflash.raw,if=pflash,format=raw,unit=0,readonly=on \
    -drive file=/var/lib/libvirt/qemu/nvram/fangying_openeuler_VARS.fd,if=pflash,format=raw,unit=1 \
    -device pcie-root-port,port=0x8,chassis=1,id=pci.1,bus=pcie.0,multifunction=on,addr=0x1 \
    -device pcie-root-port,port=0x9,chassis=2,id=pci.2,bus=pcie.0,addr=0x1.0x1 \
    -device pcie-pci-bridge,id=pci.3,bus=pci.1,addr=0x0 \
    -device pcie-root-port,port=0xa,chassis=4,id=pci.4,bus=pcie.0,addr=0x1.0x2 \
    -device pcie-root-port,port=0xb,chassis=5,id=pci.5,bus=pcie.0,addr=0x1.0x3 \
    -device pcie-root-port,port=0xc,chassis=6,id=pci.6,bus=pcie.0,addr=0x1.0x4 \
    -device pcie-root-port,port=0xd,chassis=7,id=pci.7,bus=pcie.0,addr=0x1.0x5 \
    -device pcie-root-port,port=0xe,chassis=8,id=pci.8,bus=pcie.0,addr=0x1.0x6 \
    -device pcie-root-port,port=0xf,chassis=9,id=pci.9,bus=pcie.0,addr=0x1.0x7 \
    -device virtio-blk-pci,drive=drive-virtio0,id=virtio0,bus=pci.4,addr=0x0 \
    -drive file=./openeuler-lts.qcow2,if=none,id=drive-virtio0,cache=none,aio=native \
    -device usb-ehci,id=usb,bus=pci.3,addr=0x1 \
    -device usb-tablet,id=input0,bus=usb.0,port=1 \
    -device usb-kbd,id=input1,bus=usb.0,port=2 \
    -device virtio-gpu-pci,id=video0,bus=pci.3,addr=0x4 \
    -device virtio-balloon-pci,id=balloon0,bus=pci.3,addr=0x3 \
    -vnc :99 \
    -monitor stdio
```

使用qemu monitor命令执行内存热插，这里为虚拟机添加1G内存：

```
  (qemu) object_add memory-backend-ram,id=mem1,size=1G
  (qemu) device_add pc-dimm,id=dimm1,memdev=mem1
```

然后到Guest OS内部去执行`free -g`或者`numactl -H`查询一下（注意Guest OS内核版本要支持memhp），
应该已经生效了，但这个时候内存应该默认还没自动上线。

手动上线：
```bash
  for i in `grep -l offline /sys/devices/system/memory/memory*/state`
  do 
      echo online > $i 
  done
```

udev设备自动上线。编辑udev rules创建文件
/etc/udev/rules.d/99-hotplug-memory.rules
```
# automatically online hot-plugged memory
ACTION=="add", SUBSYSTEM=="memory", ATTR{state}="online"
```

## 2. CPU Hotplug 特性

QEMU在x86上很早就支持了CPU hotplug，但在aarch64上目前upstream还没有支持。
值得高兴地是，在openEuler上提前为我们带来了这个特性，
感谢HUAWEI Hisilicon和openEuler virtualization team的努力！

CPU Hotplug主要涉及的点有：

1. MADT(Multiple APIC Description Table)表构构建
1. 构建PPTT( Processor Properties Topology Table)表 
1. 扩展GED，支持CPU Hotplug Event


## 3. Reference

* 1. [Linux Kernel Memory Hotplug](https://www.kernel.org/doc/html/latest/admin-guide/mm/memory-hotplug.html)