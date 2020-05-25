---
author: Yori Fang
title: Imporve CPU Performance Using Haltpolling
date: 2020-04-11 23:00
status: draft
slug: halt-polling
tags: haltpolling, haltpoll, smart polling
---

我们都知道，每一台运行的服务器除了要投入一笔硬件和软件成本之外，还需要覆盖供电和散热带来的长期成本开销。
为了提升能源利用率，做到节能环保和降低运营成本，就需要对服务器进行电源管理。
当服务器的CPU处于空闲状态的时候，操作系统会让CPU进入Idle状态关闭，让CPU暂时停止执行指令或者关闭
部分电路单元来达到节省电源的目的。

然而在虚拟化场景下，vCPU进入Idle状态后一般会导致vCPU退出Guest模式，
如果立刻发生了状态变更又会再次进入运行模式，模式的切换会引入额外的性能开销。
在追求vCPU调度极致性能的场景下，要尽量减少vCPU在Guest模式陷出的切换带来的开销。
本文意在分析一下虚拟化场景下的halt-polling机制。

## CPU Idle Framework

在Linux系统上，当所有进程都不再处于运行状态的时候，称作cpuidle[1]。
Kernel采用一种比较简单的方法：在init进程完成初始化之后就转变为idle进程。
在arm64上执行WFI（Wait For Interrupt）/WFE（Wait For Event）指令可以让cpu进入idle状态，
而在x86平台上执行HLT(halt)指令可让cpu进入idle状态。

为了让不同体系结构的CPU支持cpuidle机制，内核实现了一套cpuidle驱动框架[2]。
目的是用同一套框架适配多种体系结构，把公共代码解耦出来。
cpuidle驱动框架的设计思路为从CPU的**"退出时延"**和**"idle功耗"**两个方面进行考虑，
设置了多种idle级别[2]。关于cpuidle framework的设计分析可以参考蜗窝科技的文章[1]。

## Halt Polling

## Smart Polling

## Reference

* 1.[Linux cpuidle framework](http://www.wowotech.net/tag/cpuidle)
* 1.[CPU Idle Time Management](https://www.kernel.org/doc/html/latest/driver-api/pm/cpuidle.html)


