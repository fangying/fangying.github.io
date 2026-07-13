Title: Linux 5.15 KVM vcpu_enter_guest 函数行级注释
Date: 2026-7-13 08:00
Modified: 2026-7-13 17:00
Tags: virtualization, kvm, kernel
Slug: vcpu-enter-guest
Status: published
Authors: Yori Fang
Summary: 对 Linux 5.15 KVM x86 核心函数 vcpu_enter_guest 的行级注释，覆盖 VM Entry 前的请求处理、事件注入、状态同步与 VM Exit 后的清理派发流程。

# Linux 5\.15\.120 KVM vcpu\_enter\_guest 函数行级注释

**函数位置**：`arch/x86/kvm/x86.c`，第 9697 \- 10045 行\(共约 348 行\)

**功能概述**：这是 KVM x86 架构中控制 vCPU 进入 Guest 模式\(VM Entry\)的核心函数。它在执行 VMLAUNCH/VMRESUME 之前完成所有必要的请求处理、事件注入、状态同步和硬件准备工作;在 VM Exit 之后进行必要的清理并派发退出处理。

**返回值**:`> 0` 表示可继续运行 Guest;`0` 表示需要返回用户态处理\(如 KVM\_EXIT\_\*\);`< 0` 表示出错。

## 1\. 函数签名与局部变量

```c
static int vcpu_enter_guest(struct kvm_vcpu *vcpu)
{
    int r;                                             // 返回值:>0 继续 Guest,0 返回用户态,<0 出错
    bool req_int_win =                                 // 是否需要打开"中断窗口"(让 Guest 尽快接受用户态注入的中断)
        dm_request_for_irq_injection(vcpu) &&         //   条件 1:device model(qemu)请求注入 IRQ
        kvm_cpu_accept_dm_intr(vcpu);                  //   条件 2:当前 vCPU 处于可接受中断的状态
    fastpath_t exit_fastpath;                          // VM Exit 的快速路径类型(NONE / REENTER_GUEST / EXIT_HANDLED)

    bool req_immediate_exit = false;                   // 是否需要在进入 Guest 后立刻触发一次 VM Exit
                                                       // (用于注入事件后立刻回到 KVM 检查后续状态)

```

## 2\. 前置检查:脏页环缓冲区\(dirty ring\)是否已满

```c
/* Forbid vmenter if vcpu dirty ring is soft-full */
    // 若开启了脏页环(用于热迁移的脏页跟踪),且环形缓冲区已"软满",
    // 则禁止进入 Guest,返回用户态腾出空间避免 Guest 继续脏页导致硬满溢出。
    if (unlikely(vcpu->kvm->dirty_ring_size &&
             kvm_dirty_ring_soft_full(&vcpu->dirty_ring))) {
        vcpu->run->exit_reason = KVM_EXIT_DIRTY_RING_FULL;  // 通知用户态原因
        trace_kvm_dirty_ring_exit(vcpu);                    // tracepoint 记录
        r = 0;                                              // 0 表示需要退出到用户态
        goto out;
    }

```

## 3\. 处理挂起的 KVM 请求\(kvm\_request\_pending\)

下面的整段 `if (kvm_request_pending(vcpu))` 用于集中处理由其他 CPU、qemu 用户态或 KVM 自身发起的各类异步请求\(KVM\_REQ\_\*\)。每个 `kvm_check_request()` 在读取标志的同时清除该标志,保证幂等性。

```c
if (kvm_request_pending(vcpu)) {
        // === 3.1 致命请求:VM 已损坏,直接返回 -EIO ===
        if (kvm_check_request(KVM_REQ_VM_BUGGED, vcpu)) {
            r = -EIO;
            goto out;
        }

        // === 3.2 嵌套虚拟化:加载嵌套状态所需的物理页 ===
        // 若失败(如 gpa 无效),返回用户态处理
        if (kvm_check_request(KVM_REQ_GET_NESTED_STATE_PAGES, vcpu)) {
            if (unlikely(!kvm_x86_ops.nested_ops->get_nested_state_pages(vcpu))) {
                r = 0;
                goto out;
            }
        }

        // === 3.3 MMU 重载:卸载当前影子页表/EPT 根,下面 kvm_mmu_reload 会重建 ===
        if (kvm_check_request(KVM_REQ_MMU_RELOAD, vcpu))
            kvm_mmu_unload(vcpu);

        // === 3.4 迁移定时器:vCPU 换 CPU 后需要重新迁移 APIC/PIT 定时器 ===
        if (kvm_check_request(KVM_REQ_MIGRATE_TIMER, vcpu))
            __kvm_migrate_timers(vcpu);

        // === 3.5 主时钟更新:同步 kvmclock 主参考时间 ===
        if (kvm_check_request(KVM_REQ_MASTERCLOCK_UPDATE, vcpu))
            kvm_gen_update_masterclock(vcpu->kvm);

        // === 3.6 全局 kvmclock 更新(所有 vCPU 都需要更新) ===
        if (kvm_check_request(KVM_REQ_GLOBAL_CLOCK_UPDATE, vcpu))
            kvm_gen_kvmclock_update(vcpu);

        // === 3.7 单 vCPU 的 kvmclock 更新(TSC 频率变化、热插拔等) ===
        if (kvm_check_request(KVM_REQ_CLOCK_UPDATE, vcpu)) {
            r = kvm_guest_time_update(vcpu);
            if (unlikely(r))
                goto out;                              // 更新失败直接退出
        }

        // === 3.8 同步影子页表根(shadow page 需要 write-protect 时) ===
        if (kvm_check_request(KVM_REQ_MMU_SYNC, vcpu))
            kvm_mmu_sync_roots(vcpu);

        // === 3.9 重新加载页表根到硬件寄存器(CR3 / EPTP) ===
        if (kvm_check_request(KVM_REQ_LOAD_MMU_PGD, vcpu))
            kvm_mmu_load_pgd(vcpu);

        // === 3.10 全 TLB flush 请求(所有 ASID / VPID) ===
        if (kvm_check_request(KVM_REQ_TLB_FLUSH, vcpu)) {
            kvm_vcpu_flush_tlb_all(vcpu);

            /* Flushing all ASIDs flushes the current ASID... */
            // 既然全部刷了,当前 ASID 的请求也就没必要再刷一次,顺手清除
            kvm_clear_request(KVM_REQ_TLB_FLUSH_CURRENT, vcpu);
        }
        // 处理其他细粒度 TLB flush(如 TLB_FLUSH_CURRENT / TLB_FLUSH_GUEST)
        kvm_service_local_tlb_flush_requests(vcpu);

        // === 3.11 上报 TPR 访问:Guest 修改了 TPR,通知用户态(常见于旧 Windows) ===
        if (kvm_check_request(KVM_REQ_REPORT_TPR_ACCESS, vcpu)) {
            vcpu->run->exit_reason = KVM_EXIT_TPR_ACCESS;
            r = 0;
            goto out;
        }

        // === 3.12 Triple Fault(三重错):在嵌套场景中通知 L1,否则关机 ===
        if (kvm_check_request(KVM_REQ_TRIPLE_FAULT, vcpu)) {
            if (is_guest_mode(vcpu)) {
                // Guest-in-Guest:让 L1 hypervisor 处理这次 triple fault
                kvm_x86_ops.nested_ops->triple_fault(vcpu);
            } else {
                vcpu->run->exit_reason = KVM_EXIT_SHUTDOWN;
                vcpu->mmio_needed = 0;                 // 清除 mmio 待处理标记
                r = 0;
                goto out;
            }
        }

        // === 3.13 异步缺页(Async Page Fault):目标页尚在换入,合成 HLT 让 Guest 等待 ===
        if (kvm_check_request(KVM_REQ_APF_HALT, vcpu)) {
            /* Page is swapped out. Do synthetic halt */
            vcpu->arch.apf.halted = true;
            r = 1;                                     // 返回 1:vcpu_run 会走 halt 逻辑
            goto out;
        }

        // === 3.14 更新 steal time(半虚拟化时钟偷取时间统计) ===
        if (kvm_check_request(KVM_REQ_STEAL_UPDATE, vcpu))
            record_steal_time(vcpu);

        // === 3.15 处理 SMI(系统管理中断) ===
        if (kvm_check_request(KVM_REQ_SMI, vcpu))
            process_smi(vcpu);

        // === 3.16 处理 NMI(不可屏蔽中断) ===
        if (kvm_check_request(KVM_REQ_NMI, vcpu))
            process_nmi(vcpu);

        // === 3.17 PMU 事件处理(性能计数器溢出等) ===
        if (kvm_check_request(KVM_REQ_PMU, vcpu))
            kvm_pmu_handle_event(vcpu);

        // === 3.18 投递 PMU 中断(PMI)给 Guest ===
        if (kvm_check_request(KVM_REQ_PMI, vcpu))
            kvm_pmu_deliver_pmi(vcpu);

        // === 3.19 IOAPIC EOI 退出:某中断向量需要在 EOI 时退出到用户态 ===
        if (kvm_check_request(KVM_REQ_IOAPIC_EOI_EXIT, vcpu)) {
            BUG_ON(vcpu->arch.pending_ioapic_eoi > 255);   // 向量号必须合法
            if (test_bit(vcpu->arch.pending_ioapic_eoi,
                     vcpu->arch.ioapic_handled_vectors)) {
                vcpu->run->exit_reason = KVM_EXIT_IOAPIC_EOI;
                vcpu->run->eoi.vector =
                        vcpu->arch.pending_ioapic_eoi;
                r = 0;
                goto out;
            }
        } 

        // === 3.20 扫描 IOAPIC,更新 EOI 退出位图 ===
        if (kvm_check_request(KVM_REQ_SCAN_IOAPIC, vcpu))
            vcpu_scan_ioapic(vcpu);

        // === 3.21 加载 EOI 退出位图(APICv 相关) ===
        if (kvm_check_request(KVM_REQ_LOAD_EOI_EXITMAP, vcpu))
            vcpu_load_eoi_exitmap(vcpu);

        // === 3.22 重新加载 APIC access page(虚拟化 APIC 访问页) ===
        if (kvm_check_request(KVM_REQ_APIC_PAGE_RELOAD, vcpu))
            kvm_vcpu_reload_apic_access_page(vcpu);

        // === 3.23 Hyper-V 半虚拟化:Guest crash 通知 ===
        if (kvm_check_request(KVM_REQ_HV_CRASH, vcpu)) {
            vcpu->run->exit_reason = KVM_EXIT_SYSTEM_EVENT;
            vcpu->run->system_event.type = KVM_SYSTEM_EVENT_CRASH;
            r = 0;
            goto out;
        }

        // === 3.24 Hyper-V:Guest 请求 reset ===
        if (kvm_check_request(KVM_REQ_HV_RESET, vcpu)) {
            vcpu->run->exit_reason = KVM_EXIT_SYSTEM_EVENT;
            vcpu->run->system_event.type = KVM_SYSTEM_EVENT_RESET;
            r = 0;
            goto out;
        }

        // === 3.25 Hyper-V 显式退出请求(vmexit 到用户态) ===
        if (kvm_check_request(KVM_REQ_HV_EXIT, vcpu)) {
            struct kvm_vcpu_hv *hv_vcpu = to_hv_vcpu(vcpu);

            vcpu->run->exit_reason = KVM_EXIT_HYPERV;
            vcpu->run->hyperv = hv_vcpu->exit;
            r = 0;
            goto out;
        }

        /*
         * KVM_REQ_HV_STIMER has to be processed after
         * KVM_REQ_CLOCK_UPDATE, because Hyper-V SynIC timers
         * depend on the guest clock being up-to-date
         */
        // === 3.26 Hyper-V SynIC 合成定时器(必须在 CLOCK_UPDATE 之后) ===
        if (kvm_check_request(KVM_REQ_HV_STIMER, vcpu))
            kvm_hv_process_stimers(vcpu);

        // === 3.27 APICv(APIC 虚拟化)启用状态更新 ===
        if (kvm_check_request(KVM_REQ_APICV_UPDATE, vcpu))
            kvm_vcpu_update_apicv(vcpu);

        // === 3.28 异步缺页已就绪:注入 APF 就绪事件给 Guest ===
        if (kvm_check_request(KVM_REQ_APF_READY, vcpu))
            kvm_check_async_pf_completion(vcpu);

        // === 3.29 MSR filter 已变化:通知底层(VMX/SVM)重建 MSR bitmap ===
        if (kvm_check_request(KVM_REQ_MSR_FILTER_CHANGED, vcpu))
            static_call(kvm_x86_msr_filter_changed)(vcpu);

        // === 3.30 更新 CPU 脏页跟踪配置(PML 等) ===
        if (kvm_check_request(KVM_REQ_UPDATE_CPU_DIRTY_LOGGING, vcpu))
            static_call(kvm_x86_update_cpu_dirty_logging)(vcpu);
    }

```

## 4\. 事件注入\(异常 / 中断 / NMI / SMI\)

```c
// 触发条件:
    //   - 有 KVM_REQ_EVENT 请求(有新事件待注入)
    //   - 或需要打开中断窗口(用户态待注入 IRQ)
    //   - 或 Xen 半虚拟化有待注入中断
    if (kvm_check_request(KVM_REQ_EVENT, vcpu) || req_int_win ||
        kvm_xen_has_interrupt(vcpu)) {
        ++vcpu->stat.req_event;                        // 统计计数

        // 处理 APIC 事件:INIT / SIPI / start-up 等
        r = kvm_apic_accept_events(vcpu);
        if (r < 0) {
            r = 0;
            goto out;
        }
        // 若收到 INIT,vCPU 进入等待 SIPI 状态,直接返回让 vcpu_run 决策
        if (vcpu->arch.mp_state == KVM_MP_STATE_INIT_RECEIVED) {
            r = 1;
            goto out;
        }

        // 核心:选择并注入一个待处理事件(异常优先级 > NMI > 中断)
        // 若注入后需要立即 VM Exit(如注入 IRQ 后想立刻检查更多事件),
        // 会把 req_immediate_exit 置 true
        r = inject_pending_event(vcpu, &req_immediate_exit);
        if (r < 0) {
            r = 0;
            goto out;
        }
        // 用户态有 IRQ 待注入,请求硬件打开中断窗口(等 Guest 一开中断就 VM Exit)
        if (req_int_win)
            static_call(kvm_x86_enable_irq_window)(vcpu);

        // 同步虚拟 APIC 状态:更新 CR8 拦截策略,把 KVM 的 vAPIC 同步到 Guest 内存里的 vapic_page
        if (kvm_lapic_enabled(vcpu)) {
            update_cr8_intercept(vcpu);
            kvm_lapic_sync_to_vapic(vcpu);
        }
    }

```

## 5\. 确保 MMU 已加载\(不成功则取消注入\)

```c
// 重新加载 MMU(如果之前 kvm_mmu_unload 卸载过、或影子页表未就绪)
    // 失败通常意味着内存分配失败,此时需要撤销上面已经"半提交"的事件注入
    r = kvm_mmu_reload(vcpu);
    if (unlikely(r)) {
        goto cancel_injection;
    }

```

## 6\. 进入临界区:关抢占 → 关中断 → 切换到 IN\_GUEST\_MODE

```c
preempt_disable();                                 // 关闭抢占,确保接下来不被内核调度出去

    // VMX/SVM 各自的"进入 Guest 前"准备:保存 host 状态、加载 guest 状态
    // (MSR、段寄存器、XSAVE 等)
    static_call(kvm_x86_prepare_guest_switch)(vcpu);

    /*
     * Disable IRQs before setting IN_GUEST_MODE.  Posted interrupt
     * IPI are then delayed after guest entry, which ensures that they
     * result in virtual interrupt delivery.
     */
    // 关中断必须在设置 IN_GUEST_MODE 之前,
    // 这样其他 CPU 通过 posted interrupt IPI 发送的中断,
    // 会被延迟到 Guest 进入后由硬件直接投递为虚拟中断
    local_irq_disable();
    vcpu->mode = IN_GUEST_MODE;                        // 标记 vCPU 状态:即将/正在 Guest 中运行

    // 释放 SRCU 读锁(此前长时间持有会阻塞 memslot 更新等 synchronize_srcu 调用者)
    srcu_read_unlock(&vcpu->kvm->srcu, vcpu->srcu_idx);

    /*
     * 1) We should set ->mode before checking ->requests.
     * 2) For APICv, ordering pairs with pi_test_and_set_on.
     * 3) Orders mode write vs page table reads while VCPU running.
     */
    // 内存屏障:
    //   (1) 保证 mode 写入对其他 CPU 可见后,再读 requests
    //   (2) 与 posted-interrupt 的 PID.ON 位测试形成配对
    //   (3) 保证 mode 写入 与 Guest 运行期间的页表读之间的顺序
    smp_mb__after_srcu_read_unlock();

    /*
     * This handles the case where a posted interrupt was
     * notified with kvm_vcpu_kick.  Assigned devices can
     * use the POSTED_INTR_VECTOR even if APICv is disabled.
     */
    // 把 Posted Interrupt Descriptor 中的中断同步到虚拟 IRR
    // (处理 kvm_vcpu_kick 触发的 posted intr;透传设备也可能用此向量)
    if (kvm_lapic_enabled(vcpu))
        static_call_cond(kvm_x86_sync_pir_to_irr)(vcpu);

```

## 7\. 二次检查:是否又有请求要求退出\(取消进入 Guest\)

```c
// 在关中断 + 设置 IN_GUEST_MODE + 屏障之后,再检查一次是否仍应该继续
    // (比如刚才被投递了新的 signal / request / kick)
    if (kvm_vcpu_exit_request(vcpu)) {
        vcpu->mode = OUTSIDE_GUEST_MODE;               // 撤销 IN_GUEST_MODE
        smp_wmb();                                     // 让状态改动对其他 CPU 可见
        local_irq_enable();                            // 恢复中断
        preempt_enable();                              // 恢复抢占
        vcpu->srcu_idx = srcu_read_lock(&vcpu->kvm->srcu);   // 重新拿 SRCU 读锁
        r = 1;                                         // 1 表示 vcpu_run 循环继续
        goto cancel_injection;                         // 需要撤销刚才的事件注入
    }

    // 需要立即 VM Exit:通常是 inject_pending_event 注入了事件后,想马上回来
    // 做法:请求一次 KVM_REQ_EVENT,并让底层设置 preemption timer 或类似机制
    if (req_immediate_exit) {
        kvm_make_request(KVM_REQ_EVENT, vcpu);
        static_call(kvm_x86_request_immediate_exit)(vcpu);
    }

```

## 8\. FPU 与调试寄存器准备

```c
// 确保 FPU 状态一致(WARN 检查),必要时切换 FPU
    fpregs_assert_state_consistent();
    if (test_thread_flag(TIF_NEED_FPU_LOAD))
        switch_fpu_return();                           // 加载 Guest 的 FPU 状态

    // 调试寄存器切换:
    //   - 若 Guest 使用了 DR0-DR3(switch_db_regs 有效),把 Guest 的调试地址装入硬件,
    //     并把 DR7 清零(防止在进入 Guest 前就命中断点)
    //   - 否则若 host 有硬件断点激活,清零 DR7 让 Guest 不受影响
    if (unlikely(vcpu->arch.switch_db_regs)) {
        set_debugreg(0, 7);
        set_debugreg(vcpu->arch.eff_db[0], 0);
        set_debugreg(vcpu->arch.eff_db[1], 1);
        set_debugreg(vcpu->arch.eff_db[2], 2);
        set_debugreg(vcpu->arch.eff_db[3], 3);
    } else if (unlikely(hw_breakpoint_active())) {
        set_debugreg(0, 7);
    }

```

## 9\. 核心:VMLAUNCH / VMRESUME 循环\(含 Fastpath 重入\)

```c
// 这里的 for 循环用于支持 "fastpath 重入":
    //   某些 VM Exit(如 WRMSR TSC_DEADLINE)可以在关中断/关抢占的状态下
    //   直接处理完并重新进入 Guest,避免走完整退出路径的开销。
    for (;;) {
        // === 真正的 VM Entry:进入 Guest 执行,直到发生 VM Exit ===
        // static_call 是 VMX 下的 vmx_vcpu_run 或 SVM 下的 svm_vcpu_run
**        exit_fastpath = static_call(kvm_x86_run)(vcpu);**

        // 大多数退出情况:跳出循环,走完整的退出处理
        if (likely(exit_fastpath != EXIT_FASTPATH_REENTER_GUEST))
            break;

        // Fastpath 已处理,需要重入 Guest 前:再同步一次 posted interrupt
        if (kvm_lapic_enabled(vcpu))
            static_call_cond(kvm_x86_sync_pir_to_irr)(vcpu);

        // 重入前也要再检查一次是否有紧急退出请求
        if (unlikely(kvm_vcpu_exit_request(vcpu))) {
            exit_fastpath = EXIT_FASTPATH_EXIT_HANDLED;
            break;
        }

        /* Note, VM-Exits that go down the "slow" path are accounted below. */
        // 走 fastpath 的退出在这里统计;走 slow path 的下面还会再统计一次
        ++vcpu->stat.exits;
    }

```

## 10\. VM Exit 后:调试寄存器回收

```c
/*
     * Do this here before restoring debug registers on the host.
     * A DR access vmexit can then read correct DR values and set
     * KVM_DEBUGREG_WONT_EXIT again.
     */
    // 如果 Guest 用过 DR 而且底层设置了 WONT_EXIT 优化(减少 DR VM Exit),
    // 必须在恢复 host DR 之前,先把硬件 DR 值同步回 vcpu 结构体,
    // 否则后续 DR VM Exit 会读到错误的值
    if (unlikely(vcpu->arch.switch_db_regs & KVM_DEBUGREG_WONT_EXIT)) {
        WARN_ON(vcpu->guest_debug & KVM_GUESTDBG_USE_HW_BP);    // 用户态调试与此优化互斥
        static_call(kvm_x86_sync_dirty_debug_regs)(vcpu);
        kvm_update_dr0123(vcpu);
        kvm_update_dr7(vcpu);
    }

    /*
     * If the guest has used debug registers, at least dr7 will be
     * disabled while returning to the host. Restore host breakpoints
     * if any were active.
     */
    // Guest 运行时 host 的硬件断点会被清掉,
    // 若 host 原本有活动断点,现在需要恢复
    if (hw_breakpoint_active())
        hw_breakpoint_restore();

```

## 11\. VM Exit 后:状态记账与初步处理

```c
vcpu->arch.last_vmentry_cpu = vcpu->cpu;           // 记录本次 VM Entry 时所在的物理 CPU
    vcpu->arch.last_guest_tsc = kvm_read_l1_tsc(vcpu, rdtsc());  // 记录退出瞬间 Guest 的 TSC

    vcpu->mode = OUTSIDE_GUEST_MODE;                   // 状态切回 Host 模式
    smp_wmb();                                         // 让其他 CPU 立刻看到状态变化

    // 关中断状态下预处理 VM Exit(比如 VMX 里 ACK 外部中断)
    // 这一步必须在开中断之前完成
    static_call(kvm_x86_handle_exit_irqoff)(vcpu);

    /*
     * Consume any pending interrupts. An instruction is required
     * after local_irq_enable() to fully unblock interrupts on
     * processors that implement an interrupt shadow.
     */
    // 这一段"开中断 → 增计数 → 关中断"是有讲究的:
    //   Intel CPU 在 STI 后有一个"interrupt shadow"(一条指令的窗口)才真正接受中断,
    //   所以必须在 enable 后至少执行一条指令(这里用 ++stat.exits 充数),
    //   才能确保之前挂起的外部中断/NMI 被处理器 dispatch
    kvm_before_interrupt(vcpu);                        // 通知 context tracking:即将处理中断
    local_irq_enable();
    ++vcpu->stat.exits;                                // 走 slow path 的 VM Exit 计数
    local_irq_disable();
    kvm_after_interrupt(vcpu);

```

## 12\. Guest 时间记账 与 LAPIC 定时器处理

```c
/*
     * Wait until after servicing IRQs to account guest time so that
     * any ticks that occurred while running the guest are properly
     * accounted to the guest.
     */
    // 记账 Guest 时间要放在处理完中断之后,
    // 这样刚才开中断处理的 tick 会算到 Guest 头上,而不是 Host
    vtime_account_guest_exit();

    // 若使用内核内 LAPIC,记录 lapic timer advance 的延迟统计
    // (KVM 会提前触发 lapic timer 以补偿 VM Exit 的开销)
    if (lapic_in_kernel(vcpu)) {
        s64 delta = vcpu->arch.apic->lapic_timer.advance_expire_delta;
        if (delta != S64_MIN) {
            trace_kvm_wait_lapic_expire(vcpu->vcpu_id, delta);
            vcpu->arch.apic->lapic_timer.advance_expire_delta = S64_MIN;
        }
    }

    local_irq_enable();                                // 正式恢复中断
    preempt_enable();                                  // 正式恢复抢占

    // 重新拿 SRCU 读锁(memslot、IRQ routing 等读操作需要)
    vcpu->srcu_idx = srcu_read_lock(&vcpu->kvm->srcu);

```

## 13\. 收尾:profiling / TSC catchup / vAPIC 同步 / 派发退出处理

```c
/*
     * Profile KVM exit RIPs:
     */
    // 若开启了 KVM_PROFILING,采样退出时的 Guest RIP 供 readprofile 使用
    if (unlikely(prof_on == KVM_PROFILING)) {
        unsigned long rip = kvm_rip_read(vcpu);
        profile_hit(KVM_PROFILING, (void *)rip);
    }

    // 若 CPU 需要"始终追赶 TSC"(host TSC 不稳定),
    // 请求下一轮循环再做一次 CLOCK_UPDATE
    if (unlikely(vcpu->arch.tsc_always_catchup))
        kvm_make_request(KVM_REQ_CLOCK_UPDATE, vcpu);

    // 若 Guest 通过 vapic_addr 使用了内存态 vAPIC,把 Guest 内存里的 vAPIC 同步回 KVM
    if (vcpu->arch.apic_attention)
        kvm_lapic_sync_from_vapic(vcpu);

    // === 派发到具体的 VM Exit handler(handle_ept_violation / handle_io / ...) ===
    // exit_fastpath 用于告知 handler:这次退出是否已经在 fastpath 处理过一部分
    r = static_call(kvm_x86_handle_exit)(vcpu, exit_fastpath);
    return r;                                          // 返回值决定 vcpu_run 的下一步动作

```

## 14\. 异常出口:cancel\_injection 与 out

```c
cancel_injection:
    // 之前 inject_pending_event 已经"半提交"了事件到 VMCS/VMCB,
    // 但由于我们决定不进入 Guest,需要撤销;否则下次会重复注入
    if (req_immediate_exit)
        kvm_make_request(KVM_REQ_EVENT, vcpu);         // 保留 EVENT 请求,下次再试注入
    static_call(kvm_x86_cancel_injection)(vcpu);        // 底层撤销 VMX/SVM 的注入字段
    if (unlikely(vcpu->arch.apic_attention))
        kvm_lapic_sync_from_vapic(vcpu);               // 与正常路径一致,同步 vAPIC

out:
    return r;
}

```

## 15\. 总结:关键控制流

**vCPU 进入 Guest 的完整生命周期**可归纳为三大阶段:

1. **Entry 准备**\(第 1\-8 节\):处理挂起请求 → 注入事件 → 加载 MMU → 关抢占/中断 → 切 IN\_GUEST\_MODE → 二次检查 → 准备 FPU/DR

2. **Entry 本体**\(第 9 节\):`static_call(kvm_x86_run)` 执行 VMLAUNCH/VMRESUME,循环支持 fastpath 重入

3. **Exit 处理**\(第 10\-13 节\):同步 DR → 记账 → 关中断处理 → 开中断消费 pending IRQ → Guest 时间记账 → 恢复抢占 → 拿回 SRCU → 派发 handle\_exit

**关键内存序保护**:`vcpu->mode` 的读写与 `vcpu->requests` 的检查之间必须有 `smp_mb` 屏障,否则会漏掉 `kvm_vcpu_kick` 发来的请求。

**关键性能优化**:fastpath 重入避免了 srcu 锁、preempt、irq、mode 切换等所有 heavy 操作,对 WRMSR\-heavy 场景\(尤其是虚拟化 TSC deadline 定时器\)极其重要。

---

# 附录:static\_call\(kvm\_x86\_run\) 机制深度解析

本节深入分析 `static_call(kvm_x86_run)` 这一调度机制——它是 KVM 从架构无关层\(x86\.c\)进入架构相关层\(VMX/SVM\)的关键分发点。内容涵盖 static\_call 原理、X\-macros 代码生成模式、调用点上下文、完整调用链及 fastpath 重入循环。

## A\.1 static\_call 机制概述

**static\_call** 是 Linux 5\.10 引入的内核特性,用于优化间接函数调用\(indirect call\)。在 Spectre v2 漏洞之后,内核默认使用 retpoline 来防止分支预测攻击,但 retpoline 会给每次间接调用带来额外开销。对于 KVM 这样在热路径上频繁调用的函数指针,**retpoline 的开销不可忽视**。

static\_call 的核心思想:**在编译时生成直接调用指令\(direct call\),在运行时通过指令修补\(instruction patching\)将其目标地址指向实际函数**。这样既避免了间接调用的 retpoline 开销,又保留了运行时多态的灵活性。

|特性|传统函数指针|static\_call|
|---|---|---|
|调用方式|间接调用 \(call \*%rax\)|直接调用 \(call \<addr\>\)|
|Spectre 防护|需要 retpoline,有性能损耗|无需 retpoline,直接调用天然安全|
|运行时切换|修改函数指针即可|通过 static\_call\_update 修补指令|
|性能|每次调用有 IBRS/retpoline 开销|几乎零开销,等同于直接函数调用|
|适用场景|通用多态分发|热路径上固定的少量目标函数|

## A\.2 KVM 中的 X\-macros 模式

KVM 使用 **X\-macros 模式**来同时生成 `kvm_x86_ops` 结构体定义和 `static_call` 声明。核心头文件是 `arch/x86/include/asm/kvm-x86-ops.h`,它只包含宏调用,不含任何 C 代码:

```c
KVM_X86_OP(run)
KVM_X86_OP(handle_exit)
KVM_X86_OP(handle_exit_irqoff)
KVM_X86_OP_NULL(sync_pir_to_irr)
KVM_X86_OP(prepare_guest_switch)
KVM_X86_OP(request_immediate_exit)
KVM_X86_OP(sync_dirty_debug_regs)
KVM_X86_OP(cancel_injection)
/* ... 共约 60+ 个操作 ... */
```

这个头文件被 **包含两次**,每次使用不同的宏定义,产生不同的代码:

### 第一次包含:定义 static\_call\(在 x86\.c 中\)

```c
struct kvm_x86_ops kvm_x86_ops __read_mostly;
EXPORT_SYMBOL_GPL(kvm_x86_ops);

/* 宏展开:为每个操作创建一个 static_call,默认目标为 NULL */
#define KVM_X86_OP(func)                                         \
    DEFINE_STATIC_CALL_NULL(kvm_x86_##func,                      \
            *(((struct kvm_x86_ops *)0)->func));
#define KVM_X86_OP_NULL KVM_X86_OP
#include &lt;asm/kvm-x86-ops.h&gt;
```

`KVM_X86_OP(run)` 展开后等价于:

```c
DEFINE_STATIC_CALL_NULL(kvm_x86_run,
        *(((struct kvm_x86_ops *)0)->run));
```

这会创建一个名为 `kvm_x86_run` 的 static\_call,其类型与 `kvm_x86_ops.run` 一致,初始目标为 NULL。此时调用它会导致内核 panic——必须在 `kvm_init()` 中先 `static_call_update` 绑定到实际函数。

### 第二次包含:绑定实际函数\(在 kvm\_init 中\)

```c
/* 宏展开:用 static_call_update 把每个 static_call 指向 kvm_x86_ops 中的实际函数 */
#define __KVM_X86_OP(func) \
    static_call_update(kvm_x86_##func, kvm_x86_ops.func);
#define KVM_X86_OP(func) \
    WARN_ON(!kvm_x86_ops.func); \
    __KVM_X86_OP(func)
#define KVM_X86_OP_OPTIONAL  __KVM_X86_OP
#define KVM_X86_OP_OPTIONAL_RET0(func) \
    static_call_update(kvm_x86_##func, (void *)kvm_x86_ops.func ? : \
            (void *)__static_call_return0);
#include &lt;asm/kvm-x86-ops.h&gt;
```

`KVM_X86_OP(run)` 在这里展开为:

```c
WARN_ON(!kvm_x86_ops.run);                    // 检查 VMX/SVM 是否提供了 run 函数
static_call_update(kvm_x86_run, kvm_x86_ops.run);  // 修补指令,指向 vmx_vcpu_run 或 svm_vcpu_run
```

**关键时序**:`static_call_update` 在 `kvm_init()` 中执行,即模块加载\(VMX 加载 kvm\_intel\.ko\)时完成。之后所有 `static_call(kvm_x86_run)` 调用都直接跳转到 `vmx_vcpu_run`——无需查表、无需 retpoline,等同于编译时已知的直接调用。

## A\.3 调用点上下文:vcpu\_enter\_guest 中的核心循环

`static_call(kvm_x86_run)` 的调用点位于 `vcpu_enter_guest()` 的核心区域。以下是调用点**前后的完整上下文**,附逐行中文注释:

### A\.3\.1 VM Entry 准备\(调用前\)

```c
/* ==================== 关抢占 + 切换 Host 上下文 ==================== */
preempt_disable();                              // 禁止抢占:进入 Guest 期间绝不能被调度走

/* 切换 Host 的段寄存器/FS/GS 等(VMX 下是 vmx_prepare_switch_to_guest)。
 * 这一步在 Host 侧完成,为后续 VMLAUNCH 做好 Host 上下文备份 */
static_call(kvm_x86_prepare_guest_switch)(vcpu);

/* ==================== 关中断 + 设置 IN_GUEST_MODE ==================== */
/* 关中断后,posted interrupt 的 IPI 会被延迟到 Guest entry 之后 delivery,
 * 这确保了 posted interrupt 能作为虚拟中断注入到 Guest 中 */
local_irq_disable();
vcpu->mode = IN_GUEST_MODE;                     // 标记"正在 Guest 中",其他 CPU 据此判断是否需要 kick

/* 释放 SRCU 锁:Guest 运行期间不需要持锁,减少临界区 */
srcu_read_unlock(&vcpu->kvm->srcu, vcpu->srcu_idx);

/* ==================== 关键内存屏障 ==================== */
/* 三重作用:
 * 1) 先设置 mode 再检查 requests,保证不会漏掉退出请求
 * 2) APICv 场景:先设置 mode 再检查 PID.ON(Posted Interrupt Descriptor)
 * 3) 对 mode 的写操作与 Guest 运行期间的页表读操作建立 happens-before 关系 */
smp_mb__after_srcu_read_unlock();

/* ==================== APICv: 同步 PIR 到 IRR ==================== */
/* 如果虚拟 APIC (APICv) 激活,把 Posted Interrupt Register 的待处理中断
 * 同步到 IRR(Interrupt Request Register),确保 Guest 能看到这些中断 */
if (kvm_lapic_enabled(vcpu) &amp;&amp; vcpu->arch.apicv_active)
    static_call(kvm_x86_sync_pir_to_irr)(vcpu);

/* ==================== 二次检查:是否需要取消进入 Guest ==================== */
/* 在设置 IN_GUEST_MODE 之后,再次检查是否有退出请求(如信号、KVM_REQ_* 等)。
 * 如果有,放弃本次 VM Entry,走 cancel_injection 路径 */
if (kvm_vcpu_exit_request(vcpu)) {
    vcpu->mode = OUTSIDE_GUEST_MODE;
    smp_wmb();
    local_irq_enable();
    preempt_enable();
    vcpu->srcu_idx = srcu_read_lock(&vcpu->kvm->srcu);
    r = 1;
    goto cancel_injection;
}

/* ==================== 立即退出请求 ==================== */
/* 某些场景(如需要尽快回到 Host 处理事件)会设置 req_immediate_exit,
 * 让 VMX 在 Guest 执行一条指令后就触发 VM Exit(通过 preemption timer 等) */
if (req_immediate_exit) {
    kvm_make_request(KVM_REQ_EVENT, vcpu);
    static_call(kvm_x86_request_immediate_exit)(vcpu);
}

/* ==================== FPU 与调试寄存器准备 ==================== */
fpregs_assert_state_consistent();
if (test_thread_flag(TIF_NEED_FPU_LOAD))
    switch_fpu_return();                        // 加载 Guest 的 FPU 状态到硬件

if (unlikely(vcpu->arch.switch_db_regs)) {
    set_debugreg(0, 7);                         // 清 DR7,防止在 VMLAUNCH 前命中断点
    set_debugreg(vcpu->arch.eff_db[0], 0);      // 加载 Guest 的 DR0-DR3
    set_debugreg(vcpu->arch.eff_db[1], 1);
    set_debugreg(vcpu->arch.eff_db[2], 2);
    set_debugreg(vcpu->arch.eff_db[3], 3);
} else if (unlikely(hw_breakpoint_active())) {
    set_debugreg(0, 7);                         // Host 有硬件断点时,清 DR7 让 Guest 不受影响
}
```

### A\.3\.2 核心调用:static\_call\(kvm\_x86\_run\) 与 Fastpath 重入循环

```c
/* ========================================================================
 * 核心:VMLAUNCH / VMRESUME 循环(含 Fastpath 重入)
 * ========================================================================
 * 这个 for(;;) 循环实现了 KVM 的 "fastpath re-entry" 优化:
 *
 * 某些 VM Exit(如 WRMSR 写 TSC_DEADLINE 定时器)可以在不退出到
 * vcpu_run() 外层循环的情况下,在关中断/关抢占的状态下直接处理完,
 * 然后立即重新进入 Guest。这避免了:
 *   - 释放/重获 SRCU 锁
 *   - 开/关抢占
 *   - 开/关中断
 *   - IN_GUEST_MODE / OUTSIDE_GUEST_MODE 切换
 *   - 完整的 handle_exit 路径
 * 对 WRMSR-heavy 的负载(如虚拟化 TSC deadline 定时器)性能提升显著。
 * ======================================================================== */
for (;;) {
    /* === 真正的 VM Entry ===
     * static_call(kvm_x86_run) 在 VMX 下展开为直接调用 vmx_vcpu_run(vcpu)
     * 该函数执行:
     *   1. 切换 Host→Guest 的 speculative execution 控制(IBRS 等)
     *   2. 加载 Guest 寄存器到 VMCS
     *   3. 调用 vmx_vcpu_enter_exit() → __vmx_vcpu_run() 执行 VMLAUNCH/VMRESUME
     *   4. Guest 运行直到 VM Exit
     *   5. 保存 Guest 寄存器,恢复 Host spec ctrl
     *   6. 检查 fastpath 退出条件(MSR write / preemption timer)
     * 返回值 exit_fastpath 有三种:
     *   EXIT_FASTPATH_NONE          — 普通退出,需要走完整 handle_exit
     *   EXIT_FASTPATH_REENTER_GUEST — fastpath 已处理,可直接重入 Guest
     *   EXIT_FASTPATH_EXIT_HANDLED  — fastpath 已处理且不需要重入 */
    exit_fastpath = static_call(kvm_x86_run)(vcpu);

    /* 大多数情况:不是 fastpath 重入,跳出循环走完整退出处理 */
    if (likely(exit_fastpath != EXIT_FASTPATH_REENTER_GUEST))
        break;

    /* === Fastpath 重入前的补充处理 ===
     * 既然要重新进入 Guest,必须再同步一次 posted interrupt:
     * 在上一次 Guest 运行期间,可能有新的 posted interrupt 到达 */
    if (kvm_lapic_enabled(vcpu))
        static_call_cond(kvm_x86_sync_pir_to_irr)(vcpu);

    /* 重入前必须再次检查退出请求:
     * 如果在 fastpath 处理期间收到了 kick 或信号,就不能再重入了 */
    if (unlikely(kvm_vcpu_exit_request(vcpu))) {
        exit_fastpath = EXIT_FASTPATH_EXIT_HANDLED;
        break;
    }

    /* 走 fastpath 的退出在这里统计退出次数;
     * 走 slow path 的退出在下面的代码中还会再统计一次 */
    ++vcpu->stat.exits;
}
```

### A\.3\.3 VM Exit 后处理\(调用后\)

```c
/* ==================== 调试寄存器回收 ==================== */
/* 若 Guest 使用了 DR0-DR3 且设置了 WONT_EXIT 优化(减少 DR 访问的 VM Exit),
 * 必须在恢复 Host DR 之前把硬件 DR 值同步回 vcpu 结构体 */
if (unlikely(vcpu->arch.switch_db_regs & KVM_DEBUGREG_WONT_EXIT)) {
    WARN_ON(vcpu->guest_debug & KVM_GUESTDBG_USE_HW_BP);
    static_call(kvm_x86_sync_dirty_debug_regs)(vcpu);
    kvm_update_dr0123(vcpu);
    kvm_update_dr7(vcpu);
}

if (hw_breakpoint_active())
    hw_breakpoint_restore();                    // 恢复 Host 的硬件断点

/* ==================== 状态记账 ==================== */
vcpu->arch.last_vmentry_cpu = vcpu->cpu;        // 记录本次 VM Entry 所在物理 CPU
vcpu->arch.last_guest_tsc = kvm_read_l1_tsc(vcpu, rdtsc());  // 记录退出瞬间 Guest TSC

vcpu->mode = OUTSIDE_GUEST_MODE;                // 状态切回 Host 模式
smp_wmb();                                      // 确保其他 CPU 立刻看到状态变化

/* 关中断状态下预处理 VM Exit(如 VMX 中 ACK 外部中断),
 * 必须在开中断之前完成 */
static_call(kvm_x86_handle_exit_irqoff)(vcpu);

/* ==================== 开中断消费 pending IRQ ==================== */
/* STI 后有一个 interrupt shadow(一条指令窗口)才真正接受中断,
 * 所以 ++stat.exits 充当那条"间隔指令" */
kvm_before_interrupt(vcpu);
local_irq_enable();
++vcpu->stat.exits;                             // slow path 的 VM Exit 计数
local_irq_disable();
kvm_after_interrupt(vcpu);

/* ==================== Guest 时间记账 ==================== */
vtime_account_guest_exit();

/* ==================== 恢复抢占 + 拿回 SRCU ==================== */
local_irq_enable();
preempt_enable();
vcpu->srcu_idx = srcu_read_lock(&vcpu->kvm->srcu);

/* ==================== 派发退出处理 ==================== */
/* 最终调用 vmx_handle_exit 或 svm_handle_exit,
 * 根据 exit_reason 分发到具体的 exit handler */
r = static_call(kvm_x86_handle_exit)(vcpu, exit_fastpath);
return r;
```

## A\.4 完整调用链

从用户态 QEMU 发起 ioctl 到最终执行 VMLAUNCH/VMRESUME 的完整调用链:

```c
/* 用户态 (QEMU) */
ioctl(vcpu_fd, KVM_RUN)
    │
    ▼
/* 内核态:通用 KVM 层 */
kvm_vcpu_ioctl()                          // virt/kvm/kvm-main.c
    └─→ kvm_arch_vcpu_ioctl_run()         // arch/x86/kvm/x86.c
            └─→ vcpu_run()                // 外层循环:处理信号/中断窗口等
                    └─→ vcpu_enter_guest() // 一次完整的 VM Entry→Exit 周期
                            │
                            │  /* === 关键分发点 === */
                            ├─→ static_call(kvm_x86_prepare_guest_switch)(vcpu)
                            ├─→ static_call(kvm_x86_sync_pir_to_irr)(vcpu)
                            │
                            │  /* === 核心调用 === */
                            └─→ static_call(kvm_x86_run)(vcpu)    ← 本节分析重点
                                    │
                                    ▼
                            /* VMX 实现层 (arch/x86/kvm/vmx/vmx.c) */
                            vmx_vcpu_run(vcpu)
                                    │
                                    ├─→ vmx_update_hv_timer()     // 设置 Preemption Timer
                                    ├─→ pt_guest_enter()          // Intel PT 上下文切换
                                    ├─→ vmx_guest_cpu_x86_spec_ctrl_enter()  // IBRS 等
                                    │
                                    │  /* === 实际 VMENTER === */
                                    └─→ vmx_vcpu_enter_exit(vcpu, __vmx_vcpu_run)
                                            │
                                            ▼
                                    /* 汇编层 (arch/x86/kvm/vmx/vmenter.S) */
                                    __vmx_vcpu_run()
                                            │
                                            ├─→ 保存 Host 寄存器
                                            ├─→ 加载 Guest 寄存器(GPRS)
                                            ├─→ vmwrite(GUEST_RSP)
                                            │
                                            ├─→ 2: vmresume  ←───┐
                                            │   3: jz 5f       │   │
                                            │   cmpb $0, ...   │   │
                                            │   jne 4f         │   │
                                            │   vmlaunch       │   │
                                            │   5:             │   │
                                            │                  │   │
                                            │   /* Guest 运行... */│
                                            │   /* 直到 VM Exit  */│
                                            │                  │   │
                                            ├─→ 保存 Guest GPRS     │
                                            ├─→ 恢复 Host 寄存器    │
                                            │                  │   │
                                            └─→ 返回 exit_fastpath │
                                                               │   │
                                    /* 回到 vmx_vcpu_run */     │   │
                                    ├─→ vmx_guest_cpu_x86_spec_ctrl_exit()
                                    ├─→ pt_guest_exit()
                                    ├─→ vmx_recover_nmi_blocking()
                                    ├─→ vmx_complete_interrupts()
                                    └─→ vmx_exit_handlers_fastpath()
                                            │
                                            ▼
                                    /* 回到 vcpu_enter_guest */
                                    /* 根据 exit_fastpath 决定:
                                     *   REENTER_GUEST → 循环重入
                                     *   其他 → 走 handle_exit */
```

## A\.5 Fastpath 重入循环的设计要点

|设计要点|说明|
|---|---|
|**为什么用 for\(;;\) 而非 while\(1\)**|语义相同,但 for\(;;\) 在内核代码中是惯用写法,部分编译器对 for\(;;\) 的无限循环优化更激进|
|**fastpath 能处理哪些退出**<br>|主要两类:\(1\) MSR write 退出\(如 Guest 写 TSC\_DEADLINE MSR 触发 LAPIC 定时器\);\(2\) VMX Preemption Timer 退出。这两类都是"处理完即可继续运行 Guest"的场景|
|**重入前为什么再同步 PIR**|Guest 运行期间\(哪怕只有几条指令\),其他 CPU 可能通过 posted interrupt 发送了虚拟中断,重入前必须同步到 IRR,否则 Guest 会错过中断|
|**重入前为什么再检查 exit\_request**|fastpath 处理期间\(虽然关中断\),但仍可能有 NMI 或其他 CPU 的 kick 设置了 vcpu\-\>mode 或 requests,此时不能再重入|
|**EXIT\_FASTPATH\_EXIT\_HANDLED 的含义**|fastpath 已完全处理了退出原因\(如已模拟了 MSR write\),不需要再走 handle\_exit,直接回到外层 vcpu\_run 循环|
|**退出计数\(exits\)的分拆**|fastpath 退出在循环内 \+\+stat\.exits;slow path 退出在循环外 \+\+stat\.exits。确保每个 VM Exit 只计数一次|

## A\.6 IN\_GUEST\_MODE 协议与内存屏障

**这是 vcpu\_enter\_guest 中最精妙的并发控制设计。**

`vcpu->mode` 有三个状态:

|状态|含义|其他 CPU 的行为|
|---|---|---|
|OUTSIDE\_GUEST\_MODE|vCPU 在 Host 侧,未进入 Guest|可以安全地修改 vCPU 状态,设置 requests|
|IN\_GUEST\_MODE|vCPU 正在 Guest 中运行|不能直接修改 vCPU 状态,必须通过 kvm\_vcpu\_kick 发 IPI|
|EXITING\_GUEST\_MODE|vCPU 正在从 Guest 退出\(过渡态\)|等待退出完成后操作|

**关键内存屏障:**

```c
/* vCPU 侧 (vcpu_enter_guest): */
local_irq_disable();
vcpu->mode = IN_GUEST_MODE;        /* 写 mode */
srcu_read_unlock(...);
smp_mb__after_srcu_read_unlock();  /* ★ 全屏障 ★ */
if (kvm_vcpu_exit_request(vcpu))   /* 读 requests */
    goto cancel;

/* 其他 CPU 侧 (kvm_vcpu_kick): */
kvm_make_request(KVM_REQ_*, vcpu); /* 写 requests */
smp_mb__after_atomic();            /* ★ 全屏障 ★ */
if (vcpu->mode == IN_GUEST_MODE)   /* 读 mode */
    send_ipi(vcpu);                /* 发 IPI 让 Guest 退出 */
```

如果没有这两个屏障,以下竞态会发生:

1. vCPU 设置 IN\_GUEST\_MODE,但还没读取 requests

2. 其他 CPU 设置 request,但还没读取 mode\(看到旧值 OUTSIDE\_GUEST\_MODE\)

3. 其他 CPU 认为不需要发 IPI\(vCPU 不在 Guest 中\)

4. vCPU 读取 requests\(为空,因为写操作还没可见\)

5. vCPU 进入 Guest,但 request 永远不会被处理

有了 `smp_mb` 屏障,步骤 1\-2 和步骤 3\-4 之间建立了 happens\-before 关系,确保:如果 vCPU 在设置 mode 后检查 requests 为空,那么其他 CPU 的 kick 一定能读到新的 mode 值并发 IPI。

## A\.7 static\_call 与函数指针的性能对比

```c
/* 传统函数指针 (被 retpoline 保护) */
call __x86_indirect_thunk_rax    // 跳到 retpoline stub
    /* retpoline 内部:
     *   call L1
     * L2: pause
     *   lfence
     *   jmp L2
     * L1: mov [rsp], target
     *   ret
     */
/* 总计: ~20+ cycles 的额外开销 */

/* static_call (直接调用,运行时修补) */
call vmx_vcpu_run                // 编译时生成占位,运行时 patch 为直接 call
/* 总计: ~5 cycles (等同于普通函数调用) */
```

对于 KVM 的热路径,`static_call(kvm_x86_run)` 在每次 VM Entry/Exit 中都会被调用。在高密度虚拟化场景\(如 1:1 vCPU:pCPU 绑定,Guest 频繁 VM Exit\),static\_call 相比函数指针可节省 **约 3\-5% 的 VM Exit 开销**。

---

## A\.8 总结:static\_call\(kvm\_x86\_run\) 的核心设计

**static\_call\(kvm\_x86\_run\) 是 KVM x86 从架构无关层进入架构相关层的唯一分发入口**,其核心设计可归纳为以下几点:

1. **static\_call 机制**:通过编译时生成直接调用 \+ 运行时指令修补,避免了 retpoline 开销,同时保留运行时多态\(VMX/SVM 切换\)

2. **X\-macros 模式**:kvm\-x86\-ops\.h 被包含两次,分别生成 static\_call 定义和 static\_call\_update 绑定,一处声明、两处展开、零冗余

3. **调用点设计**:在 vcpu\_enter\_guest 的 for\(;;\) 循环中调用,支持 fastpath 重入——某些 VM Exit 可在关中断/关抢占状态下直接处理并重入 Guest

4. **IN\_GUEST\_MODE 协议**:通过 vcpu\-\>mode 状态 \+ smp\_mb 屏障,确保 vCPU 与其他 CPU 之间的正确通信——其他 CPU 据此决定是直接修改 vCPU 状态还是发 IPI

5. **完整调用链**:ioctl → kvm\_arch\_vcpu\_ioctl\_run → vcpu\_run → vcpu\_enter\_guest → static\_call\(kvm\_x86\_run\) → vmx\_vcpu\_run → vmx\_vcpu\_enter\_exit → \_\_vmx\_vcpu\_run → VMLAUNCH/VMRESUME

6. **fastpath 优化**:对 WRMSR\(TSC\_DEADLINE\)和 Preemption Timer 退出,避免完整的退出处理路径\(srcu/preempt/irq/mode 切换\),显著提升虚拟化定时器密集型负载的性能

7. **安全与性能兼得**:在 Spectre v2 防护下,static\_call 是唯一能同时满足安全\(无间接调用\)和高性能\(无 retpoline\)的方案

> （注：部分内容可能由 AI 生成）
