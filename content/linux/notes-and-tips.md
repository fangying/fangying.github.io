Title: Tips on Linux
Date: 2018-6-12 23:00
Modified: 2018-6-12 23:00
Tags: x86
Slug: linux-tips
Authors: Yori Fang
Summary: linux-tips
Status: published 

### QEMU gdb调试屏蔽若干信号

```
echo 'handle SIGUSR1 SIGUSR2 noprint nostop' >> ~/.gdbinit
```

#### 生成内核符号表
```bash
make tags ARCH=x86
make cscope ARCH=x86
```

#### GDB设置条件断点

设置条件断点除了使用break if语句之外还有一种便捷的方法。
例如，我们在qemu的函数vmstate_save_sate_v上设置断点，抓取virtio-blk设备的状态保存。
可以这么做：
```
b vmstate_save_sate_v
continue  
# 等到获取断点后使用
condition 1 strcmp(vmsd->name, "virtio-blk") == 0
# i b
可以看到多了一个条件，表示额外需要满足这个条件在hit这个断点
```
参考: https://www.fayewilliams.com/2011/07/13/gdb-conditional-breakpoints/

#### 密码输错超过最大次数，解锁骚操作

```bash
pam_tally2 --user root
pam_tally2 -r -u root
```

#### 更新let's encrypt证书

```bash
yum -y install yum-utils
yum-config-manager --enable rhui-REGION-rhel-server-extras rhui-REGION-rhel-server-optional
yum install python2-certbot-nginx
certbot --nginx
certbot renew --dry-run
```
### ftrace查看pCPU上的调度情况
这里以查看pCPU2的调度状况为例
```bash
mount -t debugfs none /sys/kernel/debug/
cd /sys/kernel/debug/tracing
echo 1 > events/sched/enable ; sleep 2 ; echo 0 > events/sched/enable
cat per_cpu/cpu2/trace > /home/trace.txt
```
可以看到PCPU上的调度情况
```
# tracer: nop
#
# entries-in-buffer/entries-written: 381200/1199928   #P:24
#
#                              _-----=> irqs-off
#                             / _----=> need-resched
#                            | / _---=> hardirq/softirq
#                            || / _--=> preempt-depth
#                            ||| /     delay
#           TASK-PID   CPU#  ||||    TIMESTAMP  FUNCTION
#              | |       |   ||||       |         |
          <idle>-0     [002] d... 158158.084267: sched_switch: prev_comm=swapper/2 prev_pid=0 prev_prio=120 prev_state=R ==> next_comm=CPU 0/KVM next_pid=2046 next_prio=120
       CPU 0/KVM-2046  [002] d... 158158.084280: sched_stat_runtime: comm=CPU 0/KVM pid=2046 runtime=16239 [ns] vruntime=105862773195 [ns]
       CPU 0/KVM-2046  [002] d... 158158.084281: sched_switch: prev_comm=CPU 0/KVM prev_pid=2046 prev_prio=120 prev_state=S ==> next_comm=swapper/2 next_pid=0 next_prio=120
          <idle>-0     [002] dNh. 158158.085265: sched_wakeup: comm=CPU 0/KVM pid=2046 prio=120 success=1 target_cpu=002
          <idle>-0     [002] d... 158158.085266: sched_switch: prev_comm=swapper/2 prev_pid=0 prev_prio=120 prev_state=R ==> next_comm=CPU 0/KVM next_pid=2046 next_prio=120
       CPU 0/KVM-2046  [002] d... 158158.085280: sched_stat_runtime: comm=CPU 0/KVM pid=2046 runtime=16148 [ns] vruntime=105862789343 [ns]
       CPU 0/KVM-2046  [002] d... 158158.085281: sched_switch: prev_comm=CPU 0/KVM prev_pid=2046 prev_prio=120 prev_state=S ==> next_comm=swapper/2 next_pid=0 next_prio=120
          <idle>-0     [002] dNh. 158158.086265: sched_wakeup: comm=CPU 0/KVM pid=2046 prio=120 success=1 target_cpu=002
```

#### 测试NUMA NODE内存性能
这里以加压100M为例

```
#关闭NMI watchdog，防止压力过大把系统搞死
echo 0 > /proc/sys/kernel/nmi_watchdog

#打开shell的cgroup隔离
echo $$ > /sys/fs/cgroup/cpuset/tasks

获取Stream加压工具
git clone https://github.com/jeffhammond/STREAM
cd STREAM-master
gcc -O -DSTREAM_ARRAY_SIZE=100000000 stream.c -o stream.100M

#获取pcm带宽测试工具
git clone https://github.com/opcm/pcm
chmod +x ./pcm-memory.x
./pcm-memory.x 查看带宽
```

#### 如何查看任务的调度延时
通过perf sched 查看某段时间内进程的调度延时
```c
perf sched record -- sleep 1
#观察调度延迟
perf sched latency --sort=max
```
### No newline at end of file
```
:set binary noeol
```

#### 如何查找一个系统调用的定义在哪个文件中

```
grep -E "SYSCALL_DEFINE[0-6]\(listen" -nr
```

#### perf查看虚拟机性能数据
```
pid=$(pgrep qemu-kvm)
perf kvm stat record -p $pid
perf kvm stat report
```

#### wget下载指定目录的指定文件到
```
 wget -c -r -nd -np -k -L -p -A "qemu*.rpm" \
  http://mirrors.aliyun.com/centos/7.6.1810/updates/x86_64/Packages/
 
 -c 断点续传， -r 递归， -nd不在本地创建对应文件夹， -np不下载父目录， -A 接受哪些类型的文件（这里可以试一个glob表达式）
```
 
#### 查询设备/设备类属性

```
 设备属性
 virsh qemu-monitor-command vmname '{"arguments": {"typename": "virtio-net-pci"}, "execute":"device-list-properties"}'
 设备类属性
 virsh qemu-monitor-command vmname '{"arguments": {"typename": "virtio-net-pci"}, "execute":"qom-list-properties"}'
 设备实例的属性
 virsh qemu-monitor-command fangying --hmp "info qtree" | less
```

#### 配置yum proxy
```
# append to /etc/yum.conf
proxy=http://xxxx
proxy_username=xxxx
proxy_password=xxxx
```

#### 配置docker hub

众所周知,docker hub默认国外镜像在国内几乎无法访问,需要配置国内支持匿名pull的docker hub.
edit `/etc/docker/daemon.json`
```
{
  "registry-mirrors": [
    "https://dockerhub.azk8s.cn",
    "https://docker.mirrors.ustc.edu.cn",
    "https://registry.docker-cn.com"
  ]
}
```
然后重新启动Docker服务
```bash
sudo systemctl daemon-reload
sudo systemctl restart docker
```

#### 编译firecracker

```
docker run --user 0:0 --workdir /firecracker -it \
--name firecracker --net host --volume $(pwd):/firecracker:z \
--env OPT_LOCAL_IMAGES_PATH=/firecracker/build \
--env PYTHONDONTWRITEBYTECODE=1 fcuvm/dev:v12
```

#### 虚拟机文件系统扩容

情况1： 非lvm卷，rootfs是ext4文件系统

安装的虚拟机根分区太小，磁盘格式是qcow2的，可以直接扩容，先qemu-img扩展镜像大小，再到虚拟机里面扩展文件系统。
```
# root@ubuntu:~# lsblk
NAME   MAJ:MIN RM  SIZE RO TYPE MOUNTPOINT
sda      8:0    0   10G  0 disk
├─sda1   8:1    0  512M  0 part /boot/efi
└─sda2   8:2    0  9.5G  0 part /
sr0     11:0    1  7.6G  0 rom

# qemu-img resize vm-imgage.qcow2 +100G

# root@ubuntu:~# lsblk
NAME   MAJ:MIN RM  SIZE RO TYPE MOUNTPOINT
sda      8:0    0  110G  0 disk
├─sda1   8:1    0  512M  0 part /boot/efi
└─sda2   8:2    0  9.5G  0 part /
sr0     11:0    1  7.6G  0 rom

先删除原来的分区，然后重新创建分区，前提是这个分区是磁盘的最后一个分区
# gparted /dev/sda
(parted) rm 2
Warning: Partition /dev/sda2 is being used. Are you sure you want to continue?
Yes/No? Yes
Error: Partition(s) 2 on /dev/sda have been written, but we have been unable to inform the kernel of the change, probably because it/they are in use.  As a result, the old partition(s) will
remain in use.  You should reboot now before making further changes.
Ignore/Cancel? Ignore

# gparted /dev/sda
(parted) mkpart
Start? 538MB
End? 100G
(parted) quit

文件系统扩容
# resize2fs /
```
重启虚拟机就OK了

情况2：lvm卷，rootfs是 xfs的

策略还是先调整qcow2磁盘大小，然后进入系统调整pv的大小，然后对lv进行扩容，最后再把xfs系统扩大。

```
# lsblk
vda                 252:0     0    10G  0 part
|__vda1             252:1     0    1G   0 part /boot
|__vda2             252:2     0    9G   0 part
   |__fedora-root   253:0     0    8G   0 lvm  /
   |__fedora-swap   253:1     0    1G   0 lvm  [SWAP]

将磁盘扩大，扩大个100G
# qemu-img resize fedora_31_64_server.qcow2 +100G

# cfdisk /dev/vda2 
删除原来/dev/vda2分期，重建分区把后面扇区都扩进来


# lsblk
vda                 252:0     0    110G  0 part
|__vda1             252:1     0    1G    0 part /boot
|__vda2             252:2     0    9G    0 part
   |__fedora-root   253:0     0    8G    0 lvm  /
   |__fedora-swap   253:1     0    1G    0 lvm  [SWAP]

接着对/dev/vda2进行pv扩容，将剩余的空间都划成PE
# pvresize /dev/vda2
# pvdisplay 确认PE扩展成功

对LV进行扩容
# lvextend -L +100G /dev/mapper/fedora-root

对文件系统进行扩容
# xfs_growfs /

搞定了
```

#### Debug Qemu代码

```
QEMU_BINARY=/mnt/sdc/fangying/x86/qemu/x86_64-softmmu/qemu-system-x86_64
IMAGE=$(pwd)/plc_centos_7.4_64.qcow2
gdb --args $QEMU_BINARY \
    -machine pc-i440fx-2.8,accel=kvm,kernel_irqchip \
    -cpu host \
    -m 8192,slots=4,maxmem=16950M \
    -smp 4 \
    -chardev pty,id=charserial0 \
    -device isa-serial,chardev=charserial0,id=serial0 \
    -netdev tap,id=tap0,ifname=tap0,vhost=off,script=no \
    -device virtio-net-pci,netdev=tap0 \
    -drive file=$IMAGE \
    -vnc :9
```

#### 将进程proc cmdline格式化一下
```
sed -i "s/ -/ \\\ \n-/g" cmd.txt && sed -i 's/ *$//' cmd.txt
```

#### 使用quilt补丁管理工具来管理补丁

```
quilt add filename
quilt diff
quilt top
quilt push
quilt pop
quilt refresh
quilt edit
quilt files
quilt fork
quilt graph
quilt import
quilt ...
```
请参看教程：
[https://www.cnblogs.com/openix/p/3984538.html](https://www.cnblogs.com/openix/p/3984538.html)

### macOS catalina 配置git 自动补全

https://dev.to/saltyshiomix/a-guide-for-upgrading-macos-to-catalina-and-migrating-the-default-shell-from-bash-to-zsh-4ep3

#### git 将本地自己拉出来的分支push到远程

```
git checkout -b test
// do some commit
git push --set-upstream origin test
```

#### DPDK源码编译和测试

参考：

* http://doc.dpdk.org/guides/linux_gsg/build_dpdk.html
* http://doc.dpdk.org/guides/linux_gsg/quick_start.html
* https://blog.51cto.com/10017068/2107562


```
git clone https://github.com/DPDK/dpdk.git
git checkout v20.02
pip3 install meson ninja
meson build
ninja
sudo ninja install
ldconfig
```

x86平台上使用

```c
make config T=x86_64-native-linux-gcc   
export RTE_SDK=/usr/local    # 指定DPDK的安装路径 
export RTE_TARGET=x86_64-native-linuxapp-gcc  # 指定TARGET名称
make -j
```
编译出来的目标文件默认存放路径是：
```
$RTE_SDK/$RTE_TARGET

例如： testpmd应用路径
$RTE_SDK/$RTE_TARGET/app/testpmd
```

安装到系统目录下，fedora下默认的DESTDIR=/usr/local目录：
```
make install // install to /usr/local/share/dpdk
```

配置静态大页，2M大页可以动态配置但1G大页还是要重启虚拟机。
```
echo 1024 > /sys/kernel/mm/hugepages/hugepages-2048kB/nr_hugepages
或者numa系统上
echo 1024 > /sys/devices/system/node/node0/hugepages/hugepages-2048kB/nr_hugepages
echo 1024 > /sys/devices/system/node/node1/hugepages/hugepages-2048kB/nr_hugepages
挂在hugepagetlbfs文件系统
mkdir /mnt/huge
mount -t hugetlbfs nodev /mnt/huge
写fstab
nodev /mnt/huge hugetlbfs defaults 0 0
或者配置内核参数
default_hugepagesz=2M hugepagesz=2M hugepages=1024
```

```
绑定驱动到vfio-pci
sudo modprobe vfio vfio-pci
sudo ./usertools/dpdk-devbind.py --bind=vfio-pci 0000:00:1f.6
```
绑定好了之后确认下是否成功了
```
$ lspci -vvvs 0000:00:1f.6
00:1f.6 Ethernet controller: Intel Corporation Ethernet Connection (2) I219-V
	Subsystem: Gigabyte Technology Co., Ltd Device e000
	Control: I/O- Mem- BusMaster- SpecCycle- MemWINV- VGASnoop- ParErr- Stepping- SERR- FastB2B- DisINTx+
	Status: Cap+ 66MHz- UDF- FastB2B- ParErr- DEVSEL=fast >TAbort- <TAbort- <MAbort- >SERR- <PERR- INTx-
	Interrupt: pin A routed to IRQ 16
	Region 0: Memory at ef500000 (32-bit, non-prefetchable) [disabled] [size=128K]
	Capabilities: <access denied>
	Kernel driver in use: vfio-pci
lspci: Unable to load libkmod resources: error -12
```
执行一下helloworld测试用例：
```
╰─$ sudo ./helloworld
[sudo] fang 的密码：
EAL: Detected 8 lcore(s)
EAL: Detected 1 NUMA nodes
EAL: Multi-process socket /var/run/dpdk/rte/mp_socket
EAL: Selected IOVA mode 'VA'
EAL: No available hugepages reported in hugepages-1048576kB
EAL: Probing VFIO support...
EAL: VFIO support initialized
EAL: PCI device 0000:00:1f.6 on NUMA socket -1
EAL:   Invalid NUMA socket, default to 0
EAL:   probe driver: 8086:15b8 net_e1000_em
EAL:   using IOMMU type 1 (Type 1)
hello from core 1
hello from core 2
hello from core 3
hello from core 4
hello from core 5
hello from core 6
hello from core 7
hello from core 0
```
再来测试一下报文转发，执行测试用例testpmd程序，进入交互模式后执行start
```c
sudo ./testpmd -l 0-3 -n 4 -- -i --portmask=0x1 --nb-cores=2

testpmd> start
io packet forwarding - ports=1 - cores=1 - streams=1 - NUMA support enabled, MP allocation mode: native
Logical Core 1 (socket 0) forwards packets on 1 streams:
  RX P=0/Q=0 (socket 0) -> TX P=0/Q=0 (socket 0) peer=02:00:00:00:00:00

  io packet forwarding packets/burst=32
  nb forwarding cores=2 - nb forwarding ports=1
  port 0: RX queue number: 1 Tx queue number: 1
    Rx offloads=0x0 Tx offloads=0x0
    RX queue: 0
      RX desc=256 - RX free threshold=0
      RX threshold registers: pthresh=0 hthresh=0  wthresh=0
      RX Offloads=0x0
    TX queue: 0
      TX desc=256 - TX free threshold=0
      TX threshold registers: pthresh=0 hthresh=0  wthresh=0
      TX offloads=0x0 - TX RS bit threshold=0
```

这时候我的台式机风扇就呜呜跑起来了，因为有一个CPU执行pmd驱动，CPU占用率达到了100%。
```
top - 21:21:17 up  8:30,  3 users,  load average: 0.40, 0.13, 0.04
Tasks: 291 total,   1 running, 290 sleeping,   0 stopped,   0 zombie
%Cpu(s): 12.9 us,  0.3 sy,  0.0 ni, 86.7 id,  0.0 wa,  0.0 hi,  0.0 si,  0.0 st
MiB Mem :  15982.0 total,   6987.8 free,   4255.0 used,   4739.1 buff/cache
MiB Swap:   8192.0 total,   8148.2 free,     43.8 used.  10993.1 avail Mem

    PID USER      PR  NI    VIRT    RES    SHR S  %CPU  %MEM     TIME+ COMMAND
 624935 root      20   0   64.2g  66428  16644 S 100.0   0.4   0:32.82 testpmd
   1578 root      20   0  236660  14648   2768 S   1.0   0.1   4:02.44 phdaemon
 169477 root      20   0  252768  29536   8136 S   0.3   0.2   0:30.76 sssd_kcm
      1 root      20   0  172240  12648   8996 S   0.0   0.1   0:08.36 systemd
```


#### Docker配置内部代理

方法一：写Dockerfile，启动容器OS后传入proxy
```bash
From docker.io/fedora:latest

RUN [-n $http_proxy ] && sed -i "$ a proxy=$http_proxy" /etc/dnf/dnf.conf; true

RUN dnf install -y vim
```

### multifd live migration

Since qemu 4.1.0
```
virsh migrate --live --unsafe --parallel --parallel-connections 4 \
    --migrateuri tcp://192.168.3.33 testvm qemu+tcp://192.168.3.33/system --verbose
```

### check ASLR是否开启

Check if ASLR is currently activated on the system:
```
cat /proc/sys/kernel/randomize_va_space
```
Activate ASLR:
```
echo 0 > /proc/sys/kernel/randomize_va_space
```

### qemu常用hmp/qmp命令

查询qom设备树：
```
virsh qemu-monitor-command openeuler-test --hmp "info qom-tree"
```

查询设备属性：
```
virsh qemu-monitor-command openeuler-test '{"execute": "qom-get", "arguments": {"path": "/machine", "property": "gic-version"}}'
virsh qemu-monitor-command openeuler-test '{"execute": "qom-get", "arguments": {"path": "/machine/unattached/device[1]", "property": "mp-affinity"}}'
```

### AArch64 Qemu Direct Boot
```
QEMU_BIN=/root/fangying/opensrc/qemu/build/aarch64-softmmu/qemu-system-aarch64  
$QEMU_BIN \                                                                     
    -machine virt-4.1,accel=kvm,usb=off,dump-guest-core=off,gic-version=3 \     
    -cpu host \                                                                 
    -smp 1 \                                                                    
    -m 2048 \                                                                   
    -kernel /root/fangying/opensrc/linux/arch/arm64/boot/Image \                
    -append "console=ttyAMA0 root=/dev/vda rw pci=off reboot=k panic=1 " \      
    -drive file=/root/ljj/opensrc/stratovirt/rootfs.ext4,id=rootfs,readonly=off \
    -nographic 
```

### AArch64 QEMU UEFI boot with kernel
```
QEMU_BIN=/root/fangying/opensrc/qemu/build/aarch64-softmmu/qemu-system-aarch64                                                                                                                                  
$QEMU_BIN \                                                                     
    -machine virt-4.1,accel=kvm,usb=off,dump-guest-core=off,gic-version=3 \     
    -cpu host \                                                                 
    -smp 1 \                                                                    
    -m 2048 \                                                                   
    -kernel /root/fangying/opensrc/linux/arch/arm64/boot/Image \                
    -append "console=ttyAMA0 root=/dev/vda rw pci=off reboot=k panic=1 " \      
    -drive file=/usr/share/edk2/aarch64/QEMU_EFI-pflash.raw,if=pflash,format=raw,unit=0,readonly=on \
    -drive file=/var/lib/libvirt/qemu/nvram/fangying_openeuler_VARS.fd,if=pflash,format=raw,unit=1 \
    -drive file=/root/ljj/opensrc/stratovirt/rootfs.ext4,id=rootfs,readonly=off \
    -nographic 
```
### EDK2日志开关
以ArmVirt主板为例，我们为例查看详细的UEFI启动日志，需要打开一个日志开关。
在文件：ArmVirtPkg/ArmVirt.dsc.inc中找到：DEBUG_PRINT_ERROR_LEVEL，
该开关通过bitmask控制日志级别。
```
[Defines]
  DEFINE DEBUG_PRINT_ERROR_LEVEL = 0x8000004F
改为：
  DEFINE DEBUG_PRINT_ERROR_LEVEL = 0xFFFFFFFF
```
然后再编译我们的edk2，使用DEBUG模式:
```
yum install iasl libuuid-devel -y
cd edk2
git submodule update --init
make -C BaseTools -j
NCPUS=`/usr/bin/getconf _NPROCESSORS_ONLN`
BUILD_OPTION="-t GCC5 -n $NCPUS -b DEBUG" 
. ./edksetup.sh
build $BUILD_OPTION
build -t GCC5 -n 128 -b DEBUG -a AARCH64 -p ArmVirtPkg/ArmVirtQemu.dsc
```

### CMake 引入外部库

例如我们将libboundscheck动态库引入工程，需要定义：

* `link_directories`指定libboundscheck动态库的寻找路径；
* `target_link_libraries`指定库名字为boundscheck；
* `target_include_directories`指定头文件查找路径

```
cmake_minimum_required(VERSION 3.15)
project(TestPrjt C)

set(CMAKE_C_STANDARD 99)


link_directories(/usr/local/lib）

add_executable(TestPrjt main.c)
target_link_libraries(TestPrjt boundscheck)
target_include_directories(TestPrjt PRIVATE /usr/local/include/libboundscheck)
```

### VFIO 直通虚拟机

查询网卡的PCI外设号码
```
 sudo ethtool -i enp6s0
[sudo] password for fang: 
driver: alx
version: 5.6.0-rc3+
firmware-version: 
expansion-rom-version: 
bus-info: 0000:00:1f.6
supports-statistics: yes
supports-test: no
supports-eeprom-access: no
supports-register-dump: no
supports-priv-flags: no
```

加载驱动
```
modprobe vfio vfio-pci
```

bind到vfio-pci驱动上
```
readlink /sys/bus/pci/devices/0000:00:1f.6/iommu_group

echo "bind to vfio-pci"
echo 0000:00:1f.6 > /sys/bus/pci/devices/0000:00:1f.6/driver/unbind
echo "vfio-pci" > "/sys/bus/pci/devices/0000:00:1f.6/driver_override"
echo 0000:00:1f.6 > /sys/bus/pci/drivers_probe

echo "bind back"
echo "0000:00:1f.6" > "/sys/bus/pci/devices/0000:00:1f.6/driver/unbind"
echo "0000:00:1f.6" > /sys/bus/pci/drivers_probe
```
启动虚拟机了：
```
gdb --args /home/fang/code/fang/qemu/build/x86_64-softmmu/qemu-system-x86_64 \
        -enable-kvm -m 2048 \
        -boot c \
        -drive driver=qcow2,file=$PWD/centos7.qcow2 \
        -netdev tap,id=tap0,ifname=$E1000_TAP_NAME,script=no \
        -device e1000,netdev=tap0,id=net0 \
        -netdev tap,id=tap1,ifname=$VIRTIO_NET_TAP_NAME,script=no \
        -device virtio-net-pci,netdev=tap1,id=net1,addr=05.0 \
        -device piix3-usb-uhci,id=uhci,addr=04.0 \
        -smp cpus=4 \
        -vnc :88 \
        -cdrom virtio-win-0.1.141.iso \
        -device vfio-pci,host=0000:00:1f.6,id=hostdev0
```

### PL011 串口调试
```
QEMU_BIN=/root/fangying/opensrc/qemu-fangying/build/aarch64-softmmu/qemu-system-aarch64
$QEMU_BIN \                                                                     
    -machine virt-4.0,accel=kvm,gic-version=3 \                                 
    -cpu host \                                                                 
    -smp 1 \                                                                    
    -nographic \                                                                
    -m 512M \                                                                   
    -kernel /root/fangying/opensrc/linux/vmlinux.bin \                          
    -drive id=test,file=/root/fangying/vm/rootfs_arm,format=raw,if=none \       
    -device virtio-blk-device,drive=test \                                      
    -device pci-bridge,chassis_nr=1,bus=pcie.0 \                                                      
    -append 'console=ttyAMA0 root=/dev/vda' \                                   
    -qmp unix:/tmp/qemu.sock,server,nowait \                                    
    -trace events=/tmp/events \                                                 
    -D /var/log/qemu.log 
```

## x86 Direct Boot microvm

```
qemu-system-x86_64 \
   -M microvm,x-option-roms=off,pit=off,pic=off,isa-serial=off,rtc=off \
   -enable-kvm -cpu host -m 512m -smp 2 \
   -kernel vmlinux -append "console=hvc0 root=/dev/vda" \
   -nodefaults -no-user-config -nographic \
   -chardev stdio,id=virtiocon0 \
   -device virtio-serial-device \
   -device virtconsole,chardev=virtiocon0 \
   -drive id=test,file=test.img,format=raw,if=none \
   -device virtio-blk-device,drive=test \
   -netdev tap,id=tap0,script=no,downscript=no \
   -device virtio-net-device,netdev=tap0
```
### Rust调试

运行Rust程序传入RUST_BACKTRACE=full
```
RUST_BACKTRACE=full cargo run ...
```

### Libvirt增加外部接口

```
scripts/check-aclrules.py 白名单
driver-hypervisor.h 定义声明
src/libvirt-domain.c 接口定义实现
src/qemu/qemu-driver.c driver接口实现
remote_driver.c增加定义
src/libvirt_public.syms 增加定义
```

### 虚拟机使用spice协议

```
    <channel type='spicevmc'>                                                                         
     <target type='virtio' name='com.redhat.spice.0' state='connected'/>       
     <alias name='channel4'/>                                                  
     <address type='virtio-serial' controller='0' bus='0' port='5'/>           
    </channel>                                                                  
    <input type='tablet' bus='usb'>                                             
     <alias name='input0'/>                                                    
     <address type='usb' bus='0' port='1'/>                                    
    </input>                                                                    
    <input type='keyboard' bus='usb'>                                           
     <alias name='input1'/>                                                    
     <address type='usb' bus='0' port='2'/>                                    
    </input>                                                                    
    <graphics type='spice' port='5900' autoport='yes' listen='0.0.0.0'>         
    <listen type='address' address='0.0.0.0'/>                                
    </graphics>                                                                 
    <video>                                                                     
     <model type='virtio' vram='16384' heads='1' primary='yes'/>               
     <alias name='video0'/>                                                    
     <address type='pci' domain='0x0000' bus='0x03' slot='0x04' function='0x0'/>
    </video>   
```

## 一个较为完整的虚拟机

```
/usr/bin/qemu-system-x86_64 \
	-name guest=fangying_uefi,debug-threads=on \
	-S \
	-object secret,id=masterKey0,format=raw,file=/var/lib/libvirt/qemu/domain-2-fangying_uefi/master-key.aes \
	-machine pc-i440fx-4.1,accel=kvm,usb=off,dump-guest-core=off \
	-cpu host,kvm-pv-eoi=on \
	-drive file=/usr/share/edk2/ovmf/OVMF.fd,if=pflash,format=raw,unit=0,readonly=on \
	-drive file=/usr/share/edk2/ovmf/OVMF_VARS.fd,if=pflash,format=raw,unit=1 \
	-m 16384 \
	-overcommit mem-lock=off \
	-smp 16,sockets=16,cores=1,threads=1 \
	-uuid a1f00325-9972-486e-a127-6f0b14b44a3f \
	-no-user-config \
	-nodefaults \
	-chardev socket,id=charmonitor,fd=30,server,nowait \
	-mon chardev=charmonitor,id=monitor,mode=control \
	-rtc base=utc,clock=vm,driftfix=slew \
	-no-hpet \
	-global kvm-pit.lost_tick_policy=delay \
	-no-shutdown \
	-boot strict=on \
	-device piix3-usb-uhci,id=usb,bus=pci.0,addr=0x1.0x2 \
	-device usb-ehci,id=usb1,bus=pci.0,addr=0x4 \
	-device nec-usb-xhci,id=usb2,bus=pci.0,addr=0x5 \
	-device virtio-scsi-pci,id=scsi0,bus=pci.0,addr=0x6 \
	-device virtio-serial-pci,id=virtio-serial0,bus=pci.0,addr=0x7 \
	-drive file=/mnt/sdc/fangying/x86/fangying_uefi.qcow2,format=qcow2,if=none,id=drive-virtio-disk0,cache=none,aio=native \
	-device virtio-blk-pci,scsi=off,bus=pci.0,addr=0x9,drive=drive-virtio-disk0,id=virtio-disk0,bootindex=1,write-cache=on \
	-netdev tap,fd=33,id=hostnet0,vhost=on,vhostfd=34 \
	-device virtio-net-pci,netdev=hostnet0,id=net0,mac=52:24:01:d9:dc:53,bus=pci.0,addr=0x3 \
	-chardev pty,id=charserial0 \
	-device isa-serial,chardev=charserial0,id=serial0 \
	-vnc 0.0.0.0:0 \
	-device cirrus-vga,id=video0,bus=pci.0,addr=0x2 \
	-device virtio-balloon-pci,id=balloon0,bus=pci.0,addr=0x8 \
	-sandbox on,obsolete=deny,elevateprivileges=deny,spawn=deny,resourcecontrol=deny \
	-msg timestamp=on

```

### cpu topology

```
QEMU_BIN=/root/fangying/opensrc/qemu-fangying/build/aarch64-softmmu/qemu-system-aarch64
$QEMU_BIN \                                                                     
    -machine virt-4.1,accel=kvm,usb=off,dump-guest-core=off,gic-version=3 \     
    -cpu host \                                                                 
    -drive file=/usr/share/edk2/aarch64/QEMU_EFI-pflash.raw,if=pflash,format=raw,unit=0,readonly=on \
    -drive file=/var/lib/libvirt/qemu/nvram/fangying_openeuler_VARS.fd,if=pflash,format=raw,unit=1 \
    -m 8192 \                                                                   
    -smp 4,sockets=1,dies=1,cores=4,threads=1 \                                 
    -no-user-config \                                                           
    -nodefaults \                                                               
    -rtc base=utc \                                                             
    -no-shutdown \                                                              
    -device pcie-root-port,port=0x8,chassis=1,id=pci.1,bus=pcie.0,multifunction=on,addr=0x1 \
    -device pcie-root-port,port=0x9,chassis=2,id=pci.2,bus=pcie.0,addr=0x1.0x1 \
    -device pcie-pci-bridge,id=pci.3,bus=pci.1,addr=0x0 \                       
    -device pcie-root-port,port=0xa,chassis=4,id=pci.4,bus=pcie.0,addr=0x1.0x2 \
    -device pcie-root-port,port=0xb,chassis=5,id=pci.5,bus=pcie.0,addr=0x1.0x3 \
    -device pcie-root-port,port=0xc,chassis=6,id=pci.6,bus=pcie.0,addr=0x1.0x4 \
    -device pcie-root-port,port=0xd,chassis=7,id=pci.7,bus=pcie.0,addr=0x1.0x5 \
    -device pcie-root-port,port=0xe,chassis=8,id=pci.8,bus=pcie.0,addr=0x1.0x6 \
    -device pcie-root-port,port=0xf,chassis=9,id=pci.9,bus=pcie.0,addr=0x1.0x7 \
    -device usb-ehci,id=usb,bus=pci.3,addr=0x1 \                                
    -device virtio-scsi-pci,id=scsi0,bus=pci.4,addr=0x0 \                       
    -device virtio-serial-pci,id=virtio-serial0,bus=pci.3,addr=0x2 \            
    -chardev pty,id=charserial0 \                                               
    -serial chardev:charserial0 \                                               
    -device usb-tablet,id=input0,bus=usb.0,port=1 \                             
    -device usb-kbd,id=input1,bus=usb.0,port=2 \                                
    -vnc 0.0.0.0:99 \                                                           
    -device virtio-gpu-pci,id=video0,max_outputs=1,bus=pci.3,addr=0x4  
```
## x86 UEFI Direct Boot
```
qemu-system-x86_64 \                                                            
    -M pc \                                                                     
    -cpu host \                                                                 
    -smp cpus=4 \                                                               
    -enable-kvm \                                                               
    -m 2048 \                                                                   
    -nographic \                                                                
    -net none \                                                                 
    -drive if=pflash,format=raw,unit=0,file=/home/fang/code/opensrc/edk2/Build/OvmfX64/DEBUG_GCC5/FV/OVMF_CODE.fd,readonly=on \                                   
    -drive if=pflash,format=raw,unit=1,file=/home/fang/code/opensrc/edk2/Build/OvmfX64/DEBUG_GCC5/FV/OVMF_VARS.fd \
    -device virtio-blk-pci,id=blk0,drive=image \                                
    -device piix3-usb-uhci,id=uhci \                                            
    -device usb-tablet \                                                        
    -drive if=none,id=image,file=$PWD/dummy.raw,format=raw \                    
    -monitor telnet::12345,server,nowait \                                      
    -serial stdio
```

## Make rootfs using installroot

```
sudo dnf --releasever 33 --nogpgcheck --installroot /mnt/rootfs install systemd yum passwd dnf fedora-release --noplugins
sed -i "s|root:x|root:|" etc/password
```

## QOM qmp example

```
virsh qemu-monitor-command vmname '{"execute": "qom-list-types}"' --pretty
virsh qemu-monitor-command vmname '{"execute": "qom-list", "arguments": {"path": "/machine/"}}' --pretty
virsh qemu-monitor-command vmname '{"execute": "qom-list", "arguments": {"path": "/machine/peripheral"}}' --pretty
virsh qemu-monitor-command vmname '{"execute": "qom-list", "arguments": {"path": "/machine/unattached"}}' --pretty
virsh qemu-monitor-command vmname '{"execute": "device-list-properities, "arguments": {"typename": "virtio-serial-pci"}}' --pretty
```

## 使用 Virsh console 登陆虚拟机

需要给虚拟机启用一个服务：
```
grubby --update-kernel=ALL --args=console=ttyS0,115200
systemctl start serial-getty@ttyS0.service
```

## 配置SRIOV网卡

注意：virtio-net网卡的mac地址是通过virtio_net_config配置给虚拟机的。·
```
...
 <devices>
   ...
   <interface type='hostdev' managed='yes'>
     <source>
       <address type='pci' domain='0' bus='11' slot='16' function='0'/>
     </source>
     <mac address='52:54:00:6d:90:02'>
     <vlan>
        <tag id='42'/>
     </vlan>
     <virtualport type='802.1Qbh'>
       <parameters profileid='finance'/>
     </virtualport>
   </interface>
   ...
 </devices>
```