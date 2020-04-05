Title:  Live Migration with Passthroughed Device (Draft)
Date: 2019-11-25 23:00
Modified: 2019-11-25 23:00
Tags: live migration, device passthrough, GPU, SR-IOV
Slug: live-migration-with-passthroughed-device
Status: published
Authors: Yori Fang
Summary: live migration

异构计算已经成为当前云计算的一个主流应用场景，
各种硬件加速器例如：GPGPU，FPGA，ASIC等都被用在异构计算场景来提供额外的算力加速。
为了将算力以更低的成本提供给客户，需要设计专门的加速器虚拟化方案。
就GPU虚拟化而言，目前比较著名的方案有：
Nvidia的GRID vGPU虚拟化方案（支持将一个物理GPU虚拟出多个vGPU实例提供给不同的虚拟机使用），
AMD的MxGPU方案(AMD FirePro系列显卡，走到是SRIOV方案，被AWS AppStream2采用)，
以及Intel的GVT-g方案（Intel 集成显卡，目前有一个demo）。
异构计算场景基本上都是用设备直通的方式将设备呈现给虚拟机，
而直通设备对于虚拟机热迁移不太友好，阻碍了热迁移的应用。

## 0. Live Migration With Passthourghed Device

下图是一个典型的Pre-Copy场景热迁移基本流程图:

```
                +----------+     +---------------+     +-----------------+
                | Pre-copy |     | Stop and Copy |     |Resume/Post-Copy |
                +----------+     +---------------+     +-----------------+

                |             |   Service Downtime   |                   |
                |             | <------------------> |                   |
                |                                                        |
                | <----------------Total Migration Time----------------> |
```

为了获得最优的IO性能，在公有云或者企业虚拟化场景下，会选择设备直通的方式将硬件设备直接呈现给虚拟机使用。
但直通带来的较大问题是对虚拟机的热迁移和热升级支持都非常不友好，
现阶段并没有一个很好的统一的框架能够完成直通虚拟机热迁移任务，其主要原因有以下几点：

* 挑战1：当前很多物理硬件设备还不持支持设备状态的暂停和运行（Pause & Resume）

在热迁移vCPU停机之后，设备端可能还存在已提交但尚未处理完成的任务，任务的结果还没写回处于一个中间的不确定状态。
很显然，这个时间点是不适合做设备状态快照的，因为状态都是中间态。
所以要么硬件设备在硬件层面就支持暂停、恢复，或者就要等到设备正在执行的任务执行完成，进入空闲状态。

* 挑战2：当前很多物理硬件设备还不支持硬件状态的保存和恢复（Save & Restore）

在一个典型的Pre-Copy迁移场景，当算法判断脏页已经收敛，最后一轮脏页拷贝后进入Checkpoint点，
源端需要将硬件“设备状态”保存到数据结构中再发送到目的端，目的端需要从接收到的数据结构中恢复出源端设备状态。
由于硬件设计缺陷，部分legacy设备的寄存器可能存在只读、只写的情况，这就导致状态无法100%复制，
而且由于一些软件框架上的设计缺陷，很多硬件设别不支持“上下文切换”（包括MMIO等，DMA buffer等资源），
这也最终会导致硬件状态无法从源端拷贝到目的端。

* 挑战3：当前几乎所有的硬件平台还不支持DMA脏页跟踪

在Pre-Copy阶段，物理设备发起的DMA操作是通过IOMMU/SMMU页表进行翻译的，
然而当下IOMMU/SMMU的DMA操作还不持支持脏页跟踪，也就是页表并没有Acces Bit和Dirty Bit等硬件支持。
缺乏DMA脏页硬件标脏，会导致很大的问题，以为在内存迭代拷贝阶段，
设备会通过DMA发起写虚拟机物理内存操作，而我们在查询脏页的时候又无法察觉哪些页被写了，
这就导致这部分脏页无法同步过去，无法保证源端和目的端内存的一致性，最终会导致虚拟机异常。
(备注：从Intel最新的VT-d spec来看，新的Intel平台上的IOMMU已经开始支持IOMMU页表Access Bit和Dirty Bit，
估计是Intel已经看到了DMA脏页硬件标脏的重要性，但目前该功能在哪一代CPU上开始支持还不明确，至少截至目前还是不支持的)

上述几个难点，导致直通虚拟机在热迁移和热升级场景成为特例，比较难以处理。
如何搞定直通热迁移，目前应该是业界比较热点的一个努力方向。
从目前来看，直通设备热迁移方案就两种，即mdev方案和SRIOV方案，
对于mdev方案本文选取了Intel GVT-g热迁移方案作为介绍，
对于SRIOV方案本文选取了Intel X710网卡的直通热迁移方案作为介绍。

## 1. Intel GVT-g 直通热迁移方案

Intel GVT-g是业界第一个GPU全虚拟化方案，也是目前唯一开源（Nvidia不开源）且较为稳定的GPU全虚拟化方案。
Intel GVT-g基于mdev实现了受控的直通，在具备良好性能的同时保证了可扩展性和隔离性。
在Intel GVT-g中Intel GPU的GGTT和PGTT都通过影子页表方式实现，GGTT页表则在虚拟机之间通过切换分时共享。
GVT-g中还实现了一个**指令扫描器**来扫描所有GGTT中缓存中的GPU指令，确保不会访问非法地址。
同时，最牛叉的地方在于Intel GVT-g中实现了GPU调度和CPU调度相互分离机制，
这是一种时间片轮转和按需调度相互结合的方式。
不得不说，Intel还是掌握了核心科技！

为了分析Intel GVT-g直通热迁移方案，我们分析了一下整个Intel GVT-g框架的流程。
Intel GVT-g要去硬件平台是5代酷睿以上（桌面版）和至强系列（服务器）V4以上的芯片架构。

首先，简单看下Intel显卡驱动加载流程，这里是一堆框架相关的初始化操作，驱动加载的入口是`i915_driver_hw_probe`：
```c
i915_driver_hw_probe    显卡驱动加载入口
	--> intel_device_info_runtime_init
	--> i915_ggtt_probe_hw   初始化GGTT相关信息，包括ggtt基地址，大小等信息
		--> gen8_gmch_probe   ggtt存放在BAR2里面
	--> i915_kick_out_firmware_fb  没看太懂，好像是是删除了firmware的framebuffer
	--> vga_remove_vgacon          这里将默认的vga console给关掉了
	--> i915_ggtt_init_hw 
		--> ggtt_init_hw (i915_address_space_init, arch_phys_wc_add)
	--> intel_gvt_init 初始化 GVT 组件，drm_i915_private
		--> intel_gvt_init_device
			--> init_device_info
			--> intel_gvt_setup_mmio_info
			--> intel_gvt_init_engine_mmio_context
			--> intel_gvt_load_firmware   加载固件
			--> intel_gvt_init_irq 初始化 GVT-g 中断模拟子系统，注意：vGPU的中断是模拟的？
			--> intel_gvt_init_gtt 初始化全局地址图形地址翻译表
			--> intel_gvt_init_workload_scheduler 调度器初始化，注意GPU有多个渲染引擎，都支持上下文切换
			--> intel_gvt_init_sched_policy 调度器初始化
			--> intel_gvt_init_cmd_parser 这个不简单，初始化GPU渲染器的命令解析器（有点复杂，要好好看看）
			--> init_service_thread 
			--> intel_gvt_init_vgpu_types 
                            // 初始化vGPU类型，根据SKU芯片资源不同，最多有4种规格的vGPU，最多支持8个vGPU
			--> intel_gvt_init_vgpu_type_groups 创建不同vGPU Type的属性组
			--> intel_gvt_create_idle_vgpu      空闲的vGPU实例
			--> intel_gvt_debugfs_init          create debugfs，方便调试
	--> intel_opregion_setup  没看懂这里啥意思？	
```
从上面的分析我们可以看到，Intel GPU初始化的时候获取了GGTT的相关信息并对GGTT进行了初始化，
然后初始化了vGPU相关的东东，其中包括设置MMIO，初始化MMIO上下文，初始化vGPU的模拟中断，
初始化vGPU的GGTT，初始化调度器和参数，初始化cmdparser（GPU指令解析器），初始化server线程，
初始化vGPU类型信息，初始化了一个idle状态的的vCPU实例，以及调试相关的debugfs。

接着来看下Intel vGPU的mdev设备模型，我们知道mdev设备模型中要求提供Userspace API接口，
`mdev_parent_ops`作为mdev sysfs回调，负责mdev实例的创建和销毁等操作，是vGPU对用户态的接口。
加载kvmgt.ko的时候，会调用`kvmgt_host_init`注册设备。
```c
static struct mdev_parent_ops intel_vgpu_ops = {
	.mdev_attr_groups       = intel_vgpu_groups,
	.create			= intel_vgpu_create,
	.remove			= intel_vgpu_remove,

	.open			= intel_vgpu_open,
	.release		= intel_vgpu_release,

	.read			= intel_vgpu_read,
	.write			= intel_vgpu_write,
	.mmap			= intel_vgpu_mmap,
	.ioctl			= intel_vgpu_ioctl,
};

insmod kvmgt.ko
kvmgt_init
	--> intel_gvt_register_hypervisor
		--> intel_gvt_hypervisor_host_init
			--> kvmgt_host_init
				--> mdev_register_device(dev, &intel_vgpu_ops)
```

通过sysfs创建vCPU的mdev实例，用户态程序echo "$UUID" > /sys/class/mdev_bus/$type_id/create里面，
这里会调用到`intel_vgpu_create`来创建一个vGPU实例。
```c
    intel_vgpu_create
    	--> intel_gvt_ops->gvt_find_vgpu_type -> intel_gvt_find_vgpu_type 根据echo进来的字符串，找到对应的vGPU Type
	--> intel_gvt_ops->vgpu_create -> intel_gvt_create_vgpu （创建intel_vgpu实例）
	--> mdev_set_drvdata(mdev, vgpu)  // 将driver_data赋值为创建的intel_vgpu对象
      
    重点分析intel_gvt_create_vgpu
    intel_gvt_create_vgpu
        --> vgpu = vzalloc(sizeof(*vgpu))	// 分配一个vGPU结构体
        --> vgpu->id = idr_alloc()		// 分配一个唯一的id
        --> intel_vgpu_init_cfg_space		// 初始化配置空间
        --> intel_vgpu_init_mmio   // 初始化MMIO，intel_gvt_init_device里面给mmio_size = 2MB，给MMIO赋默认值
        --> intel_vgpu_alloc_resource		// 好复杂的，vGPU各种资源分配
        --> intel_vgpu_init_display
        --> intel_vgpu_setup_submission		
        --> intel_vgpu_init_sched_policy
        --> intel_gvt_hypervisor_set_opregion
```

## 2.0 SRIOV直通热迁移框架

https://patchwork.kernel.org/cover/11274097/

## TO BE CONTINUED

## Refs

1. [Intel GVT-g Reference](https://projectacrn.github.io/1.1/developer-guides/hld/hld-APL_GVT-g.html#audience)
1. [https://patchwork.kernel.org/cover/11274097/](https://patchwork.kernel.org/cover/11274097/)

