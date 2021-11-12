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
如果硬件支持CONFIG_FRAME_POINTER也一并开启，但要关闭CONFIG_DEBUG_INFO_REDUCED。

```bash
cd /home/fang/Code/opensrc/linux
make modules -j`nproc`
make -j`nproc` 
```

## 调试内核

用下的命令行拉起QEMU，这里可以从自己的OS上选取一个initramfs传给QEMU或者直接挂载一个rootfs镜像，
记得配上`nokaslr`以免内核段基地址被随机映射．
这里`-S`参数可以让QEMU启动后CPU先Pause住不运行，
`-s`参数是`-gdb tcp::1234`的简写，意思是让QEMU侧的gdb server侦听在1234端口等待调试．

```bash
/data/vm/qemu/x86_64-softmmu/qemu-system-x86_64 \
	-machine pc,accel=kvm \
	-cpu host \
    -smp 4 \
	-m 4096M \
	-nodefaults \
	-nographic \
	-drive id=test,file=$(pwd)/fedora33.raw,format=raw,if=none \
	-device virtio-blk-pci,drive=test \
	-netdev tap,id=tap,ifname=virbr0-tap,script=no,downscript=no \
	-device virtio-net-pci,netdev=tap \
	-kernel /home/fang/Code/opensrc/linux/vmlinux \
	-append "nokaslr earlyprintk=ttyS0 console=ttyS0 tsc=realiable root=/dev/vda rw" \
	-serial stdio -S -s
```
用上面的qemu脚本拉起虚拟机，关键是最后的`-S -s`参数的含义是让qemu运行内建的gdbserver并监听在本地的1234
端口。**注意**：测试发现高版本的qemu内建的gdbserver好像有兼容性问题，我用qemu-6.0发现无法调试内核，
但是回退到qemu-4.0可以调试内核。下载qemu自己编译一个合适的版本：
```
git clone https://github.com/qemu/qemu.git
cd qemu
git checkout v4.0.0
./configure --enable-kvm --target-list=x86_64-softmmu --disable-werror
make -j
# 目标文件是：
x86_64-softmmu/qemu-system-x86_64
```

如果运行后，gdb可能会报错`Remote 'g' packet reply is too long:`，
这个时候的解决办法是打上一个补丁然后重新编译gdb.

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

编辑~/.gdbinit文件，让gdb自动加载vmlinux-gdb.py文件，
```
add-auto-load-safe-path /path/to/linux-build
```
开始愉快地调试内核了:
```bash
$ cd linux
$ gdb vmlinux
$ lx-symbols
$ 
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

2.[Debugging kernel and modules via gdb](https://01.org/linuxgraphics/gfx-docs/drm/dev-tools/gdb-kernel-debugging.html)
