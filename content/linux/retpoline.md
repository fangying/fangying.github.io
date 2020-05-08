Title: Intel CPU BUG
Date: 2018-12-14 23:00 
Modified: 2018-12-14 23:00 
Tags: retpoline
Slug: retpoline
Status: draft 
Authors: Yori Fang 
Summary: retpoline

https://stackoverflow.com/questions/48089426/what-is-a-retpoline-and-how-does-it-work

https://support.google.com/faqs/answer/7625886

```
B+>x0x550dfc <aio_ctx_prepare+16>   ldr    x0, [x29, #24]
   x0x550e00 <aio_ctx_prepare+20>   str    x0, [x29, #40] 
   x0x550e04 <aio_ctx_prepare+24>   ldr    x0, [x29, #40]
   x0x550e08 <aio_ctx_prepare+28>   add    x0, x0, #0xa8
   x0x550e0c <aio_ctx_prepare+32>   ldaxr  w1, [x0]
   x0x550e10 <aio_ctx_prepare+36>   orr    w1, w1, #0x1
   x0x550e14 <aio_ctx_prepare+40>   stlxr  w2, w1, [x0]
   x0x550e18 <aio_ctx_prepare+44>   cbnz   w2, 0x550e0c <aio_ctx_prepare+32>
   x0x550e1c <aio_ctx_prepare+48>   ldr    x0, [x29, #40]
   x0x550e20 <aio_ctx_prepare+52>   bl     0x550cf4 <aio_compute_timeout>
   x0x550e24 <aio_ctx_prepare+56>   bl     0x553414 <qemu_timeout_ns_to_ms>
   x0x550e28 <aio_ctx_prepare+60>   mov    w1, w0
   x0x550e2c <aio_ctx_prepare+64>   ldr    x0, [x29, #16]
   x0x550e30 <aio_ctx_prepare+68>   str    w1, [x0]
   x0x550e34 <aio_ctx_prepare+72>   ldr    x0, [x29, #40]
   x0x550e38 <aio_ctx_prepare+76>   bl     0x555f90 <aio_prepare>
```

```
B+>x0x55555564bea0 <aio_ctx_prepare>        push   %rbp
   x0x55555564bea1 <aio_ctx_prepare+1>      mov    %rsi,%rbp
   x0x55555564bea4 <aio_ctx_prepare+4>      push   %rbx
   x0x55555564bea5 <aio_ctx_prepare+5>      mov    %rdi,%rbx
   x0x55555564bea8 <aio_ctx_prepare+8>      sub    $0x8,%rsp
   x0x55555564beac <aio_ctx_prepare+12>     lock orl $0x1,0x98(%rdi)
   x0x55555564beb4 <aio_ctx_prepare+20>     callq  0x55555564be40 <aio_compute_timeout>
   x0x55555564beb9 <aio_ctx_prepare+25>     mov    %rax,%rdi
   x0x55555564bebc <aio_ctx_prepare+28>     callq  0x55555564d260 <qemu_timeout_ns_to_ms>
   x0x55555564bec1 <aio_ctx_prepare+33>     mov    %rbx,%rdi
   x0x55555564bec4 <aio_ctx_prepare+36>     mov    %eax,0x0(%rbp)
   x0x55555564bec7 <aio_ctx_prepare+39>     callq  0x55555564f060 <aio_prepare>
   x0x55555564becc <aio_ctx_prepare+44>     test   %al,%al
   x0x55555564bece <aio_ctx_prepare+46>     je     0x55555564bee8 <aio_ctx_prepare+72>
   x0x55555564bed0 <aio_ctx_prepare+48>     movl   $0x0,0x0(%rbp)
```
