Title:  Userfaultfd机制
Date: 2020-10-16 23:00
Modified: 2020-10-16 23:00
Tags: userfaultfd
Slug: userfaultfd
Status: draft
Authors: Yori Fang
Summary: Userfaultfd


## 1. Userfaultfd简介

我们熟知的`page fault`是内核用来处理缺页的基本机制，
而`userfaultfd`引入的目的是为了允许应用程序从用户态按需获取各种内存缺页的控制权的一种方案。

## 2. 设计方案
`userfaultfd`除了可以注册和取消注册虚拟地址以外，还提供两个主要功能：

*   read/ POLLIN协议，用于通知用户空间线程故障发生；
*   通过各种UFFDIO_* ioctls可以管理注册的虚拟地址，允许用户解决通过后台接收到的缺页错误或者在后台管理虚拟内存。

userfaultfd相对于常规的虚拟内存管理方法mremap/mprotect的优点是，
在userfaultfd的所有操作场景下都不涉及引用重量级的数据结构例例如vma，
实际上userfaultfd在工作的时候是不持mmap_lock的写锁的。
而且vma也不适用页（大页）内存的跟踪尤其是那些虚拟地址空间有可能扩展到TB级别的场景，
因为需要太多的vma了。

userfaultfd厉害的地方在于：

一旦使用系统调用打开userfaultfd后，我们可以将fd通过unix socket传送给管理进程。
这样管理进程可以通过监听fd来处理多个不同被监听进程的缺页异常（当然除非进程自己使用userfautfd注册了相同内存区域，这样会导致EBUSY错误）。

目前QEMU会使用`userfaultfd`技术来优化post-copy热迁移，高效内存快照等常见。

## 3. userfaultfd API

userfaultfd的基本工作流程： 

* 应用程序调用userfaultfd会系统会返回一个用于控制用户态进程内存区域的fd；
* 通过进行一组ioctl()调用，用户空间进程可以接管那些发生在它指定地址区间的page fault处理；
* 该范围内的page fault将产生一个可以从fd中读取的event事件，进程读取该event并采取必要的行动来处理page fault；
* 进程将一个描述此page fault解决方法的response写到同一个fd中，之后导致fault的代码将恢复执行。

userfaultfd通常被应用在多线程常见中，由一个线程来处理事件消息。

## 6. References

1. https://www.kernel.org/doc/html/latest/admin-guide/mm/userfaultfd.html
2. https://www.mdeditor.tw/pl/pE31/zh-hk