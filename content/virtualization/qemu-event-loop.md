Title:  qemu event handling
Date: 2019-9-3 23:00
Modified: 2019-9-3 23:00
Tags: qemu,main_loop,aio
Slug: qemu
Status: draft
Authors: Yori Fang
Summary: QEMU event handing


https://runsisi.com/2019-03-02/qemu-event-loop

其中信号处理：

如果支持SYS_signalfd SYSCALL，那么qemu利用signalfd(将信号集合转换为一个fd)，
否则使用qemu_signalfd_compat创建一个线程sigwait_compat，在线程里面sigwait接收信号，当信号接收到了就通过管道传送给主线程处理。
    qemu_set_fd_handler(sigfd, sigfd_handler, NULL, (void *)(intptr_t)sigfd)；
    sigfd要么为signalfd，要么为管道的一端，收到写事件后会调用sigfd_handler去读取信号，并调用信号的处理函数对信号进行处理。

综上：qemu异步信号处理走的是iohandler方式。

iohandler 和 aio

AioContext 支持的类型有：
* File Descriptor monitoring
* Event notifiers (inter-thread signalling)
* Timers
* Bottom Halves deferred callbacks


main_loop_wait
    notifier_list_notify(&main_loop_poll_notifiers, &mlpoll); // 设备可以注册到这个main_loop_poll_notifer上，例如slrip
    os_host_main_loop_wait()
         g_main_context_acquire
         glib_pollfds_fill
         qemu_poll_ns
         glib_pollfds_poll
