Title: A Qemu Hang Problem revelant to AIO
Date: 2020-2-3 23:00 
Modified: 2020-2-3 23:00 
Tags: aio
Slug: qemu-aio-internal
Status: published 
Authors: Yori Fang 
Summary: Qemu AIO Internal

最近openEuler在HDC 2020上宣布开源了，采用开源社区的运作模式开发和发布版本。
openEuler对Huawei鲲鹏系列CPU（基于ARM架构）提供了良好的支持，
开始陆续被国内私有云厂商开始采用，希望openEuler能够成长起来成OS业界的明星。

在前期我们的测试环境中发现在使用qemu-img做镜像格式转换的时候偶然会发现
qemu主线程会出现hung的情况。奇怪的是这个现在只在aarch64平台上出现，
在x86平台上我们没有复现出来，当时也没太在意但后来被平安科技的技术人员测出来了反馈给我们开始引起了我们的注意。
通过我们的分析，再加上和社区的讨论发现这个问题其实是
隐藏在qemu AIO机制中的一个典型smp多线程共享变量直接的同步问题。
通过对这个问题的分析和探讨，可以有助于进一步理解了smp架构上用户态编译器优化和乱序执行原理。
这里分析和记录一下这个问题。

问题复现方法很简单，采用下面的测试命令即可：

```bash
COUNT=0
while true
    do qemu-img convert -f qcow2 origin.qcow2 -O output.qcow2
    COUNT=$(expr $COUNT + 1)
    echo "do image convert times = $COUNT"
done
```

我们向qemu社区提交了bugzilla，但是好像社区的Commiter也没有就这个问题达成一个结论，
社区讨讨论连接是：

[https://lists.gnu.org/archive/html/qemu-arm/2019-10/msg00051.html](https://lists.gnu.org/archive/html/qemu-arm/2019-10/msg00051.html)


使用gdb调试出错现场发现IO请求已经完成（THREAD_DONE），
但主线程却没有感知到，从而导致主线程一直处poll循环监听pipe事件中(AIO完成事件)，
造成了主线程hang住的假象，没有办法正常退出了。

```
(gdb) p *(ThreadPoolElement*)0xaaab002707e0
$6 = { common = {aiocb_info = 0xaaaacfd6e250 <thread_pool_aiocb)info>,bs = 0x0,
    cb=0xaaaacfcd128<thread_pool_co_cb>, opaqueue = 0xffff90cef828,
    refcnt = 1, pool = 0xaaab002a4000, func = 0xaaaacfc607e4 <aio_worker>,
    state = THREAD_DONE,
    }
}
```

这里来分析一下qemu aio机制的执行逻辑：

当上一次IO处理完成之后，qemu主线程会执行aio_ctx_prepare，
在prepare阶段首先把ctx->notify_me置1（表示我下面可能要睡眠了，有IO完成了请主动通知我），
然后通过aio_compute_timeout计算下次poll的超时时间。
该函数会去检查所有的bottom half（包括定时器和监听的file descriptor）
来判断哪些IO已经下发调度（通过bh->schedule的值来确定）。

* 若有需要处理的IO直接返回0，表示下次poll的超时时间为0，即不管eventfd的pipe中是否有事件，都会直接退出，
进入aio_ctx_check和dispatch阶段去处理IO去。
* 若没有IO需要处理，则返回timeout的值为-1，这时候主线程会一直poll等待eventfd通知到来。

整个AIO的处理流程大概可以用下面的示意图表示：

![qemu aio](images/qemu_aio.svg)

进一步分析qemu_bh_schedule流程，其代码中首先通过原子操作xchq将BH_SCHEDULED标志位置为1，
若之前为0则调用aio_notify通知主线程，而aio_notify()中
会判断ctx->notify_me是否为0，只有当其不为0时候才会写pip fd。

```c
void qemu_bh_schedule(QEMUBH *bh)
{
    aio_bh_enqueue(bh, BH_SCHEDULED);
}
static void aio_bh_enqueue(QEMUBH *bh, unsigned new_flags)
{
    AioContext *ctx = bh->ctx;
    unsigned old_flags;

    /*
     * The memory barrier implicit in atomic_fetch_or makes sure that:
     * 1. idle & any writes needed by the callback are done before the
     *    locations are read in the aio_bh_poll.
     * 2. ctx is loaded before the callback has a chance to execute and bh
     *    could be freed.
     */
    old_flags = atomic_fetch_or(&bh->flags, BH_PENDING | new_flags);
    if (!(old_flags & BH_PENDING)) {
        QSLIST_INSERT_HEAD_ATOMIC(&ctx->bh_list, bh, next);
    }

    aio_notify(ctx);
}
void aio_notify(AioContext *ctx)
{
    /* Write e.g. bh->scheduled before reading ctx->notify_me.  Pairs
     * with atomic_or in aio_ctx_prepare or atomic_add in aio_poll.
     */
    smp_mb();
    if (ctx->notify_me) {
        event_notifier_set(&ctx->notifier);
        atomic_mb_set(&ctx->notified, true);
    }
}
```

后面通过aio_notify()和aio_compute_timeout()中tracelog，
我们发现io thread已经完成io请求，且调用了qemu_bh_schedule设置bh->flags BH_SCHEDULED为1，
但是主线程好像并没有看到BH_SCHEDULED被置1，或者还有一种情况是主线程在并发执行aio_ctx_prepare
的时候并没有先将notify_me置1而是直接调用了aio_ctx_compute_timeout此时却计算timeout值为-1，
导致直接即后续主线程会一直处于poll等待事件的fd从而导致主线程hang住的假象。