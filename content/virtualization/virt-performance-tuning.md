---
author: Yori Fang
title: Performance Tuning On Virtualization Platform
date: 2020-04-25 23:00
status: draft
slug: virt-perf-tuning
tags: perf
---

虚拟化性能调优

虚拟化资源调度影响：
HostOS和GuestOS的双重调度，不同的调度域（跨片调度、跨die调度、SMT调度）、vCPU复用、Cache资源竞争、Mem带宽竞争、芯片指令流水

* mwait
  
* async pagefault
  
* smart polling
  
* pv spinlock

* pv time
  
[https://developer.arm.com/docs/den0057/a](https://developer.arm.com/docs/den0057/a)