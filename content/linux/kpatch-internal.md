Title:  kpatch internal
Date: 2020-6-23 23:00
Modified: 2020-6-23 23:00
Tags: kpatch
Slug: kpatch-internal
Status: draft
Authors: Yori Fang
Summary: kpatch internal


References:


目标文件的文件类型为ELF格式，本质是一个**可重定位文件(Relocatable File)**，
ELF文件分为4中类型：Relocatable file，Executable File， Shared object和Core dump file。

连接器对目标文件进行链接(link)，生成可执行程序的时候一般包含两个步骤：

* 地址空间分配： 扫描输入目标文件，获取各段长度，属性和位置信息，并将所有输入目标文件中的符号定义（Symbol Defination）和
  符号引用（Symbol Reference）收集起来，统一放到全局符号表中。
* 符号解析或重定位：读取输入段中的数据重定位信息并进行符号解析与重定位，调整代码地址。

GOT（global offset table）

什么是重定向？为什么我们需要重定向？

GOT 全局偏移表，连接器在执行链接的时候实际上要填充部分，保存了所有外部符号的地址信息。

## 

1. https://github.com/dynup/kpatch