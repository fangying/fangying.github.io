Title:  QEMU Live Migration Internal
Date: 2020-2-23 23:00
Modified: 2020-2-23 23:00
Tags: live-migration
Slug: live-migration
Status: draft
Authors: Yori Fang
Summary: QEMU live migration


虚拟机热迁移技术（VM live migration）是指在虚拟机正在运行的时候，
在不影响虚拟机正常业务执行的情况下将虚拟机从一个物理机迁移到另外一台物理机上的一种技术方案。
经过多年的发展，虚拟机热迁移技术逐渐成熟，已经在云计算IaaS运维里面得到大规模应用和广泛实践。
热迁移技术可以说是整个虚拟化技术中心最为复杂的特性，其中涉及的知识点相当多。
本文旨在整理一下和虚拟机热迁移相关的一些技术细节，为对虚拟化感兴趣的人提供一些参考，
同时也作为我个人的知识学习和整理。

本文主要包含了以下几个关于热迁移的Topic：

1. qemu-kvm虚拟机热迁移框架
2. libvirt热迁移流程
3. qemu热迁移关键流程
4. kvm热迁移标脏，pml，大页内存
5. multifd热迁移，压缩热迁移，热迁移限速
6. userfault和postcopy
7. vhost-user脏页跟踪

**本文由于涵盖面较大，可能有点长，也有点啰嗦，我猜测一般人没有那个耐心看完的，除非你不是一般人**。

## 1. qemu-kvm虚拟机热迁移原理和框架

基本流程：
Libvirt，qemu，kvm

基本数据结构：
SaveStateEntry, SaveVMHandler

VMState 

https://wiki.qemu.org/File:Postcopyflow.png

kvm标脏流程，pml原理，大页内存如何标脏，multifd，极速热迁移

## 2. Libvirt热迁移

根据通信控制模式的不同，Libvirt热迁移可以分为3种类型：

* 受控直接热迁移（Managed direct migration）；
* 受控点对点热迁移（Managed peer to peer migration）；
* 无控制直接迁移（Unmanaged direct migration）

受控直接热迁移由libvirt客户端直接管理，客户端与两端的数据libvirt连接，
中间发生异常本地libvirtd反馈给客户端，再由客户端通知对端。
这种迁移方式的缺点在于libvirt客户端crash或者与libvirtd断开连接后，
造成迁移失败并且容易残留。

受控点对点迁移由libvirtd直接交互管理，libvirt客户端通知远端libvirtd发起热迁移，
之后由远端libvirtd与目的端libvirtd建立连接，并管理整个迁移过程。
这种迁移方式的优点在于libvirt客户端crash或者与源端libvirtd连接断开后，热迁移仍旧能够正常完成。

无控制直接热迁移则由Hypervisor上层管理程序完成控制，libvirt客户端通过Hypervisor管理程序初始化
迁移，之后由Hypervisor管理程序自行控制与目的端的迁移流程。

Libvirt迁移也一直不断在重构和演进当中，目前最完整的v3协议一共包含了5个阶段：

* Begin阶段    （源端）
    - 生成需要传递给对端的xml
    — 生成需要传递给对端的cookie
* Prepare阶段  （目的端）
    - 为接受即将到来的VM做准备
    - 生成传递给源端的可选cookie
* Perform阶段  （源端） 
    - 开始迁移，并等待传送完成
    - 生成传递给对端的可选cookie
* Finish阶段   （目的端）
    - 等待接受完成，并检查虚拟机状态
    - 如果迁移失败则kill虚拟机，否则resume虚拟机
* Confirm     （源端）
    - 如果失败则resume虚拟机，否则kill虚拟机

## 3. QEMU热迁移

当libvirt下发qmp热迁移命令`qmp_migrate`的时候，QEMU会创建热迁移线程。

### 3.1 Source Behavior

Source下发热迁移，通过qmp命令来触发：
```
qmp_migrate 
    -> tcp_start_outgoing_migration 
        -> socket_start_outgoing_migration 
            -> migration_fd_connect
                -> multifd_save_setup
                -> qemu_thread_create
                    -> migration_thread
```
QEMU 热迁移线程`migration_thread`负责整个QEMU热迁移的流程。
按照热迁移功能节点，可以划分成4个Step：

* Step1：初始化阶段，发送初始化消息和热配参数到目的端；
* Step2：setup准备阶段，创建脏页位图并开始全局标脏（包括内存和块设备的）；
* Step3：内存、块设备迭代拷贝阶段；
* Step4：vCPU暂停和设备状态保存。


```c
migration_thread 
{
    Step1: qemu_savevm_state_header  发送魔术字0x5145564d和热迁移配置参数到目的端
	
    Step2: qemu_savevm_state_setup	 热迁移准备阶段
    {
        FOREACH SaveStateEntry
            save_section_header          添加section header

            /* 内存传输准备阶段，定义好savevm_ram_handlers*/
            ram_save_setup
                ram_init_all {
                    ram_init_bitmaps    初始化每个RAMblock的bitmap
                    memory_global_dirty_log_start    开启全局标脏
                    migration_bitmap_sync_precopy    开启内存标脏
                        RAMBLOCK_FOREACH_MIGRATABLE 遍历所有的migratable RAMBlock
                        发送RAMBlock信息	
		    }


		/* 存储传输准备阶段 */	block_save_setup
		init_blk_migration
			初始化blk_mig_state，统计磁盘块信息
		set_dirty_tracking
			创建磁盘脏页位图

		save_section_footer          //添加section footer
    }
		
    Step3: 内存/磁盘迭代拷贝传输阶段
    while migraiton_is_active {
    	migration_iteration_run /* 每一轮迭代先查询脏页信息，然后做一轮传送 */
            qemu_savevm_state_pending   //计算需要传输的剩余数据大小
	            ops->save_live_pending	//脏页位图同步，这个过程中要拿到QEMU大锁的
            qemu_savevm_state_iterate
                FOREACH SaveStateEntry(savevm_state)
                    ops->save_live_iterate
                    // 发送内存数据，存储数据到目的端
            migration_rate_limit /* 热迁移限速，QOS */
	        // if pending_size < threshold_size 剩下的内容不多了
            migration_completion  // 进入热迁移完成阶段
    }
	
    Step4: CPU停机和设备状态保存
    migraiton_completion {
        vm_stop_force_state -> RUN_STATE_FINISH_MIGRATE  // 运行状态切换，强制停机
           vm_stop
              do_vm_stop    /* 将vcpu都pause住，并且将没有落盘的BlockIO处理完 */
        qemu_savevm_state_complete_precopy   /* 进入precopy的完成阶段 */
            cpu_synchronize_all_states       /* 同步vcpu的状态* /
	    qemu_savevm_state_complete_precopy_non_iterable    // 对于precopy的设备状态同步
            {
                FOREACH SaveStateEntry {
                /* 每个qdev设备在realize的时候会注册自己的handler，device_set_realized */
                    vmstate_save                             
                }
            }
    }
}
```

#### 3.1.1内存、块设备迭代拷贝



#### 3.1.2设备状态的保存和恢复

这里以virtio-blk设备为例，分析一下virtio-blk设备状态保存的具体实现。
设备状态是在停机后再保存,而且很明显也不需要迭代，qemu热迁移代码是一直在不断重构的，
现在是在`qemu_savevm_state_complete_precopy_non_iterable`函数中实现。

`qemu_savevm_state_complete_precopy_non_iterable`中是个foreach循环，
会遍历每个设备注册进来的`SaveStateEntry`，调用设备自己注册的回调函数去保存设备
自己要保存的状态。每个设备状态是用一个预定义好的`json`对象格式来保存的，其大致结构为：
```javascript
{
  "page_size": 4096,
  "devices": [
    {
      "name": "virito-blk",
      "instance_id": 0,
      "vmsd_name": "virtio-blk",
      "version": 2,
      "fields": [
        {
        }
      ]
    }
  ]
}
```
如果还是不太clear，这里有一份实例可以参考一下：

https://github.com/qemu/qemu/blob/master/tests/vmstate-static-checker-data/dump1.json

其中`devices`是一个数组，每个设备是其中的一个数组元素。
对于每个`device`又定义了`name`,`instance_id`,`version`等属性，
每个设备有个`VMStateField`类型的`fileds`数组，用来保存设备要保存的内容，其内容也是转换为json对象格式。

有个关键的函数叫做`vmstate_save`，是单个设备状态保存的入口函数。

```c
migration_completion
-> qemu_savevm_state_complete_precopy
-> qemu_savevm_state_complete_precopy_non_iterable {
    QTAILQ_FOREACH savevm_state.handlers {    /* 这里是循环遍历每个qdev设备，调用设备*/
        vmstate_save { // 保存virtio-blk设备状态，有些legacy设备没有使用vmsd，即old_style
            vmstate_save_old_style
	    vmstate_save_state    /* 使用vmsd来保存设备状态的设备 */
	        -> vmstate_save_state_v
	            -> virtio_device_put
	            -> virtio_save
	                -> virtio_blk_save_device
        }
    }
}

virtio-blk设备注册了VMStateDescription来保存要保存的设备状态。
在hw/block/virtio-blk.c
static const VMStateDescription vmstate_virtio_blk = {                                                                                                            
    .name = "virtio-blk",                                                       
    .minimum_version_id = 2,                                                    
    .version_id = 2,                                                            
    .fields = (VMStateField[]) {                                                
        VMSTATE_VIRTIO_DEVICE,                                                  
        VMSTATE_END_OF_LIST()                                                   
    },                                                                          
};
```

重点看下`vmstate_save`的关键实现，这个函数的主要功能就是将设备对象的状态保存下来。
如果设备对象的vmsd有`pre_save`这个hook，先调用`pre_save`执行设备状态保存之前的预处理，
接着遍历设备对象预定义的所有`field`，根据`filed`的类型（指针类型，结构体类型，其他基础类型）
按照特定的格式保存设备对象的状态到目的端，这个过程中会调用`field`自己的的`put`方法来保存。
```c
struct VMStateInfo {
    const char *name;
    int (*get)(QEMUFile *f, void *pv, size_t size, const VMStateField *field);
    int (*put)(QEMUFile *f, void *pv, size_t size, const VMStateField *field,
               QJSON *vmdesc);
};
```
再接着如果有`subsection`也保存一下，最后调用`post_save`执行设备状态保存后的一些处理工作。

```c
int vmstate_save_state_v(QEMUFile *f, const VMStateDescription *vmsd,
                         void *opaque, QJSON *vmdesc, int version_id)
{
    int ret = 0;
    const VMStateField *field = vmsd->fields;

    trace_vmstate_save_state_top(vmsd->name);

    if (vmsd->pre_save) {
        ret = vmsd->pre_save(opaque);
        trace_vmstate_save_state_pre_save_res(vmsd->name, ret);
        if (ret) {
            error_report("pre-save failed: %s", vmsd->name);
            return ret;
        }
    }

    if (vmdesc) {
        json_prop_str(vmdesc, "vmsd_name", vmsd->name);
        json_prop_int(vmdesc, "version", version_id);
        json_start_array(vmdesc, "fields");
    }

    while (field->name) {
        if ((field->field_exists &&
             field->field_exists(opaque, version_id)) ||
            (!field->field_exists &&
             field->version_id <= version_id)) {
            void *first_elem = opaque + field->offset;
            int i, n_elems = vmstate_n_elems(opaque, field);
            int size = vmstate_size(opaque, field);
            int64_t old_offset, written_bytes;
            QJSON *vmdesc_loop = vmdesc;

            trace_vmstate_save_state_loop(vmsd->name, field->name, n_elems);
            if (field->flags & VMS_POINTER) {
                first_elem = *(void **)first_elem;
                assert(first_elem || !n_elems || !size);
            }
            for (i = 0; i < n_elems; i++) {
                void *curr_elem = first_elem + size * i;
                ret = 0;

                vmsd_desc_field_start(vmsd, vmdesc_loop, field, i, n_elems);
                old_offset = qemu_ftell_fast(f);
                if (field->flags & VMS_ARRAY_OF_POINTER) {
                    assert(curr_elem);
                    curr_elem = *(void **)curr_elem;
                }
                if (!curr_elem && size) {
                    /* if null pointer write placeholder and do not follow */
                    assert(field->flags & VMS_ARRAY_OF_POINTER);
                    ret = vmstate_info_nullptr.put(f, curr_elem, size, NULL,
                                                   NULL);
                } else if (field->flags & VMS_STRUCT) {
                    ret = vmstate_save_state(f, field->vmsd, curr_elem,
                                             vmdesc_loop);
                } else if (field->flags & VMS_VSTRUCT) {
                    ret = vmstate_save_state_v(f, field->vmsd, curr_elem,
                                               vmdesc_loop,
                                               field->struct_version_id);
                } else {
                    ret = field->info->put(f, curr_elem, size, field,
                                     vmdesc_loop);
                }
                if (ret) {
                    error_report("Save of field %s/%s failed",
                                 vmsd->name, field->name);
                    if (vmsd->post_save) {
                        vmsd->post_save(opaque);
                    }
                    return ret;
                }

                written_bytes = qemu_ftell_fast(f) - old_offset;
                vmsd_desc_field_end(vmsd, vmdesc_loop, field, written_bytes, i);

                /* Compressed arrays only care about the first element */
                if (vmdesc_loop && vmsd_can_compress(field)) {
                    vmdesc_loop = NULL;
                }
            }
        } else {
            if (field->flags & VMS_MUST_EXIST) {
                error_report("Output state validation failed: %s/%s",
                        vmsd->name, field->name);
                assert(!(field->flags & VMS_MUST_EXIST));
            }
        }
        field++;
    }

    if (vmdesc) {
        json_end_array(vmdesc);
    }

    ret = vmstate_subsection_save(f, vmsd, opaque, vmdesc);

    if (vmsd->post_save) {
        int ps_ret = vmsd->post_save(opaque);
        if (!ret) {
            ret = ps_ret;
        }
    }
    return ret;
}
```
所以对于virtio-blk设备而言，保存的状态内容大概包括3部分：virtio-blk-pci配置空间信息，virtio-blk-pci队列信息，
还有virtio-blk信息等3个方面。
```c
virtio_save {
    if (k->save_config) {
        virtio_pci_save_config()   /* 保存virtio-blk-pci设备的配置空间 */
    }
    if (k->save_queue) {
        virtio_pci_save_queue()    /* 保存virtio-pci-blk保存队列 */
    }

    if (vdc->save) {
        virtio_blk_save_device()    /* 保存virtio-blk信息 */
    }
    
    vmsd->pre_save
}
```
为了搞清楚每个设备到底保存了哪些东西，我打开了qemu在vmsate_save里面的trace，得到了一份trace日志。
日志详细记录了每个设备保存了哪些field，这个文件有点大，raw格式打开可以查看：[vmstate_tracelog.txt](../images/vmstate_tracelog.txt)
从文件的头部很明显可以看出save了一个configuration结构（虚拟机配置文件）和一个timer结构，
其中timer有cpu_ticks_offset,unused,cpu_clock_offset登几个field。
```
vmstate_save_state_top 0.000 pid=469556 idstr=b'configuration'
vmstate_save_state_pre_save_res 5.059 pid=469556 name=b'configuration' res=0x0
vmstate_save_state_loop 1.754 pid=469556 name=b'configuration' field=b'len' n_elems=0x1
vmstate_save_state_loop 2.217 pid=469556 name=b'configuration' field=b'name' n_elems=0x1

vmstate_save_state_top 1456114.395 pid=469556 idstr=b'timer'
vmstate_save_state_loop 1.911 pid=469556 name=b'timer' field=b'cpu_ticks_offset' n_elems=0x1
vmstate_save_state_loop 2.444 pid=469556 name=b'timer' field=b'unused' n_elems=0x1
vmstate_save_state_loop 1.046 pid=469556 name=b'timer' field=b'cpu_clock_offset' n_elems=0x1
```

虚拟机状态发生改变的时候回调函数`vm_state_notify`,


## 3.2 Destination Behavior

```
qmp_cmd_name: qmp_capabilities, arguments: {}                                   
qmp_cmd_name: query-migrate-capabilities, arguments: {}                         
qmp_cmd_name: migrate-set-capabilities, arguments: {"capabilities": [{"state": true, "capability": "events"}]}
qmp_cmd_name: query-chardev, arguments: {}                                      
qmp_cmd_name: query-hotpluggable-cpus, arguments: {}                            
qmp_cmd_name: query-cpus-fast, arguments: {}                                    
qmp_cmd_name: query-iothreads, arguments: {}                                    
qmp_cmd_name: balloon, arguments: {"value": 34359738368}                        
qmp_cmd_name: query-migrate-parameters, arguments: {}                           
qmp_cmd_name: migrate-set-capabilities, arguments: {"capabilities": [{"state": false, "capability": "xbzrle"}, {"state": false, "capability": "auto-converge"}, {"state": false, "capability": "rdma-pin-all"}, {"state": false, "capability": "postcopy-ram"}, {"state": false, "capability": "compress"}, {"state": false, "capability": "pause-before-switchover"}, {"state": true, "capability": "late-block-activate"}, {"state": true, "capability": "multifd"}]}
qmp_cmd_name: migrate-set-parameters, arguments: {"multifd-channels": 4, "tls-creds": "", "tls-hostname": ""}
qmp_cmd_name: migrate-incoming, arguments: {"uri": "tcp:[::]:49152"}
```

```c
qmp_migrate_incoming
    -> qemu_start_incoming_migration
        -> tcp_start_incoming_migration
            -> socket_start_incoming_migration
                -> socket_accept_incoming_migration
                    -> migration_channel_process_incoming
                        -> migraiton_incoming_setup
                            -> migraiton_incoming_process
                                -> process_incoming_migration_co
```

## 4. Conclusion

## References

1. https://www.qemu.org/docs/master/system/index.html