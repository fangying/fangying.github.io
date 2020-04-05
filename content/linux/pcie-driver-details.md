Title: PCIe Overview
Date: 2018-12-14 23:00
Modified: 2018-12-14 23:00
Tags: linux
Slug: pcie
Status: draft
Authors: Yori Fang
Summary: PCIe Overview


PCIe是Intel为首的厂家提出的一种高速互联的总线协议，是整个X86体系结构外设标准接口协议。
虚拟化中设备模拟的时候必不可少的需要对PCIe设备进行模拟，这里整理一下关于PCI/PCIe的一些基本知识方面后面查阅。


```
pcie_init_slot => 
        pciehp_ist (events=PDC, state=0)=> if (!test_and_set_bit(0, &slot_being_removed_rescanned))     
                => pciehp_handle_presence_or_link_change
                        print slot link up
                        => ctrl->request_result = pciehp_enable_slot(slot);
                                ret = __pciehp_enable_slot  failed to check link status    ret = -1 所以 state = 0
                                                => pciehp_check_link_status
        


pciehp_probe
                => pcie_init => pcie_init_slot => pciehp_queue_pushbutton_work 处理PDC事件
                => pciehp_check_presence 发送PDC事件
```


MODULE_DEVICE_TABLE

```c
struct pci_driver {
        struct list_head        node;
        const char              *name;
        const struct pci_device_id *id_table;   /* Must be non-NULL for probe to be called */
        int  (*probe)(struct pci_dev *dev, const struct pci_device_id *id);     /* New device inserted */
        void (*remove)(struct pci_dev *dev);    /* Device removed (NULL if not a hot-plug capable driver) */
        int  (*suspend)(struct pci_dev *dev, pm_message_t state);       /* Device suspended */
        int  (*suspend_late)(struct pci_dev *dev, pm_message_t state);
        int  (*resume_early)(struct pci_dev *dev);
        int  (*resume)(struct pci_dev *dev);    /* Device woken up */
        void (*shutdown)(struct pci_dev *dev);
        int  (*sriov_configure)(struct pci_dev *dev, int num_vfs); /* On PF */
        const struct pci_error_handlers *err_handler;
        const struct attribute_group **groups;
        struct device_driver    driver;
        struct pci_dynids       dynids;
};

```

pci_register_driver()
