---
author: Yori Fang
title: Understanding C11/C++11 Memory Model (draft)
date: 2020-05-15 23:00
status: draft
slug: memory-model
tags: memory model
---

现代计算机体系结构上，CPU执行指令的速度远远大于CPU访问内存的速度，于是引入Cache机制来加速内存访问速度。
除了Cache以外，分支预测和指令预取也在很大程度上提升了CPU的执行速度。
随着SMP的出现，多线程编程模型被广泛应用，在多线程模型下对共享变量的访问变成了一个复杂的问题。
于是我们有必要了解一下内存模型，这是多处理器架构下并发编程里面的一个基础概念。

## 1. 什么是内存模型？

到底什么是内存模型呢？看到有两种不同的观点：

* A：内存模型是从来描述编程语言在支持多线程编程中对共享内存访问的顺序[1]。
* B：内存模型的本质是指在单线程情况下CPU指令在多大程度上发生指令重排(reorder)[2]。

实际上A，B两种说法都是正确的，只不过是从不同的角度去说明memory model的概念。
个人认为，内存模型表达为“内存顺序模型”可能更加贴切一点。

一个良好的memory model定义包含3个方面：

* Atomic Operations
* Partial order of operations
* Visable effects of operations

我们这里所说的内存模型和CPU的体系结构、编译器实现和编程语言规范3个层面都有关系。

首先，不同的CPU体系结构内存顺序模型是不一样的，但大致分为两种：

| Architecture | Memory Model      |
| :----------- | :---------------- |
| x86_64       | Total Store Order |
| Sparc        | Total Store Order |
| ARMv8        | Weakly Ordered    |
| PowerPC      | Weakly Ordered    |
| MIPS         | Weakly Ordered    |
|              |

x86_64和Sparc是强顺序模型TSO，这是一种接近程序顺序的顺序模型。
谓Total，就是说，内存（在写操作上）是有一个全局的顺序的（所有人看到的一样的顺序），
就好像在内存上的每个Store动作必须有一个排队，一个弄完才轮到另一个，这个顺序和你的程序顺序直接相关。
所有的行为组合只会是所有CPU内存程序顺序的交织，不会发生和程序顺序不一致的地方[6]。
TSO模型有利于多线程程序的编写，对程序员更加友好，但对芯片实现者不友好。
CPU为了TSO的承诺，可能会牺牲一些并发上的执行效率。

弱内存模型（简称WMO，Weak Memory Ordering），是把是否要求强制顺序这个要求直接交给程序员的方法。
换句话说，CPU不去保证这个顺序模型（除非他们在一个CPU上就有依赖），
程序员要主动插入内存屏障指令来强化这个“可见性”。
也没有一个全局的对所有CPU都是一样的Total Order[4]。
ARMv8，PowerPC和MIPS等体系结构都是弱内存模型。
每种弱内存模型的体系架构都有自己的内存屏障指令，语义也不完全相同。
弱内存模型下，硬件实现起来相对简单，处理器执行的效率也高，
只要没有遇到显式的屏障指令，CPU可以对局部指令进行reorder以提高执行效率。

对于多线程程序开发来说，对并发的数据访问我们一般到做同步操作，
可以使用mutex，semaphore，conditional等重量级方案对共享数据进行保护。
但为了实现更高的并发，需要使用内存共享变量做通信（Message Passing），
这就对程序员的要求很高了，时时刻刻必须很清楚自己在做什么，
否则程序的行为会让人很是迷惑。
值得一提的是，并发虽好，但在设计程序的时候尽量不要和别人共享数据，
能简单粗暴就不要搞太多投机取巧！要实现lock-free无锁编程真的有点难。

其次，不同的编程语言对内存模型都有自己的规范，例如：
C/C++和Java等不同的编程语言都有定义内存模型相关规范。

2011年发布的C11/C++11 ISO Standard为我们带来了memory order的支持，
引用C++11里的一段描述：
```
The memory model means that C++ code now has a standardized
library to call regardless of who made the compiler and on
what platform it's running. There's a standard way to control
how different threads talk to the processor's memory.[7]
```
C++11引入memory order的意义在于我们现在有了一个与运行平台无关和编译器无关的标准库，
让我们可以在high level languange层面实现对多处理器对共享内存的交互式控制。
我们的多线程终于可以跨平台啦！我们可以借助内存模型写出更好更安全的并发代码。
真棒，简直不要太优秀~

C11/C++11使用atomic来描述memory model，而atomic操作可以用load()和release()语义来描述。
一个简单的atomic变量赋值可描述为：
```
 atomic_var1.store (atomic_var2.load()); // atomic variables
     vs
 var1 = var2;                            // regular variables
```
下面我们来一起学习一下内存模型吧。

## 2. C11/C++11内存模型

为了描述内存模型，C/C++11标准中提供了6种memory order[x]:
```c++
enum memory_order {
    memory_order_relaxed,
    memory_order_consume,
    memory_order_acquire,
    memory_order_release,
    memory_order_acq_rel,
    memory_order_seq_cst
};
```
每种memory order的规则可以简要描述为：

| 枚举值               | 定义规则                                                                 |
| :------------------- | :----------------------------------------------------------------------- |
| memory_order_relaxed | 不对执行顺序做任何保证                                                   |
| memory_order_consume | 本线程中，所有后续的有关本原子类型的操作，必须在本条原子操作完成之后执行 |
| memory_order_acquire | 本线程中，所有后续的读操作必须在本条原子操作完成后执行                   |
| memory_order_release | 本线程中，所有之前的写操作完成后才能执行本条原子操作                     |
| memory_order_acq_rel | 同时包含memory_order_acquire和memory_order_release标记                   |
| memory_order_seq_cst | 全部存取都按顺序执行                                                     |
|                      |

下面我们来举例一一说明，扒开内存模型的神秘面纱。

### 2.1 memory order releaxed

`relaxed`表示一种最为宽松的内存操作约定，Relaxed ordering 仅仅保证load()和store()是原子操作，
除此之外，不提供任何跨线程的同步[5]。

```
                   std::atomic<int> x = 0;     // global variable
                   std::atomic<int> y = 0;     // global variable
		  
Thread-1:                                  Thread-2:
r1 = y.load(memory_order_relaxed); // A    r2 = x.load(memory_order_relaxed); // C
x.store(r1, memory_order_relaxed); // B    y.store(42, memory_order_relaxed); // D
```
上面的多线程模型执行的时候，可能出现r2 == r1 == 42。
要理解这一点并不难，因为CPU在执行的时候允许局部指令重排reorder，D可能在C前执行。
如果程序的执行顺序是 D -> A -> B -> C，那么就会出现r1 == r2 == 42。

如果某个操作只要求是原子操作，除此之外，不需要其它同步的保障，那么就可以使用 relaxed ordering。
程序计数器是一种典型的应用场景：
```c
#include <cassert>
#include <vector>
#include <iostream>
#include <thread>
#include <atomic>

std::atomic<int> cnt = {0};
void f()
{
    for (int n = 0; n < 1000; ++n) {
        cnt.fetch_add(1, std::memory_order_relaxed);
    }
}
int main()
{
    std::vector<std::thread> v;
    for (int n = 0; n < 10; ++n) {
        v.emplace_back(f);
    }
    for (auto& t : v) {
        t.join();
    }
    assert(cnt == 10000);    // never failed
    return 0;
}
```
`cnt`是共享的全局变量，多个线程并发地对`cnt`执行RMW原子操作。
这里只保证`cnt`的原子性，其他有依赖`cnt`的地方不保证任何的同步。

### 2.2 memory order consume

consume要搭配release一起使用。很多时候，线程间只想针对有依赖关系的操作进行同步，
除此之外线程中其他操作顺序如何不关系，这时候就可以用`consume`来完成这个操作。
例如：
```c
b = *a;
c = *b
```
第二行的变量c依赖于第一行的执行结果，因此这两行代码是"Carries dependency"关系。
`memory_order_consume`就是针对有明确依赖关系的语句来限定其执行顺序的一种内存顺序，
显然`consume order`要比`releaxed order`要Strong一点。

```c++
#include <thread>
#include <atomic>
#include <cassert>
#include <string>

std::atomic<std::string*> ptr;
int data;

void producer()
{
    std::string* p  = new std::string("Hello");
    data = 42;
    ptr.store(p, std::memory_order_release);
}

void consumer()
{
    std::string* p2;
    while (!(p2 = ptr.load(std::memory_order_consume)))
        ;
    assert(*p2 == "Hello");  // never fires: *p2 carries dependency from ptr
    assert(data == 42);      // may or may not fire: data does not carry dependency from ptr
}

int main()
{
    std::thread t1(producer);
    std::thread t2(consumer);
    t1.join();
    t2.join();
}
```
assert(*p2 == "Hello")永远不会失败，但assert(data == 42)可能会。
原因是p2和ptr直接有依赖关系，但data和ptr没有直接依赖关系，
尽管线程1中data赋值在ptr.store()之前，线程2看到的data的值是不确定的。

### 2.3 memory order acquire

`acquire`和`release`必须放到一起使用，属于一个package deal。
`release`和`acquire`构成了synchronize-with关系，也就是同步关系。
在这个关系下：线程A中所有发生在release x之前的值的写操作，
对线程B的acquire x之后的任何操作都可见。
```c++
#include <thread>
#include <atomic>
#include <cassert>
#include <string>
#include <iostream>

std::atomic<bool> ready{ false };
int data = 0;
std::atomic<int> var = {0};

void sender()
{
    data = 42;                                              // A
    var.store(100, std::memory_order_relaxed);              // B
    ready.store(true, std::memory_order_release);           // C
}
void receiver()
{
    while (!ready.load(std::memory_order_acquire))          // D
        ;
    assert(data == 42);  // never failed                    // E
    assert(var == 100);  // never failed                    // F
}

int main()
{
    std::thread t1(sender);
    std::thread t2(receiver);
    t1.join();
    t2.join();
}
```
上面的例子中，
sender线程中`data = 42`是sequence before原子变量ready的，
sender和receiver在B和C处发生了同步，
线程sender中B之前的所有读写对线程receiver都是可见的。



### 2.4 memory order release
### 2.5 memory order acq_rel
### 2.6 memory order seq_cst


## 3. Reference

* 1.[C++11 内存模型](https://wizardforcel.gitbooks.io/cpp-11-faq/26.html)
* 1.[高并发编程](https://zhuanlan.zhihu.com/p/48161056)
* 1.[Common Compiler Optimisations are Invalid](http://plv.mpi-sws.org/c11comp/popl15.pdf)
* 1.[CppCon 2015: Michael Wong “C++11/14/17 atomics and memory model..."](https://www.youtube.com/watch?v=DS2m7T6NKZQ)
* 1.[理解 C++ 的 Memory Order](http://senlinzhan.github.io/2017/12/04/cpp-memory-order/)
* 1.[理解弱内存顺序模型](https://zhuanlan.zhihu.com/p/94421667)
* 1.[当我们在谈论 memory order 的时候，我们在谈论什么](https://segmentfault.com/p/1210000011132386/read)
* 1.[https://en.cppreference.com/w/cpp/atomic/memory_order](https://en.cppreference.com/w/cpp/atomic/memory_order)