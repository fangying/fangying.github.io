Title:  DPDK and Vhost User
Date: 2020-3-23 23:00
Modified: 2020-3-23 23:00
Tags: DPDK,Vhost User
Slug: dpdk-and-vhost-user
Status: draft
Authors: Yori Fang
Summary: DPDK and Vhost User

## DPDK 简介
为啥要有DPDK？DPDK解决了什么问题？有哪些特点？

## DPDK关键技术

## Vhost User


```
+-------------+                     +-------------+
|     VM1     |                     |     VM2     |
|             |                     |             |
|    vhost    |    shared memory    |             |
|   device    | +-----------------> |             |
|   backend   |                     |             |
|             |                     | virtio-net  |
+-------------+                     +-------------+
|             |                     |             |
|  virtio-    |  vhost-user socket  |             |
| vhost-user  | <-----------------> | vhost-user  |
|    QEMU     |                     |    QEMU     |
+-------------+                     +-------------+
```
https://wiki.qemu.org/Features/VirtioVhostUser

## 关键代码分析

Step1： 调用rte_eal_init初始化包括CPU、Memory、Log、Pci等，根据参数创建转发线程，并wait状态；
Step2： 添加网卡设备，进行网卡设置和启动；
Step3： 运行转发线程，rte_eal_remote_launch，转发逻辑是由自己实现，通常是收发包和包处理过程。

## 参考文献
