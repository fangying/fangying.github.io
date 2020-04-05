Title: Linux Memory Management Overview 
Date: 2018-12-14 23:00 
Modified: 2018-12-14 23:00 
Tags: linux-mm
Slug: linux-mm 
Status: draft 
Authors: Yori Fang 
Summary: Linux MM Overvuew

本文的目的是记录一下Linux内存管理的相关内容，用来督促自己主动学习一下内存管理的知识内容，加油！

## 0.Linux内存管理的知识点

《深入Linux内核架构》一书中将Linux内存管理的相关知识点归纳为5个Topic，即：

1. 内存中的物理内存页管理机制；
1. 分配的大块内存的伙伴系统；
1. 分配较小块内存的slab, slub和slob分配器；
1. 分配非连续性内存块的vmalloc机制；
1. 进程的虚拟内存管理。


（kernel -> Buddy System, Swap[zram, zcache], 虚实映射， RMAP， huge page， ZONE & LRU）
硬件结构：MMU，L1Cache，内存一致性

Linux内存管理大图
https://www.cnblogs.com/pengdonglin137/p/4382403.html

## 1.物理内存管理

NUMA模型
内存结点：每个节点关联到系统的一个处理器上，再内核中表现为pg_data_t实例
内存域：每个内存结点又划分为不同的区域 (DMA NORMAL HIGHMEM)，一个结点最多由3个内存域构成。
页帧：代表系统内存的最小单位，标准大小是4KB，每个页帧对应一个page实例

初始化内存管理系统：

start_kernel -> setup_arch -> build_all_zonelists -> setup_percpu_areas -> mm_init -> setup_per_cpu_pageset

```c
struct memblock {
	phys_addr_t current_limit;
	struct memblock_type memory;
	struct memblock_type reserved;
};
```
体系结构相关的初始化
当内核已经载入内存，初始化的汇编执行后，内核需要执行哪些特定的步骤？
```
start_kernel
  -> setup_arch
  -> setup_per_cpu_areas
  -> build_all_zonelists
  -> mem_init
  -> setup_per_cpu_pageset
```

```c
setup_arch -> setup_memory_map (从bios读取可用内存情况) -> init_memory_mapping（建立直接内存映射）
-> initmem_init
  x86_numa_init -> add_active_range
  setup_bootmem_allocator
-> paging_init
  pagetable_init
  zone_sizes_init -> free_area_init_nodes
```

注册活动的内存区域

add_active_range ： 在全局变量early_node_map中注册内存区域，相关数据结构

### 1.2 Linux内核初期内存管理

带着下面几个问题来学习：

1. 在内核启动的时候，Linux内核是如何知道系统中多有多大的内存空间？
1. 在内核启动初期，Buddy分配器还未工作的时候，Linux是如何管理物理内存的？

**内核是到底是如何获取物理内存的拓扑结构的呢？**
从硬件的角度来看，随机存储器（Random Access Memory, RAM）是CPU直接交换数据的内部存储器。
现在绝大部分计算机都使用DDR（Dual Data Rate SDRAM）设备作为存储器。
DDR的初始化一般是又BIOS或者boot loader来完成的，然后BIOS或者boot loader将DDR的大小传递给内核。
在系统刚启动的时候RAM还处于不可用的状态，**因为系统最早都是从ROM中启动的**。
在X86平台上BIOS通过E820表报告系统物理内存情况，在ARM64平台上通过DTS来报告物理内存的大小给OS。


在内核刚启动的时候，伙伴系统还没开始工作，如何管理内存？
答案是`memblock`分配器（老的内核版本上使用的是`bootmem`分配器，现在由memblock分配器取而代之）。
`memblock`的内核补丁由[Yinghai Lu提供](https://lkml.org/lkml/2010/7/13/68)。

在进一步介绍`memblock`之前，有必要先了解下Linux内核启动初期系统内存的使用情况[1](https://blog.csdn.net/modianwutong/article/details/53162142)：
首先，内存中的某些部分是永久的分配给内核的，
比如内核代码段和数据段，ramdisk和fdt占用的空间等，它们是系统内存的一部分，但是不能被侵占，也不参与内存分配，称之为静态内存；
其次，GPU，Camera等都需要预留大量连续内存，这部分内存平时不用，但是系统必须提前预留好，称之为预留内存；
最后，内存的其余部分称之为动态内存，是需要内核管理的宝贵资源；

根据Linux内核启动初期的物理内存分配实际情况，memblock把物理内存划分为若干内存区，每个内存区域由一段连续的内存区间（Region）组成，
按使用类型分别放在memory，reserved和physmem三个集合（数组）中，
memory即动态内存的集合，reserved集合包括静态内存和预留内存，physmem即物理内存集合；

```
/**
 * enum memblock_flags - definition of memory region attributes
 * @MEMBLOCK_NONE: no special request
 * @MEMBLOCK_HOTPLUG: hotpluggable region
 * @MEMBLOCK_MIRROR: mirrored region
 * @MEMBLOCK_NOMAP: don't add to kernel direct mapping
 */
enum memblock_flags {
        MEMBLOCK_NONE           = 0x0,  /* No special request */
        MEMBLOCK_HOTPLUG        = 0x1,  /* hotpluggable region */
        MEMBLOCK_MIRROR         = 0x2,  /* mirrored region */
        MEMBLOCK_NOMAP          = 0x4,  /* don't add to kernel direct mapping */
};

/**
 * struct memblock_region - represents a memory region
 * @base: physical address of the region
 * @size: size of the region
 * @flags: memory region attributes
 * @nid: NUMA node id
 */
struct memblock_region {
        phys_addr_t base;
        phys_addr_t size;
        enum memblock_flags flags;
#ifdef CONFIG_HAVE_MEMBLOCK_NODE_MAP
        int nid;
#endif
};

/**
 * struct memblock_type - collection of memory regions of certain type
 * @cnt: number of regions
 * @max: size of the allocated array
 * @total_size: size of all regions
 * @regions: array of regions
 * @name: the memory type symbolic name
 */
struct memblock_type {
        unsigned long cnt;
        unsigned long max;
        phys_addr_t total_size;
        struct memblock_region *regions;
        char *name;
};

/**
 * struct memblock - memblock allocator metadata
 * @bottom_up: is bottom up direction?
 * @current_limit: physical address of the current allocation limit
 * @memory: usabe memory regions
 * @reserved: reserved memory regions
 * @physmem: all physical memory
 */
struct memblock {
        bool bottom_up;  /* is bottom up direction? */
        phys_addr_t current_limit;
        struct memblock_type memory;
        struct memblock_type reserved;
#ifdef CONFIG_HAVE_MEMBLOCK_PHYS_MAP
        struct memblock_type physmem;
#endif
};
```
内核还定义了一个memblock类型的全局变量，并为其做了初始化，如下：
```c
struct memblock memblock __initdata_memblock = {
        .memory.regions         = memblock_memory_init_regions,
        .memory.cnt             = 1,    /* empty dummy entry */
        .memory.max             = INIT_MEMBLOCK_REGIONS,
        .memory.name            = "memory",

        .reserved.regions       = memblock_reserved_init_regions,
        .reserved.cnt           = 1,    /* empty dummy entry */
        .reserved.max           = INIT_MEMBLOCK_RESERVED_REGIONS,
        .reserved.name          = "reserved",

#ifdef CONFIG_HAVE_MEMBLOCK_PHYS_MAP
        .physmem.regions        = memblock_physmem_init_regions,
        .physmem.cnt            = 1,    /* empty dummy entry */
        .physmem.max            = INIT_PHYSMEM_REGIONS,
        .physmem.name           = "physmem",
#endif

        .bottom_up              = false,
        .current_limit          = MEMBLOCK_ALLOC_ANYWHERE,
};
```
memblock的一些基本操作：
```
void memblock_allow_resize(void);
int memblock_add_node(phys_addr_t base, phys_addr_t size, int nid);
int memblock_add(phys_addr_t base, phys_addr_t size);
int memblock_remove(phys_addr_t base, phys_addr_t size);
int memblock_free(phys_addr_t base, phys_addr_t size);
static inline void * __init memblock_alloc(phys_addr_t size,  phys_addr_t align);
int memblock_reserve(phys_addr_t base, phys_addr_t size);
void memblock_trim_memory(phys_addr_t align);
bool memblock_overlaps_region(struct memblock_type *type,
		 phys_addr_t base, phys_addr_t size);
int memblock_mark_hotplug(phys_addr_t base, phys_addr_t size);
int memblock_clear_hotplug(phys_addr_t base, phys_addr_t size);
int memblock_mark_mirror(phys_addr_t base, phys_addr_t size);
int memblock_mark_nomap(phys_addr_t base, phys_addr_t size);
int memblock_clear_nomap(phys_addr_t base, phys_addr_t size);
```
内核在早期的初始化阶段，体系结构相关的初始化流程里会调用`memblock_add`和`memblock_add_node`
来添加内存layout信息。当`memblock`分配器建立起内存映射关系后，
就可以调用`memblock_phys_alloc`和`memblock_alloc`来分配物理内存和虚拟内存。
当内核启动到一定阶段之后，`memblock`分配器不再被需要，转而开始使用`buddy`分配器，
这时候内核会调用`mem_init`去释放所有的内存给`buddy page allocator`。

在X86平台上，BIOS通过E820 Table的方式向OS报告内存映射信息，OS通过调用BIOS function来从表里面get信息。
注：在IBM PC compatible计算机系统上，BIOS通过interrupt calls方式向bootloader提供一些必要的硬件信息，
在bootload阶段或者kernel启动早期的**实模式阶段**，都可以通过interrupt call（实际上是软中断）来调用bios接口[1](https://en.wikipedia.org/wiki/BIOS_interrupt_call)，利用这些接口操作系统可以完成诸多功能，
例如：查询内存映射图的调用是：INT 0x15, EAX = 0xE820。
在X86上Linux内核初始化阶段`setup_arch`（arch/x86/kernel/setup.c）里会为系统预留特定的内存区域，
并调用`e820__memory_setup` -> `memblock_alloc`等操作来完成`memblock`的初始化，
建立起早期的内核内存映射视图。

在ARM64平台上，通过FDT方式呈现去描述系统的内存映射关系。
扫描内存主要流程在是：setup_arch()->setup_machine_fdt()->early_init_dt_scan()->early_init_dt_scan_memory()
建立`memblock`内存映射的流程主要是在函数`arm64_memblock_init`里。


## 2.分配大块内存的伙伴系统

memblock分配器替代了bootmem分配器。

页表映射初始化： paging_init
paging_init负责建立只能用于内核的页表，用户空间无法访问。（__PAGE_OFFSET）

内存域节点数据初始化
该函数主要用来初始化素有pg_data_t和zone数据结构，参数max_zone_pfn记录了每个域最大pfn。节点的信息通过查找memblock表？

内存域初始化： __build_all_zonelists

该函数的主要工作是对活动的每个结点调用build_zonelists 建立内存域列表，build_zonelists建立内存分配的列表

伙伴系统的结构
free_area[MAX_ORDER] -> 

伙伴系统的初始化

伙伴系统的初始化发生在节点数据结构的初始化的时候，但此时空闲的内存为0，说明还不能使用，直到memblock分配器停用的时候。
free_area_init_node -> free_area_init_core -> init_currently_empty_zone -> zone_init_free_lists

memblock 分配器的停用 （https://blog.csdn.net/modianwutong/article/details/53162142） 
memblock分配器停用后会释放所有的普通内存，返回给伙伴系统，高端内存单独 有独立的函数进行释放

mm_init ->mem_init ->free_all_bootmem -> __free_pages -> set_highmem_pages_init -> __free_pages

碎片问题如何解决？ 不可以移动页，可回收页，可移动页

分配器API

页分配流程：
```
  __alloc_pages_nodemask
    -> first_zones_zonelist
      -> get_page_from_freelist
        -> __alloc_pages_slowpath
          -> wake up kswapd -> get_page_from_freelist
          -> mem compress -> get_page_from_freelist
          -> mem claim -> get_page_from_freelist
          -> kill oom -> get_page_from_freelist -> sleep a while
```

get_page_from_freelist 分配内存的实际函数，该函数遍历zonelist链表上的所有内存域按照优先顺序查找有没有空闲页，有就分配。
检查有没有内存页的函数 __zone_watermark_ok 
```c
/*
 * Return true if free base pages are above 'mark'. For high-order checks it
 * will return true of the order-0 watermark is reached and there is at least
 * one free page of a suitable size. Checking now avoids taking the zone lock
 * to check in the allocation paths if no pages are free.
 */
bool __zone_watermark_ok(struct zone *z, unsigned int order, unsigned long mark,
			 int classzone_idx, unsigned int alloc_flags,
			 long free_pages)
{
	long min = mark;
	int o;
	const bool alloc_harder = (alloc_flags & (ALLOC_HARDER|ALLOC_OOM));

	/* free_pages may go negative - that's OK */
	free_pages -= (1 << order) - 1;

	if (alloc_flags & ALLOC_HIGH)
		min -= min / 2;

	/*
	 * If the caller does not have rights to ALLOC_HARDER then subtract
	 * the high-atomic reserves. This will over-estimate the size of the
	 * atomic reserve but it avoids a search.
	 */
	if (likely(!alloc_harder)) {
		free_pages -= z->nr_reserved_highatomic;
	} else {
		/*
		 * OOM victims can try even harder than normal ALLOC_HARDER
		 * users on the grounds that it's definitely going to be in
		 * the exit path shortly and free memory. Any allocation it
		 * makes during the free path will be small and short-lived.
		 */
		if (alloc_flags & ALLOC_OOM)
			min -= min / 2;
		else
			min -= min / 4;
	}


#ifdef CONFIG_CMA
	/* If allocation can't use CMA areas don't use free CMA pages */
	if (!(alloc_flags & ALLOC_CMA))
		free_pages -= zone_page_state(z, NR_FREE_CMA_PAGES);
#endif

	/*
	 * Check watermarks for an order-0 allocation request. If these
	 * are not met, then a high-order request also cannot go ahead
	 * even if a suitable page happened to be free.
	 */
	if (free_pages <= min + z->lowmem_reserve[classzone_idx])
		return false;

	/* If this is an order-0 request then the watermark is fine */
	if (!order)
		return true;

	/* For a high-order request, check at least one suitable page is free */
	for (o = order; o < MAX_ORDER; o++) {
		struct free_area *area = &z->free_area[o];
		int mt;

		if (!area->nr_free)
			continue;

		for (mt = 0; mt < MIGRATE_PCPTYPES; mt++) {
			if (!list_empty(&area->free_list[mt]))
				return true;
		}

#ifdef CONFIG_CMA
		if ((alloc_flags & ALLOC_CMA) &&
		    !list_empty(&area->free_list[MIGRATE_CMA])) {
			return true;
		}
#endif
		if (alloc_harder &&
			!list_empty(&area->free_list[MIGRATE_HIGHATOMIC]))
			return true;
	}
	return false;
}
```

寻找伙伴：当释放一块内存时，系统需要判断该内存块是否能和其他伙伴系统合并成更高阶的内存。
```
	while(order < MAX_ORDER - 1) {
		buddy_idx = __find_buddy_index
		buddy = page + xxx
	}
	
	__find_buddy_index
```

内核中不连续页的分配 vmalloc
* vmalloc用于分配虚拟地址连续，物理地址未必连续的内存，使用标志 ZONE_HIGHMEM，倾向分配高端内存
内核为跟踪哪些子区域被使用哪些内存域空闲，使用vm_struct结构管理映射区域
```

```

内存释放： __free_pages
```
  __free_pages
  	-> single page ?  -> return to per-cpu cache
	-> return to slab system
```

## 3.分配较小块内存的slab, slub和slob分配器

## 4.分配非连续性内存块的vmalloc机制

## 5.进程的虚拟内存管理

https://blog.csdn.net/modianwutong/article/details/53162142

https://www.cnblogs.com/ronnydm/default.html?page=2
