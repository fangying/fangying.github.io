Title:  Lightweight Micro Virtual Machines
Date: 2019-6-25 23:00
Modified: 2019-6-25 23:00
Tags: virtualization
Slug: microVM
Authors: Yori Fang
Summary: microvm

## 轻量级虚拟化技术

云计算领域经过近13年的发展后，整个云软件栈已经变得大而全了。
例如：Openstack + KVM解决方案，这套IaaS解决方案已经比较完善了。
以AWS为首的云计算服务提供商为了更细粒度的划分计算资源，提出了Serverless模型。
为了更好地服务Serverless模型，涌现了若干个轻量级虚拟化方案。
这里简单介绍一下当前已有的４种解决方案．它们分别是Firecracker, gVisor, Rust-VMM 和NEMU。

轻量级虚拟化方案的设计理念是围绕着：安全、快速、轻量、高并高密度，这几个共同点展开的。
下面对这几个轻量级虚拟机化方案进行简要的对比介绍。

![Light Weight Virt](../images/lightweight-virt.png)

### AWS Firecracker

Firecracker由AWS发布并将firecracker开源，
它的定位是面向Serverless计算业务场景。
Firecracker本质上是基于KVM的轻量级的microVM，
可以同时支持多租户容器和FaaS场景。
Security和Fast是firecracker的首要设计目标。
它的设计理念可以概括为：

* 基于KVM
* 精简的设备集（极简主义）
* 基于Rust语言（Builtin Safety）
* 定制的guest kernel（快速启动）
* 优化内存开销（使用musl c）

Firecracker使用了极为精简的设备模型（仅有几个关键的模拟设备），目的是减少攻击面已提升安全性。
同时这irecracker使用了一个精简的内核（基于Apline Linux），这使得Firecracker可以做在125ms内拉起一个虚拟机。
Firecracker使用musl libc而不是gnu libc，能够将虚拟机的最低内存开销小到5MB。
注：一个Standard MicroVM的规格是1U 128M

Fircracker的架构图如下：

![FireCracker](https://firecracker-microvm.github.io/img/diagram-desktop@3x.png)

### google gVisor

gVisor由Google出品，目的是为了加强Container的隔离性但走的是另外一条路子。
gVisor是Container Runtime Sandbox，本质是一种进程级虚拟化技术，走的是沙箱的路子。
它的设计理念可以概括为：

* 基于ptrace syscall截获模拟
* runsc直接对接Docker & Kubernates
* 不需要模拟Devices、Interrupts和IO
* 文件系统隔离机制

gVisor的架构如下图：

![gVisor](https://static.lwn.net/images/conf/2018/kubecon/gvisor.png)


gVisor由3个组件构成，Runsc、Sentry和Gopher。
Runsc向上提供Docker & Kubernates的接口(OCI)，Sentry截获syscall并进行模拟，Gopher用来做9p将文件系统呈现给沙箱内部App。

gVisor当前的设计模式中带来的问题有：

* 不适用于intensive syscall场景
* 对sysfs、procfs支持不完整
* 目前仅支持240个syscall的模拟
* 对ARM架构支持还不友好
* 对KVM的支持尚处于experimental阶段

更多的信息可以参考：

[https://lwn.net/Articles/754433/](https://lwn.net/Articles/754433)

[Kubecon gVisor Talk](https://schd.ws/hosted_files/kccnceu18/47/Container%20Isolation%20at%20Scale.pdf)

### Rust-VMM

Rust-VMM是一个新项目，目前还处于开发阶段。它的愿景是帮助社区构建自定义的VMM和Hypervisor。
使得我们可以能够像搭积木一样去构建一个适用于我们自己应用场景的VMM，而不用去重复造轮子。
社区的参与者包括了Alibaba, AWS, Cloud Base, Crowdstrike, Intel, Google, Red Hat等。
它的设计理念是：

* 合并CrosVM项目和Firecracker项目
* 提供更安全、更精简的代码集（Build with Rust Language）
* 采用基于Rust的crates组件开发模式
* 高度可定制

项目目前在开发阶段，更多的信息见：[https://github.com/rust-vmm](https://github.com/rust-vmm)

### NEMU

NEMU项目由Intel领导开发，重点是面向IaaS云化场景。
NEMU是基于QEMU 4.0进行开发的，有可能会被QEMU社区接收到upstream中。
NEMU的涉及理念可以概括为：

* 基于QEMU/KVM
* 精简的设备集（no legacy devices)
* 新的virt类型主板
* 优化内存开销
* 定制的Guest OS(基于Clear Linux）
* 编译时可裁剪

个人认为NEMU项目如果用来面向Serverless场景是不够精简的，
它的完备设备集还是很大（包含约20种Moderm设备）。
NEMU选择支持seabios和UEFI目的就是要兼容IaaS方案，所以它的代码集还是很大的。
NEMU的做法更像是对QEMU做了一个减法，让QEMU更加聚焦X86和ARM的云OS场景。
NEMU的好处是原生支持设备直通、热迁移等高级特性。


