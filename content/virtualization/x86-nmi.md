Title:  Virt NMI Emulation
Date: 2019-3-16 23:00
Modified: 2019-3-16 23:00
Tags: virtualization
Slug: x86-nmi
Status: published
Authors: Yori Fang
Summary: x86 NMI Emulation

### X86 NMI中断

NMI（Nonmaskable Interrupt）中断之所以称之为NMI的原因是：这种类型的中断不能被CPU的EFLAGS寄存器的IF标志位所屏蔽。
而对于可屏蔽中断而言只要IF标志位被清理（例如：CPU执行了cli指令），那么处理器就会禁止INTR Pin和Local APIC上接收到的内部中断请求。
NMI中断有两种触发方式：

* 外部硬件通过CPU的 NMI Pin 去触发（硬件触发）
* 软件向CPU系统总线上投递一个NMI类型中断（软件触发）

当CPU从上述两种中断源接收到NMI中断后就立刻调用vector=2（中断向量为2）的中断处理函数来处理NMI中断。
Intel SDM, Volume 3, Chapter 6.7 Nonmaskable Interrupt章节指出：
当一个NMI中断处理函数正在执行的时候，处理器会block后续的NMI直到中断处理函数执行IRET返回。

### 1.NMI中断的用途

NMI中断的主要用途有两个：

* 用来告知操作系统有硬件错误（Hardware Failure）
* 用来做看门狗定时器，检测CPU死锁

除了用来，看门狗定时器在Linux内核中被用来进行死锁检测（Hard Lockup），当CPU长时间不喂狗的时候会触发看门狗超时，
这时候向操作系统注入NMI中断，告知系统异常。

### 2.NMI中断虚拟化

我们可以通过virsh inject-nmi VMname命令给虚拟机注入NMI中断。

QEMU这边的调用栈为：
```c
qmp_inject_nmi
  => nmi_monitor_handle
    => nmi_children  //传入了struct do_nmi_s ns
      => do_nmi
        => nc->nmi_monitor_handler
          => x86_nmi
            => apic_deliver_nmi
              => kvm_apic_external_nmi
                => do_inject_external_nmi
                  => kvm_vcpu_ioctl(cpu, KVM_NMI)
```
其中`nmi_children`的设计比较特别，它调用了一个object_child_foreach函数，
会沿着QOM对象树往下遍历，遍历的时候调用`do_nmi`函数。
值得注意的是这里`NMIClass`被设计为一个`interface`类型，而主板类`MachineClass`实现了这个接口。
```c
static const TypeInfo pc_machine_info = {
    .name = TYPE_PC_MACHINE,
    .parent = TYPE_MACHINE,
    .abstract = true,
    .instance_size = sizeof(PCMachineState),
    .instance_init = pc_machine_initfn,
    .class_size = sizeof(PCMachineClass),
    .class_init = pc_machine_class_init,
    .interfaces = (InterfaceInfo[]) {
         { TYPE_HOTPLUG_HANDLER },
         { TYPE_NMI },
         { }
    },
};

```
主板类是一个抽象类，实现了`TYPE_HOTPLUG_HANDLER`和`TYPE_NMI`接口，有点Java面向对象的意思。
```
static int do_nmi(Object *o, void *opaque)
{
    struct do_nmi_s *ns = opaque;
    NMIState *n = (NMIState *) object_dynamic_cast(o, TYPE_NMI);  // 对象动态转换

    if (n) {      // 如果能够成功转换，说明这个对象实现了 NMI 接口，那么可以调用这个对象的处理函数
        NMIClass *nc = NMI_GET_CLASS(n);

        ns->handled = true;
        nc->nmi_monitor_handler(n, ns->cpu_index, &ns->err);   // nmi_monitor_handler 是NMI接口的方法
        if (ns->err) {
            return -1;
        }
    }
    nmi_children(o, ns);

    return 0;
}
```
`nmi_monitor_handle`函数中调用了nmi_children(object_get_root(), &ns)，从Root Object对象开始向下遍历，
在对象上调用`do_nmi`方法，而`do_nmi`里面会检测这个对象是否实现了`TYPE_NMI`类型的接口，
如果这个对象实现了这个接口，那么调用`mi_monitor_handler`方法来发送NMI中断。这里充分体现了QOM面向对象思想。
在看代码的时候，我们可以找到`pc_machine_class_init`里面注册了`mi_monitor_handler`。
这里还不太理解的是x86_nmi里面会遍历所有的CPU，对每个CPU都注了NMI，有这个必要吗？

```c
static void pc_machine_class_init(ObjectClass *oc, void *data) 
{
  NMIClass *nc = NMI_CLASS(oc);       // 把对象转换为NMIClass类型对象
  nc->nmi_monitor_handler = x86_nmi;  // 实现接口方法
}
```

QEMU调用完kvm_vcpu_ioctl(cpu, KVM_NMI)之后就开始进入KVM内核进行NMI中断注入，
毕竟LAPIC和IOAPIC现在都放到KVM模拟来提升中断注入的实时性。
```c
KVM x86.c
kvm_arch_vcpu_ioctl
  => kvm_vcpu_ioctl_nmi
    => kvm_inject_nmi
```
kvm_inject_nmi 里面将nmi_queued加1，然后make KVM_REQ_NMI request。
为了防止中断嵌套KVM做了一些额外的处理。
```
 void kvm_inject_nmi(struct kvm_vcpu *vcpu)
  {
          atomic_inc(&vcpu->arch.nmi_queued);
          kvm_make_request(KVM_REQ_NMI, vcpu);
  }
```
这样VCPU在下次VM Exit的时候会check标志位，进行NMI注入。 
```c
static int vcpu_enter_guest(struct kvm_vcpu *vcpu)
{
		if (kvm_check_request(KVM_REQ_NMI, vcpu))
			process_nmi(vcpu);
}

// 由于NMI中断不能嵌套，这里做了防呆，第一process_nmi的时候limit=2，
static void process_nmi(struct kvm_vcpu *vcpu)
{
	unsigned limit = 2;

	/*
	 * x86 is limited to one NMI running, and one NMI pending after it.
	 * If an NMI is already in progress, limit further NMIs to just one.
	 * Otherwise, allow two (and we'll inject the first one immediately).
	 */
	if (kvm_x86_ops->get_nmi_mask(vcpu) || vcpu->arch.nmi_injected)
		limit = 1;

	vcpu->arch.nmi_pending += atomic_xchg(&vcpu->arch.nmi_queued, 0);
	vcpu->arch.nmi_pending = min(vcpu->arch.nmi_pending, limit);
	kvm_make_request(KVM_REQ_EVENT, vcpu);
}

static int inject_pending_event(struct kvm_vcpu *vcpu, bool req_int_win)
{
  kvm_x86_ops->set_nmi(vcpu);  // call vmx_inject_nmi
}
```
最后调用`vmx_inject_nmi`函数注入NMI中断给虚拟机（也是通过写VMCS VM_ENTRY_INTR_INFO_FIELD域来实现）。

### 3.参考文献
[Intel SDM Volume 3, Chapter 6](https://software.intel.com/sites/default/files/managed/39/c5/325462-sdm-vol-1-2abcd-3abcd.pdf)
