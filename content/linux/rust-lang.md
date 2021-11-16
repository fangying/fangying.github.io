Title:  The Rust Programming Language
Date: 2019-5-27 23:00
Modified: 2019-5-27 23:00
Tags: Rust
Category: Programe Language
Slug: rust-lang
Status: published
Authors: Yori Fang
Summary: rust

### 1. Rust 编程语言

Rust是一个聚焦安全性的多范式的系统编程语言，尤其是并发安全。
Rust的语法类似c++但在设计的时候考虑了更多的内存安全并且保持了高性能。
Rust语言的精髓深藏在各种语言规则中，这里记录一些Rust语言学习笔记，供自己体会和学习。

### 2.Rust 语言教程

* https://doc.rust-lang.org/book/
* https://doc.rust-lang.org/std/index.html#the-rust-standard-library
* [Rust编程之道 张汉东 电子工业出版社](https://item.jd.com/40634014085.html)

### 3.Rust 语言特性

所有权准则：

* Rust中的每个值都有一个与之对应的变量叫做它的所有权；
* 同一时刻只能有一个所有权；
* 当所有权走出作用域的时候，值就会被自动丢弃。


可变借用:

* 在特定的作用域内，任何数据只能有且仅有1个可变引用。

借用准则：

* 在任何时候对于一个变量，你只能有一个可变的引用 或者 任意数量的不可变引用。
* 引用都必须是有效的。
* 当数据被不可变地借用时，它还会冻结（freeze）。已冻结的数据无法通过原始 对象来修改，直到对这些数据的所有引用离开作用域为止。

引用和借用的区别：

* 引用, 简单而言就是指向一个值所在内存的指针, 这个跟 c++ 里是一致的。如果一个引用作为函数的参数, 它又称为对一个值的借用。

[参考](https://blog.biofan.org/2019/08/rust-references-and-borrowing/)

生命周期省略规则：

* 每个引用类型的参数都有自己的生命周期参数；
* 如果只有一个生命周期输入参数，那么所有的输出参数都使用这个入参的生命周期；
* 如果有多个参数的生命周期，那么只能有一个参数是 *&self* 或者 *&mut self* 类型，因为这是一个方法。

说明：由于Rust会自动释放作用域内的变量，所以就需要用生命周期来告诉编译器去检查所有的借用都是有效的。

闭包（Lambda 表达式/匿名函数）准则：

* 使用 || 而不是 ()来包围输入变量；
* 对于单个表达式的执行体， {} 不是必须要求的；
* 能够使用外部环境中的变量；
* 可以自动推断输入和返回值的类型。

匿名函数默认会实现3个特定Trait类型的其中一个：FnOnce/FnMut/Fn
默认情况下它们是交给rust编译器去推理的, 大致的推理原则是:

* FnOnce: 当指定这个Trait时, 匿名函数内访问的外部变量必须拥有所有权.
* FnMut: 当指定这个Trait时, 匿名函数可以改变外部变量的值.
* Fn: 当指定这个Trait时, 匿名函数只能读取(borrow value immutably)变量值.

注意：若使用闭包作为函数参数，由于这个结构体的类型未知，任何的用法都要求是泛型的

Rust核心库：

Rust核心库（Rust Core Lib）是标准库（Rust Standard Lib）的基础，不依赖于操作系统，没有堆内存分配。
可以用来构建OS和物联网等嵌入式应用程序。

* 基础的trait: Copy，Debug，Display，Option等
* 基本的原始类型：bool，char，i8/u8，i16/u16，i32/u32，i64/u64，isize/uszie，f32/f64，str，array，slice，tuple，pointer
* 常用的功能数据类型，入String，Vec，HashMap，Rc，Arc，Box等
* 常用的宏定义：println!，assert！，panic！，vec！等

Rust结构体：

* 具名结构体（Named-Field Struct）
* 元组结构体（Tuple-Like Struct）
* 单元结构体（Unit-Like Struct）

Trait类型：

* trait是Rust唯一的接口抽象方式
* 可以静态生成，也可以动态调用
* 可以当做标记类型拥有某些特定行为的“标签”来使用

extern crate和use的区别：

Rust2018之后不需要显式extern引入crate，编译器会自动引入。
只需要在Cargo.toml中的Dependency加入crate name，然后在源码中use即可。
这里是Rust关于废弃extern crate的声明：
[https://doc.rust-lang.org/nightly/edition-guide/rust-2018/module-system/path-clarity.html](https://doc.rust-lang.org/nightly/edition-guide/rust-2018/module-system/path-clarity.html)

Rust Debug姿势：

rust-gdb使用方法：
[https://bitshifter.github.io/rr+rust/index.html#1](https://bitshifter.github.io/rr+rust/index.html#1)

函数入参的生命周期：

* 任何引用都必须拥有标注好的生命周期。
* 任何被返回的引用都必须有和某个输入量相同的生命周期或是静态类型（static）。

结构体中标注的生命周期和函数中一致。

语法糖：

* map如果有值Some(T)会执行f，反之直接返回None。
* unwrap_or提供了一个默认值default，当值为None时返回default。
* 看起来and_then和map差不多，不过map只是把值为Some(t)重新映射了一遍，and_then则会返回另一个Option。

这些个语法糖经常用在错误处理的方面。
[参考](https://wiki.jikexueyuan.com/project/rust-primer/error-handling/option-result.html)


关于MutexGard类型：

* Arc<Mutex>类型执行了lock.unwrap得到MutexGuard类型，需要解引用或者借用才能取出包装类型；
* 例如: let mytype: &MyType = &x.lock().unwrap() //借用
* 或者: let mytype = *x.lock().unwrap() //解引用

关于Rust函数入参：mut a:&T 和a:&mut T的区别

| Rust           | C/C++            | 含义                | 解释                 |
| :------------- | :----------------| :----------------- | :---------------------- |
| a:&T          | const T* const a | 都不能修改   | 不可变引用的不可变绑定 |
| mut a: &T     | const T* a       | 不能修改a指向内容 | 不可变引用的可变绑定 |
| a: &mut T     | T * const a      | 不能修改a     | 可变引用的不可变绑定 |
| mut a: &mut T | T* a             | 都可以修改   | 可变引用的可变绑定 |

参考: [https://www.zhihu.com/search?type=content&q=%26mut%20*mut](https://www.zhihu.com/search?type=content&q=%26mut%20*mut)

零成本抽象：

Rust中零成本抽象是基于范型和Trait来实现的。

关于智能指针：

智能指针是指实现了Deref Trait或者Drop Trait语义的类型。
智能指针的**智能**体现在：（1）可以自动解引用；（2）可以自动管理内存，安全无忧；


### Reference

1. [Rust Programming Language (wikipedia)](https://en.wikipedia.org/wiki/Rust_(programming_language))
1. [Rust closure FnOne/FnMut/Fn](https://www.jianshu.com/p/f38388e0e956)
1. [理解Rust生命周期](https://lotabout.me/2016/rust-lifetime/)
