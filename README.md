# blog.kernel.love

Personal tech blog by Yori Fang (Ying Fang), built with [Pelican](https://getpelican.com/).

**URL:** <https://blog.kernel.love>  
**Language:** Chinese  
**License:** CC BY-SA 3.0

## Content

37 articles organized by category:

| Category | Count | Focus |
|---|---|---|
| `virt/` | 26 | KVM/QEMU virtualization internals |
| `linux/` | 2 | Kernel debugging, kprobes |
| `misc/` | 2 | C11 memory model, Rust |
| `productivity/` | 2 | Neovim IDE setup |
| `pages/` | 3 | About, 404, landing page |
| `virtualization/` | 1 | x86 APICv (draft) |

### Key Topics

- **Intel VT-x/VT-d:** nested virtualization, VMCS shadowing, posted interrupts, interrupt remapping, DMA remapping
- **VFIO:** device passthrough, mediated devices (mdev), BAR mapping
- **ARM virtualization:** SMMU, GICv3, exception levels, two-stage translation
- **KVM:** steal time, PV TLB flush, Hyper-V enlightenments, vPMU
- **QEMU:** AIO, device hotplug, MMIO emulation, address spaces
- **virtio:** spec overview
- **microVMs:** lightweight virtualization
- **AMD:** x2AVIC
- **Renode:** embedded system simulation

## Tech Stack

- **Generator:** Pelican (Python)
- **Theme:** [Elegant](https://github.com/Pelican-Elegant/elegant) (git submodule)
- **Plugins:** assets, extract_toc, neighbors, render_math (MathJax), related_posts, share_post, series (git submodule)
- **Markdown:** extra, toc, codehilite (emacs style), admonition, wikilinks
- **Analytics:** Google Analytics

## Build

```bash
make html       # generate site → output/
make serve      # dev server at localhost:8000
make publish    # production build
```
