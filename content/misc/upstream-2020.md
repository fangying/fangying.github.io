---
author: Yori Fang
title: OpenWrt Customization
date:  2021-04-01 7:30:47 +0100
status: draft
slug: openwrt-customization
---

## 定制一个适合自己的OpenWrt固件版本

尽管有很多无私奉献的小伙伴编译和定制了各种各样的OpenWrt固件，但有时候我们还是希望自己能够定制属于自己的专属固件。
所以这里简单记录一下，如何定制一个属于自己的OpenWrt固件用在自己的路由器系统上。

## 选定OpenWrt基线版本

这里选择LEDE的开源仓库为制作模板，站在大神的肩膀上可以省去一些不必要的麻烦，当然你也可以用OpenWrt官方社区的源。

```
git clone https://github.com/coolsnowwolf/lede.git
```
我这里是在家里的台式机上创建了一个ubuntu的容器，在容器中对固件进行编译的。

## 参考文献
