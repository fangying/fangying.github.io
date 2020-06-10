Title:  Multifd Live Migration
Date: 2020-2-23 23:00
Modified: 2020-2-23 23:00
Tags: multifd-migration
Slug: multifd-migration
Status: draft
Authors: Yori Fang
Summary: QEMU live migration

之前的qemu默认使用单线程`migration_thread`来做热迁移，这样会导致一个问题：
主机热迁移带宽无法得到充分利用。为了提升热迁移速度，Juan Quintela提出了multifd热迁移方案，
该方案可以利用多个线程来进行热迁移，提升带宽利用率和缩短热迁移时长。
本文记录一下multifd的实现细节。


## 1. Multifd源端

源端下发热迁移，传入热迁移参数，例如使用4个线程来做热迁移：
```
# virsh migrate testvm --live --unsafe --parallel --parallel-connections 4 \
        --migrateuri tcp://192.168.3.33  qemu+tcp://192.168.3.33/system --verbose
```

接着看下Multifd的下发流程，于是加点日志，看下qmp的交互大概如下：
```
qmp_cmd_name: query-migrate-parameters, arguments: {}                           
qmp_cmd_name: migrate-set-capabilities, arguments: {"capabilities": [{"state": false, "capability": "xbzrle"}, {"state": false, "capability": "auto-converge"}, {"state": false, "capability": "rdma-pin-all"}, {"state": false, "capability": "postcopy-ram"}, {"state": false, "capability": "compress"}, {"state": true, "capability": "pause-before-switchover"}, {"state": false, "capability": "late-block-activate"}, {"state": true, "capability": "multifd"}]}
qmp_cmd_name: migrate-set-parameters, arguments: {"multifd-channels": 4, "tls-creds": "", "tls-hostname": ""}                                                                                                   
qmp_cmd_name: migrate_set_speed, arguments: {"value": 9223372036853727232}      
2020-06-05 03:57:39.843+0000: initiating migration
qmp_cmd_name: migrate, arguments: {"blk": false, "uri": "tcp://192.168.3.33", "detach": true, "inc": false}
```
从日志中可以看到下的multifd-channels数目是4个，下发的热迁移uri是: tcp://192.168.3.33。

```c
qmp_migrate
    -> tcp_start_outgoing_migration
        -> socket_start_outgoing_migration
            -> socket_outgoing_migration
                -> migration_channel_connect
                    -> migrate_fd_connect
migrate_fd_connect
    -> multifd_save_setup   // 创建multifd子线程
    -> migration_thread     // 热迁移线程
```

从Multifd的源端流程准备工作主要在`multifd_save_setup`实现，大概做了3件事情：

*  multifd_send_state全局变量初始化
*  channel的参数MultiFDSendParams *p
*  multifd通道线程创建

```c
int multifd_save_setup(Error **errp)
{
    int thread_count;
    uint32_t page_count = MULTIFD_PACKET_SIZE / qemu_target_page_size(); //每次发送page_count个页
    uint8_t i;

    if (!migrate_use_multifd()) {
        return 0;
    }
    thread_count = migrate_multifd_channels();  // multifd线程数
    multifd_send_state = g_malloc0(sizeof(*multifd_send_state));    //初始化multifd_send_state全局变量
    multifd_send_state->params = g_new0(MultiFDSendParams, thread_count);
    multifd_send_state->pages = multifd_pages_init(page_count);
    qemu_sem_init(&multifd_send_state->channels_ready, 0);
    atomic_set(&multifd_send_state->exiting, 0);
    multifd_send_state->ops = multifd_ops[migrate_multifd_compression()];

    for (i = 0; i < thread_count; i++) {
        MultiFDSendParams *p = &multifd_send_state->params[i];

        qemu_mutex_init(&p->mutex);
        qemu_sem_init(&p->sem, 0);          // 发送信号量初始化
        qemu_sem_init(&p->sem_sync, 0);     // 同步信号量初始化
        p->quit = false;
        p->pending_job = 0;
        p->id = i;      // channel id
        p->pages = multifd_pages_init(page_count);
        p->packet_len = sizeof(MultiFDPacket_t)
                      + sizeof(uint64_t) * page_count;
        p->packet = g_malloc0(p->packet_len);
        p->packet->magic = cpu_to_be32(MULTIFD_MAGIC);
        p->packet->version = cpu_to_be32(MULTIFD_VERSION);
        p->name = g_strdup_printf("multifdsend_%d", i);
        socket_send_channel_create(multifd_new_send_channel_async, p);  //创建multifd子线程
    }

    for (i = 0; i < thread_count; i++) {
        MultiFDSendParams *p = &multifd_send_state->params[i];
        Error *local_err = NULL;
        int ret;

        // 调用send_setup钩子函数，热迁移压缩会走这个
        ret = multifd_send_state->ops->send_setup(p, &local_err);   
        if (ret) {
            error_propagate(errp, local_err);
            return ret;
        }
    }
    return 0;
}
```

创建了multifd后，源端需要和目的端要做个握手动作以建立连接通道准备开始传输内存数据。
在握手的过程中，源端要给目的端发送一个inital packet，然后进入一个while循环开始
发送数据报文。
```
socket_send_channel_create
    -> multifd_new_send_channel_async
        -> multifd_send_thread
            -> multifd_send_initial_packet // 发送initial packet握手数据包
            while true {
                qemu_sem_wait(&p->sem)  // 等待信号量
                // 发送内存page
            }
```


ram_save_target_page

每次发送完成之后


发送一个page
```c
static int multifd_send_pages(QEMUFile *f)
{
    int i;
    static int next_channel;
    MultiFDSendParams *p = NULL; /* make happy gcc */
    MultiFDPages_t *pages = multifd_send_state->pages;
    uint64_t transferred;

    if (atomic_read(&multifd_send_state->exiting)) {
        return -1;
    }

    qemu_sem_wait(&multifd_send_state->channels_ready);
    for (i = next_channel;; i = (i + 1) % migrate_multifd_channels()) {
        p = &multifd_send_state->params[i];

        qemu_mutex_lock(&p->mutex);
        if (p->quit) {
            error_report("%s: channel %d has already quit!", __func__, i);
            qemu_mutex_unlock(&p->mutex);
            return -1;
        }
        if (!p->pending_job) {
            p->pending_job++;
            next_channel = (i + 1) % migrate_multifd_channels();
            break;
        }
        qemu_mutex_unlock(&p->mutex);
    }
    assert(!p->pages->used);
    assert(!p->pages->block);

    p->packet_num = multifd_send_state->packet_num++;
    multifd_send_state->pages = p->pages;
    p->pages = pages;
    transferred = ((uint64_t) pages->used) * qemu_target_page_size()
                + p->packet_len;
    qemu_file_update_transfer(f, transferred);
    ram_counters.multifd_bytes += transferred;
    ram_counters.transferred += transferred;;
    qemu_mutex_unlock(&p->mutex);
    qemu_sem_post(&p->sem);    // 同时multifd线程发送page

    return 1;
}
```

## 2. Multifd目的端


## 3. References

1. http://patchwork.ozlabs.org/project/qemu-devel/cover/20170913105953.13760-1-quintela@redhat.com/