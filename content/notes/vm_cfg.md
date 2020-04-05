Title:  VM Configuraton
Date: 2020-2-20 23:00
Modified: 2020-2-20 23:00
Tags: VM, Libvirt, XML
Slug: vm-cfg
Status: draft
Authors: Yori Fang
Summary: VM Configuration Stuff

## 虚拟机配置清单



#### 1.配置UEFI启动

配置虚拟机BIOS/UEFI的XML元素为'loader'，可以配置2个属性，一个是属性是readonly其值一般配置为yes，
另一个属性type，其值只能是'rom'或者'pflash'。
对于UEFI而言type配置成'pflash'，这样每个UEFI虚拟机都可以再额外配置自己的启动参数（一般利用NVRAM来完成）。
对于seabios而言配置成'rom'，表示从bios-256k.bin被映射到ROM空间。

例如我们可以配置UEFI启动为：

```
  <os>
    <type arch='x86the _64' machine='pc-i44fx-4.0'>hvm<type>
    <loader readonly='yes' type='pflash'>/usr/share/edk2/ovmf/OVMF_CODE.fd</loader>
    <nvram>/usr/share/edk2/ovmf/OVMF_VARS.fd</nvram>
  </os>
```

其中，OVMF_CODE.fd是UEFI的二进制启动文件，OVMF_VARS.fd是用来保存uefi启动参数的文件。
值得注意的是，尽管UEFI启动的是也可以配置type='rom'，但这样以来我们无法为每个虚拟机指定uefi参数文件。

当然也可以用cmdline来拉起一个UEFI虚拟机：
```
qemu-kvm \
  -m 2048 \
  --machine pc-q35-4.0 \
  -drive if=pflash,format=raw,readonly,file=./OVMF_CODE.fd \
  -drive if=pflash,format=raw,file=./OVMF_VARS.fd \
  -drive file=/home/this-vim.img,format=raw,index=0,media=disk \
  -boot menu=on
```
#### 2.为虚拟机配置网卡

第一种是ovs网桥上挂载的网卡，配置如下：
```
<interface type='bridge'>
  <mac address='52:24:01:d9:dc:56'/>
  <source bridge='br0'/>
  <virtualport type='openvswitch'>
  </virtualport>
  <target dev='vnet2'/>
  <model type='virtio'/>
  <alias name='net0'/>
</interface>
```