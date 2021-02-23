Title: the vhost protocal
Date: 2019-12-12 23:00
Tags: vhost protocal
Slug: vhost-protocal
Authors: Yori Fang
Summary: the vhost protocal
Status: draft

## 0. vhost protocal

以vhost net为例

前端仍然是virtio-net

struct virtnet_info 定义了virtio-net网卡的信息，一个网卡包含3个队列（控制队列[可以没有]，发送队列和接收队列）。

## 1. vhost net初始化流程分析

virtio模式下：
收包：Hardware => Host Kernel => Qemu => Guest
发包：Guest => Host Kernel => Qemu => Host Kernel => Hardware

Vhost模式下：
收包： Hardware => Host Kernel => Guest
发包： Guest => Host Kernel => Hardware

收包：底层设备通过socket唤醒worker线程调度收报处理函数，接受完成之后写eventfd向虚拟机注入中断。
发包：vCPU退出写eventfd唤醒worker线程调度，调用发包函数发包

关键数据结构，对象抽象： vhost_dev, vhost_net, vhost_poll, vhost_work, vhost_virtqueue

```
struct vhost_dev {
        struct mm_struct *mm;
        struct mutex mutex;
        struct vhost_virtqueue **vqs;
        int nvqs;
        struct eventfd_ctx *log_ctx;
        struct llist_head work_list;
        struct task_struct *worker;
        struct vhost_umem *umem;
        struct vhost_umem *iotlb;
        spinlock_t iotlb_lock;
        struct list_head read_list;
        struct list_head pending_list;
        wait_queue_head_t wait;
        int iov_limit;
        int weight;
        int byte_weight;
}; 
```

tap设备的初始化流程

```c
net_client_init -> net_client_init1 -> net_client_init_fun 
        -> net_init_tap 
                for(i : queues) // 每个queue初始化一个tap设备 
                -> fd = net_tap_init(ifname) //根据传入的ifname，打开/dev/net/tup创建tap设备返回fd
                -> net_init_tap_one(fd)
                        -> vhostfd = open("/dev/vhost-net", O_RDWR) // 打开vhost-net获得驱动fd
                        -> net_tap_fd_init      // 设置tap offload参数，header信息等
                        -> tap_set_sndbuf       // 设置tap发送buffer大小
                        -> vhost_net_init -> vhost_dev_init(vhostfd)  // 重点分析

```

vhost_net初始化流程
```c
virtio_pci_common_write // 写MMIO退出
    -> virtio_set_status 
        -> virtio_net_set_status
            -> virtio_net_vhost_status
                -> vhost_net_start
                    -> vhost_net_start_one
                        -> vhost_dev_start
                        
vhost_dev_start
        -> vhost_dev_set_features 设置feature
        -> vhost_set_mem_table 设置mem table (memslot共享)
        -> vhost_virtqueue_start vring地址共享,创建eventfds消息机制，
            -> virtio_queue_get_desc_addr && vhost_memory_map
            -> virtio_queue_get_avail_addr && vhost_memory_map
            -> virtio_queue_get_used_size && vhost_memory_map
            -> vhost_virtqueue_set_addr
                -> vhost_kernel_set_vring_addr
            -> vhost_set_vring_kick 设置vring_kick fd
            -> vhost_set_vring_call 设置vring_call fd
```

## 2. vhost-net 发包流程分析
发包流程：
```c
iov -> eventfd_kick -> worker 
        -> handle_tx_kick 
        -> handle_tx -> handle_tx_copy
```

随后又会为网卡实例初始化收发包的virtqueue队列，`virtnet_probe` -> `init_vqs` ->  `virtnet_alloc_queues`。

```c
// virtio-net使用内核NAPI（New API）是内核中的网卡收发包统一框架
// NAPI是中断和轮训两种收发包模式的结合，数据量低时采用中断，数据量高时采用轮询。
// 平时是中断方式，当有数据到达时，会触发中断处理函数执行，中断处理函数关闭中断开始处理。
// 如果此时有数据到达，则没必要再触发中断了，因为中断处理函数中会轮询处理数据，直到没有新数据时才打开中断。
// NAPI工作在各大网卡厂商驱动的上层
        for (i = 0; i < vi->max_queue_pairs; i++) {
                vi->rq[i].pages = NULL;
                netif_napi_add(vi->dev, &vi->rq[i].napi, virtnet_poll,
                                  napi_weight);
                netif_tx_napi_add(vi->dev, &vi->sq[i].napi, virtnet_poll_tx,
                                  napi_tx ? napi_weight : 0);

                sg_init_table(vi->rq[i].sg, ARRAY_SIZE(vi->rq[i].sg));
                ewma_pkt_len_init(&vi->rq[i].mrg_avg_pkt_len);
                sg_init_table(vi->sq[i].sg, ARRAY_SIZE(vi->sq[i].sg));

                u64_stats_init(&vi->rq[i].stats.syncp);
                u64_stats_init(&vi->sq[i].stats.syncp);
        }
```

`virtnet_alloc_queues`在分配队列的时候，注册了一组NAPI poll回调函数，即`virtnet_poll_tx`（收包）和`virtnet_poll`（发包）。

## 3. vhost-net 收包流程分析


## 4. vhost-user-net分析

vhost-user的IO路径：
* guest 设置好tx;
* kick通知host
* guest退出到kvm；
* kvm通知vhost-backend；
* vhost-backend将tx数据直接发送到nic设备。

大小
