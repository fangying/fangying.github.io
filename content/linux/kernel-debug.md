Title: Debug Linux Kernel Using QEMU and GDB
Date: 2018-12-23 23:00
Modified: 2018-12-23 23:00
Tags: linux
Slug: kernel-debug-using-qemu
Status: published
Authors: Yori Fang
Summary: Debug Linux Kernel 


有的时候为了研究内核原理或者调试bios的时候，可以利用QEMU和gdb的方式来帮助我们调试问题．
这种操作利用了QEMU内建的gdb-stub能力．

## 重新编译内核

编译的时候开启内核参数CONFIG_DEBUG_INFO和CONFIG_GDB_SCRIPTS再进行编译，
如果硬件支持CONFIG_FRAME_POINTER也一并开启．

```bash
make modules -j`nproc`
make -j`nproc` 
```

## 调试内核

用下的命令行拉起QEMU，这里可以从自己的OS上选取一个initramfs传给QEMU，
记得配上`nokaslr`以免内核段基地址被随机映射．
这里`-S`参数可以让QEMU启动后CPU先Pause住不运行，
`-s`参数是`-gdb tcp::1234`的简写，意思是让QEMU侧的gdb server侦听在1234端口等待调试．

```bash
/mnt/code/qemu/x86_64-softmmu/qemu-system-x86_64 \
    -machine pc-i440fx-2.8,accel=kvm,kernel_irqchip \
    -cpu host \
    -m 4096,slots=4,maxmem=16950M \
    -smp 4 \
    -chardev pty,id=charserial0 \
    -device isa-serial,chardev=charserial0,id=serial0 \
    -netdev tap,id=tap0,ifname=virbr0-nic,vhost=on,script=no \
    -device virtio-net-pci,netdev=tap0 \
    -kernel $KERNEL_SRC/arch/x86/boot/bzImage \
    -initrd /boot/vmlinuz-4.14.0-rc2-fangying \
    -append 'console=ttyS0 nokaslr' \
    -vnc :9 \
    -S -s
```
gdb可能会报错`Remote 'g' packet reply is too long:`，这个时候的解决办法是打上一个补丁然后重新编译gdb.

问题处在static void process_g_packet (struct regcache *regcache)函数，6113行，屏蔽对buf_len的判断．

如果gdb版本低(7.x)打这个补丁:
```bash
    if (buf_len > 2 * rsa->sizeof_g_packet)
    error (_("Remote 'g' packet reply is too long: %s"), rs->buf);
改为:
    if (buf_len > 2 * rsa->sizeof_g_packet) {
        rsa->sizeof_g_packet = buf_len;
        for (i = 0; i < gdbarch_num_regs (gdbarch); i++)
        {
            if (rsa->regs[i].pnum == -1)
                continue;
            if (rsa->regs[i].offset >= rsa->sizeof_g_packet)
                rsa->regs[i].in_g_packet = 0;
            else
                rsa->regs[i].in_g_packet = 1;
        }
    }
```
如果gdb版本高(8.x)打这个补丁:

```bash
    if (buf_len > 2 * rsa->sizeof_g_packet)
    error (_("Remote 'g' packet reply is too long: %s"), rs->buf);
改为:
    /* Further sanity checks, with knowledge of the architecture.  */
    if (buf_len > 2 * rsa->sizeof_g_packet) {
        rsa->sizeof_g_packet = buf_len ;
        for (i = 0; i < gdbarch_num_regs (gdbarch); i++) {
            if (rsa->regs[i].pnum == -1)
                continue;
            if (rsa->regs[i].offset >= rsa->sizeof_g_packet)
                rsa->regs[i].in_g_packet = 0;
            else
                rsa->regs[i].in_g_packet = 1;
        }
    }
```

开始愉快地调试内核了:
```bash
$ gdb vmlinux 
(gdb) target remote :1234
Remote debugging using :1234
0x000000000000fff0 in cpu_hw_events ()
(gdb) hb start_kernel
Hardware assisted breakpoint 1 at 0xffffffff827dabb2: file init/main.c, line 538.
(gdb) c
Continuing.

Thread 1 hit Breakpoint 1, start_kernel () at init/main.c:538
538	{
(gdb) l
533	{
534		rest_init();
535	}
536	
537	asmlinkage __visible void __init start_kernel(void)
538	{
539		char *command_line;
540		char *after_dashes;
541	
542		set_task_stack_end_magic(&init_task);
(gdb) 

```

另外可以使用mkinitrd（mkinitramfs）命令来生成initramfs.img文件，例如：
```
sudo mkinitrd -v initramfs.img 5.0.0-rc4+
```
第一个参数是initramfs的输出文件名，第二个参数是内核版本号。
然后我们可以直接boot这个内核：

```
x86_64-softmmu/qemu-system-x86_64 \
    -kernel /mnt/code/linux/arch/x86/boot/bzImage \
    -nographic \
    -append "console=ttyS0 nokalsr" \
    -enable-kvm \
    -cpu host \
    -initrd initramfs.img \
    -m 1024
```

## 参考文献

1.[linux kernel debug with qemu](http://nickdesaulniers.github.io/blog/2018/10/24/booting-a-custom-linux-kernel-in-qemu-and-debugging-it-with-gdb/)
