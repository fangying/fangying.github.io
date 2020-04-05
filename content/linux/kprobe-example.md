Title: kprobe kretprobe example
Date: 2017-9-17 23:00
Modified: 2019-9-6 23:00
Tags: linux
Slug: kprobe
Authors: Yori Fang
Summary: kprobe kretprobe example

有时候想知道下发某个操作后内核在做些什么，这个时候就要内内核进行调试， 然而KGDB这种方法操作起来相对麻烦，这个时候我们就可以使用kprobe来探测内核的行为。

介绍kprobe和kretprobe的文档为:<https://www.kernel.org/doc/Documentation/kprobes.txt>

**划重点**，这里是文档和很多博客没有解释清楚的地方：


1.  对于kprobe而言，理论上它可以probe任何一个地方（只需要指定某个代码段地址就行了，例如函数的地址）；
2.  对于kprobe而言，pre_handler回调函数执行是发生在probe断点执行之前，post_handler回调执行是发生在probe断点*单步执行*之后，而不是函数返回之前；
3.  对于kretprobe而言，一般只用来探测函数，entry_handler回调执行是在函数入口的地方（这时候我们可以探测函数的入参），handler回调函数执行是发生在函数准备返回的时候，注意这个时候参数都已经弹栈，我们只能探测函数的返回值。


下面举一个最简单的例子，介绍如何使用kprobe来查看*inet_bind*这个函数的调用情况。
*inet_bind*函数是在发生ipv4 socket bind阶段调用的一个内核函数。
```c
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/sched/clock.h>
#include <linux/kprobes.h>
#include <linux/errno.h>
#include <linux/stddef.h>
#include <linux/bug.h>
#include <linux/ptrace.h>

#include <linux/socket.h>
#include <linux/kmod.h>
#include <linux/sched.h>
#include <linux/string.h>
#include <linux/sockios.h>
#include <linux/net.h>

#include <linux/inet.h>
#include <net/ip.h>
#include <net/tcp.h>
#include <linux/skbuff.h>
#include <net/sock.h>
#include <net/inet_common.h>


/* For each probe you need to allocate a kprobe structure */
static struct kprobe kp = {
    .symbol_name    = "inet_bind",
};

/* kprobe pre_handler: called just before the probed instruction is executed */
static int handler_pre(struct kprobe *p, struct pt_regs *regs)
{

#ifdef CONFIG_ARM64
    struct socket *sock = regs->regs[0];
    struct sockaddr *uaddr = regs->regs[1];
#endif

#ifdef CONFIG_X86
    struct socket *sock = regs->di;
    struct sockaddr *uaddr = regs->si;
#endif

    struct sockaddr_in *addr =  (struct sockaddr_in *)uaddr;
    unsigned short snum = ntohs(addr->sin_port);

    pr_info("%s name:%s pid:%d socket bind port=%d\n",
            p->symbol_name, current->comm, task_pid_nr(current), snum);

    return 0;
}
/* kprobe post_handler: called after the probed instruction is executed */
static void handler_post(struct kprobe *p, struct pt_regs *regs,
        unsigned long flags)
{
    pr_info("%s called\n", __func__);
}

/*
 * fault_handler: this is called if an exception is generated for any
 * instruction within the pre- or post-handler, or when Kprobes
 * single-steps the probed instruction.
 */
static int handler_fault(struct kprobe *p, struct pt_regs *regs, int trapnr)
{
    printk(KERN_INFO "fault_handler: p->addr = 0x%p, trap #%dn",
            p->addr, trapnr);
    /* Return 0 because we don't handle the fault. */
    return 0;
}

static int __init kprobe_init(void)
{
    int ret;
    kp.pre_handler = handler_pre;
    kp.post_handler = handler_post;
    kp.fault_handler = handler_fault;

    ret = register_kprobe(&kp);
    if (ret < 0) {
        printk(KERN_INFO "register_kprobe failed, returned %d\n", ret);
        return ret;
    }
    printk(KERN_INFO "Planted kprobe at %p\n", kp.addr);
    return 0;
}

static void __exit kprobe_exit(void)
{
    unregister_kprobe(&kp);
    printk(KERN_INFO "kprobe at %p unregistered\n", kp.addr);
}

module_init(kprobe_init)
module_exit(kprobe_exit)
MODULE_LICENSE("GPL");
```
值得一提的是，kprobe里面我们在probe某个函数的时候，获取函数参数的时候是和体系结构相关的。

例如：在x86平台上，根据C ABI [ptrace](https://elixir.bootlin.com/linux/latest/source/arch/x86/include/asm/ptrace.h)接口规范，函数的参数和pt_regs的对应关系是：
```c
struct pt_regs {
/*
 * C ABI says these regs are callee-preserved. They aren't saved on kernel entry
 * unless syscall needs a complete, fully filled "struct pt_regs".
 */
        unsigned long r15;
        unsigned long r14;
        unsigned long r13;
        unsigned long r12;
        unsigned long bp;
        unsigned long bx;
/* These regs are callee-clobbered. Always saved on kernel entry. */
        unsigned long r11;
        unsigned long r10;
        unsigned long r9;
        unsigned long r8;
        unsigned long ax;
        unsigned long cx;   // mapped to arg[3]
        unsigned long dx;   // mapped to arg[2]
        unsigned long si;   // mapped to arg[1]
        unsigned long di;   // mapped to arg[0]
/*
 * On syscall entry, this is syscall#. On CPU exception, this is error code.
 * On hw interrupt, it's IRQ number:
 */
        unsigned long orig_ax;
/* Return frame for iretq */
        unsigned long ip;
        unsigned long cs;
        unsigned long flags;
        unsigned long sp;
        unsigned long ss;
/* top of stack page */
};
```
在ARM64平台上，根据C ABI [ptrace](https://elixir.bootlin.com/linux/v4.19.69/source/arch/arm64/include/asm/ptrace.h)规范，
函数的参数和pt_regs的对应关系是：入参args[0]对应了regs[0]，入参args[1]对应regs[1]依此类推。

```c
/*
 * This struct defines the way the registers are stored on the stack during an
 * exception. Note that sizeof(struct pt_regs) has to be a multiple of 16 (for
 * stack alignment). struct user_pt_regs must form a prefix of struct pt_regs.
 */
struct pt_regs {
        union {
                struct user_pt_regs user_regs;
                struct {
                        u64 regs[31];
                        u64 sp;
                        u64 pc;
                        u64 pstate;
                };
        };
        u64 orig_x0;
#ifdef __AARCH64EB__
        u32 unused2;
        s32 syscallno;
#else
        s32 syscallno;
        u32 unused2;
#endif

        u64 orig_addr_limit;
        /* Only valid when ARM64_HAS_IRQ_PRIO_MASKING is enabled. */
        u64 pmr_save;
        u64 stackframe[2];
};
```

使用下面的Makefile文件，对其进行编译。
```shell
obj-m := kprobe_example.o
CROSS_COMPILE=''
KDIR := /lib/modules/$(shell uname -r)/build
all:  
    make -C $(KDIR) M=$(PWD) modules   
clean:  
    rm -f *.ko *.o *.mod.o *.mod.c .*.cmd *.symvers  modul*  
```
编译完成后会生产一个名为*kprobe_example.ko*的内核模块文件，执行`insmod kprobe_example.ko`后内核模块立即生效，通过`dmesg`命令可以查看到*inet_bind*这个函数的调用情况。从dmesg日志可以看到：

```
[46071.632951] inet_bind name:test pid:68248 socdmket bind port=49152
[46071.632984] inet_bind name:test pid:68248 socket bind port=49152
[46071.632995] inet_bind name:test pid:68248 socket bind port=49152
```

kretprobe可以用来探测函数的返回值，示例中我们用它来探测*inet_release*函数的返回值和执行时间：
```c
/*
 * kretprobe_example.c
 *
 * Here's a sample kernel module showing the use of return probes to
 * report the return value and total time taken for probed function
 * to run.
 *
 * usage: insmod kretprobe_example.ko func=<func_name>
 *
 * If no func_name is specified, inet_release is instrumented
 *
 * For more information on theory of operation of kretprobes, see
 * Documentation/kprobes.txt
 *
 * Build and insert the kernel module as done in the kprobe example.
 * You will see the trace data in /var/log/messages and on the console
 * whenever the probed function returns. (Some messages may be suppressed
 * if syslogd is configured to eliminate duplicate messages.)
 */

#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/kprobes.h>
#include <linux/ktime.h>
#include <linux/limits.h>
#include <linux/sched.h>

static char func_name[NAME_MAX] = "inet_release";
module_param_string(func, func_name, NAME_MAX, S_IRUGO);
MODULE_PARM_DESC(func, "Function to kretprobe; this module will report the"
                        " function's execution time");

/* per-instance private data */
struct my_data {
        ktime_t entry_stamp;
};

/* Here we use the entry_hanlder to timestamp function entry */
static int entry_handler(struct kretprobe_instance *ri, struct pt_regs *regs)
{
        struct my_data *data;

        if (!current->mm)
                return 1;       /* Skip kernel threads */

        data = (struct my_data *)ri->data;
        data->entry_stamp = ktime_get();
        return 0;
}

/*
 * Return-probe handler: Log the return value and duration. Duration may turn
 * out to be zero consistently, depending upon the granularity of time
 * accounting on the platform.
 */
static int ret_handler(struct kretprobe_instance *ri, struct pt_regs *regs)
{
        int retval = regs_return_value(regs);
        struct my_data *data = (struct my_data *)ri->data;
        s64 delta;
        ktime_t now;

        now = ktime_get();
        delta = ktime_to_ns(ktime_sub(now, data->entry_stamp));

        printk(KERN_INFO "%s returned %d and took %lld ns to execute\n",
                        func_name, retval, (long long)delta);
        return 0;
}

static struct kretprobe my_kretprobe = {
        .handler                = ret_handler,
        .entry_handler          = entry_handler,
        .data_size              = sizeof(struct my_data),
        /* Probe up to 20 instances concurrently. */
        .maxactive              = 20,
};

static int __init kretprobe_init(void)
{
        int ret;

        my_kretprobe.kp.symbol_name = func_name;
        ret = register_kretprobe(&my_kretprobe);
        if (ret < 0) {
                printk(KERN_INFO "register_kretprobe failed, returned %d\n",
                                ret);
                return -1;
        }
        printk(KERN_INFO "Planted return probe at %s: %p\n",
                        my_kretprobe.kp.symbol_name, my_kretprobe.kp.addr);
        return 0;
}

static void __exit kretprobe_exit(void)
{
        unregister_kretprobe(&my_kretprobe);
        printk(KERN_INFO "kretprobe at %p unregistered\n",
                        my_kretprobe.kp.addr);

        /* nmissed > 0 suggests that maxactive was set too low. */
        printk(KERN_INFO "Missed probing %d instances of %s\n",
                my_kretprobe.nmissed, my_kretprobe.kp.symbol_name);
}

module_init(kretprobe_init)
module_exit(kretprobe_exit)
MODULE_LICENSE("GPL");
```
探测的结果输出如下：
```shell
[60362.085372] inet_release returned 0 and took 16360 ns to execute
[60362.091124] inet_release returned 0 and took 8880 ns to execute
[60362.091147] inet_release returned 0 and took 7640 ns to execute
[60362.091173] inet_release returned 0 and took 7900 ns to execute
[60362.941665] inet_release returned 0 and took 9100 ns to execute
[60363.099577] inet_release returned 0 and took 9240 ns to execute
[60363.126682] inet_release returned 0 and took 6000 ns to execute
[60363.153610] inet_release returned 0 and took 9060 ns to execute
[60363.153820] inet_release returned 0 and took 3220 ns to execute
[60363.154699] inet_release returned 0 and took 3260 ns to execute
[60363.159178] inet_release returned 0 and took 3200 ns to execute
[60363.180098] inet_release returned 0 and took 3080 ns to execute

```
