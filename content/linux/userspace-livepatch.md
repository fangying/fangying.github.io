Title:  Userspace Livepatch Internal
Date: 2020-6-23 23:00
Modified: 2020-6-23 23:00
Tags: livepatch
Slug: userspace-livepatch
Status: draft
Authors: Yori Fang
Summary: Userspace Livepatch


## 1. What is livepatch

## 2. Kernel livepatch solutions

## 3. Userspace livepatch internal

the ELF format
```
    ELF header
    program header
    section header
```
## 4. The libcare livepatch internal

## 5. Use libcare to patch process

查看断点处的rip寄存器值：
```
(gdb) info reg
rax            0x0                 0
rbx            0x0                 0
rcx            0x7fd6498fa185      140558333878661
rdx            0x0                 0
rsi            0x7fd648825ea0      140558316232352
rdi            0x0                 0
rbp            0x0                 0x0
rsp            0x7fd648825ed8      0x7fd648825ed8
r8             0x0                 0
r9             0x22                34
r10            0x7fd648825d92      140558316232082
r11            0x0                 0
r12            0x7ffffc51254e      140737426564430
r13            0x7ffffc51254f      140737426564431
r14            0x7ffffc512550      140737426564432
r15            0x7fd648825fc0      140558316232640
rip            0x401269            0x401269 <thread3_say>
eflags         0x202               [ IF ]
cs             0x33                51
ss             0x2b                43
ds             0x0                 0
es             0x0                 0
fs             0x0                 0
gs             0x0                 0
```
对rip指向的内容进行反汇编，可以看到thread3_say的汇编指令内容：
```asm
(gdb) x/20i 0x401269
=> 0x401269 <thread3_say>:      jmpq   0xa0b4b5
   0x40126e <thread3_say+5>:    add    $0x2ddd,%eax
   0x401273 <thread3_say+10>:   add    $0x1,%eax
   0x401276 <thread3_say+13>:   mov    %eax,0xc(%rsp)
   0x40127a <thread3_say+17>:   mov    0xc(%rsp),%eax
   0x40127e <thread3_say+21>:   mov    %eax,%esi
   0x401280 <thread3_say+23>:   mov    $0x4020d0,%edi
   0x401285 <thread3_say+28>:   mov    $0x0,%eax
   0x40128a <thread3_say+33>:   callq  0x401060 <printf@plt>
   0x40128f <thread3_say+38>:   mov    $0xa,%edi
   0x401294 <thread3_say+43>:   callq  0x401030 <putchar@plt>
   0x401299 <thread3_say+48>:   movl   $0x29a,%fs:0xfffffffffffffffc
   0x4012a5 <thread3_say+60>:   mov    %fs:0xfffffffffffffffc,%eax
   0x4012ad <thread3_say+68>:   mov    %eax,%esi
   0x4012af <thread3_say+70>:   mov    $0x4020f8,%edi
   0x4012b4 <thread3_say+75>:   mov    $0x0,%eax
   0x4012b9 <thread3_say+80>:   callq  0x401060 <printf@plt>
   0x4012be <thread3_say+85>:   nop
   0x4012bf <thread3_say+86>:   add    $0x18,%rsp
   0x4012c3 <thread3_say+90>:   retq   
```
可以看到第一条指令替换成了jmpq指令，跳转到地址0xa0b4b5处，看下这里的补丁文件汇编内容。
```asm
(gdb) x/40i 0xa0b4b5
   0xa0b4b5:    sub    $0x18,%rsp
   0xa0b4b9:    mov    $0x404050,%rax
   0xa0b4c0:    mov    (%rax),%eax
   0xa0b4c2:    sub    $0x1,%eax
   0xa0b4c5:    mov    %eax,0xc(%rsp)
   0xa0b4c9:    mov    0xc(%rsp),%eax
   0xa0b4cd:    mov    %eax,%esi
   0xa0b4cf:    mov    $0x4020d0,%edi
   0xa0b4d4:    mov    $0x0,%eax
   0xa0b4d9:    callq  0xa0c890
   0xa0b4de:    mov    $0xa,%edi
   0xa0b4e3:    callq  0xa0c880
   0xa0b4e8:    movl   $0xa2c2a,%fs:0xfffffffffffffffc
   0xa0b4f4:    mov    %fs:0xfffffffffffffffc,%eax
   0xa0b4fc:    mov    %eax,%esi
   0xa0b4fe:    mov    $0x4020f8,%edi
   0xa0b503:    mov    $0x0,%eax
   0xa0b508:    callq  0xa0c890
   0xa0b50d:    nop
   0xa0b50e:    add    $0x18,%rsp
   0xa0b512:    retq   
```
## 6. References

1. https://github.com/cloudlinux/libcare
2. https://github.com/libunwind/libunwind
3. https://github.com/cloudlinux/libcare/blob/master/docs/internals.rst
4. https://vincent.bernat.ch/en/blog/2015-hotfix-qemu-venom
5. http://david-grs.github.io/tls_performance_overhead_cost_linux/
6. http://articles.manugarg.com/aboutelfauxiliaryvectors
7. https://man7.org/linux/man-pages/man5/elf.5.html
8. https://www.cnblogs.com/mmmmar/p/6040325.html
9. http://actes.sstic.org/SSTIC06/Playing_with_ptrace/SSTIC06-article-Bareil-Playing_with_ptrace.pdf
10. https://en.wikipedia.org/wiki/Dynamic_software_updating
11. https://github.com/torvalds/linux/tree/master/kernel/livepatch