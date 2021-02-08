Title: Use vim8 on Apple M1 MacOS bigSur
Date: 2021-2-8 23:00
Modified: 2021-2-8 23:00
Tags: vim8
Slug: vim-bigSur-apple-m1
Status: published
Authors: Yori Fang
Summary: Use vim8 on Apple M1 MacOS bigSur

年前入手了Apple M1 MacBookPro，这是Apple第一款自研芯片的MBP，大小是13寸相对较为实用。
由于是ARM64架构，在刚上来的时候很多研发工具软件对系统的支持还不是太完善，但经过几个月的
发展目前已经基本能够满足日常开发需求。

安利3个传送门，可以方便地查询到各种生态软件对Apple M1的支持最新进展情况。

* 传送门1：

https://isapplesiliconready.com/zh

* 传送门2：

https://github.com/ThatGuySam/doesitarm

* 传送门3：

https://doesitarm.com/

由于我们是从事系统开发的软件行业，vim成为了日常看代码的必备工具，为此有必要设置一下Apple M1下的vim8工作环境。

## 配置vim8

M1上默认安装了vim 8.2版本，编译特性也很全：

```bash
vim --version
VIM - Vi IMproved 8.2 (2019 Dec 12, compiled Dec 21 2020 20:40:21)
macOS version
Included patches: 1-850, 1972
Compiled by root@apple.com
```

vim插件配置可以参考:[https://kernelgo.org/vim8](https://kernelgo.org/vim8)
请自行阅读，这里不再详述。
在新的Apple M1上主要遇到了2个问题，导致vim8无法很好正常工作。

## 编译gnu global

由于要使用global来查看函数调用关系，所以我们要自己编译global来完成这个重要功能。
但是编译的时候会报错无法找到'realpath'。问题社区已经有报告:

https://lists.gnu.org/archive/html/bug-global/2021-01/msg00001.html

```
checking for dirent.h that defines DIR... yes
checking for library containing opendir... none required
checking whether POSIX.1-2008 realpath is equipped... no
configure: error: POSIX.1-2008 realpath(3) is required.
```

原因是configure脚本还没有适配好M1版本，这里提供一种规避方案：
```c
diff --git a/configure b/configure
index 100a690..4e54a52 100755
--- a/configure
+++ b/configure
@@ -14273,33 +14273,6 @@ case "$host_os" in
 	mingw*|*djgpp*)
 	;;
 	*)
-{ $as_echo "$as_me:${as_lineno-$LINENO}: checking whether POSIX.1-2008 realpath is equipped" >&5
-$as_echo_n "checking whether POSIX.1-2008 realpath is equipped... " >&6; }
-if ${ac_cv_posix1_2008_realpath+:} false; then :
-  $as_echo_n "(cached) " >&6
-else
-  if test "$cross_compiling" = yes; then :
-  { { $as_echo "$as_me:${as_lineno-$LINENO}: error: in \`$ac_pwd':" >&5
-$as_echo "$as_me: error: in \`$ac_pwd':" >&2;}
-as_fn_error $? "cannot run test program while cross compiling
-See \`config.log' for more details" "$LINENO" 5; }
-else
-  cat confdefs.h - <<_ACEOF >conftest.$ac_ext
-/* end confdefs.h.  */
-
-main(){ (void)realpath("/./tmp", (void *)0); return 0; }
-
-_ACEOF
-if ac_fn_c_try_run "$LINENO"; then :
-  ac_cv_posix1_2008_realpath=yes
-else
-  ac_cv_posix1_2008_realpath=no
-fi
-rm -f core *.core core.conftest.* gmon.out bb.out conftest$ac_exeext \
-  conftest.$ac_objext conftest.beam conftest.$ac_ext
-fi
-
-fi
 
 { $as_echo "$as_me:${as_lineno-$LINENO}: result: $ac_cv_posix1_2008_realpath" >&5
 $as_echo "$ac_cv_posix1_2008_realpath" >&6; }
```
打上这个补丁之后，再次编译就能够顺利编译通过了。
```
./configure --with-universal-ctags=/usr/local/bin/ctags
make -j
sudo make install
```

## 修改gutentags配置参数

我们用universal-ctags来帮我们生成形系统符号表，这样我们可以用ctrl + ]来实现符号跳转。
在M1上需要注意的是，默认安装后可能会出现E433错误。
```
E433: No tags file
```
这里需要打开日志开关，取消下面配置的注释：
```
let g:gutentags_trace = 1
```
这样再次出现E433错误后，输入":messages"命令，可以看到错误的原因：
```
gutentags: Scanning buffer '' for gutentags setup...
gutentags: No specific project type.
gutentags: Setting gutentags for buffer ''
gutentags: Generating missing tags file: /Users/yingfang/.cache/tags/Users-yingfang-Code-opensrc-qemu-.tags
gutentags: Wildignore options file is up to date.
gutentags: Running: ['/Users/yingfang/.vim/plugged/vim-gutentags/plat/unix/update_tags.sh', '-e', 'ctags', '-t', '/Users/yingfang/.cache/tags/U
sers-yingfang-Code-opensrc-qemu-.tags', '-p', '/Users/yingfang/Code/opensrc/qemu', '-o', '/Users/yingfang/.vim/plugged/vim-gutentags/res/ctags_
recursive.options', '-O', '--fields=+niazS', '-O', '--extra=+q', '-O', '--c++-kinds=+pxI', '-O', '--c-kinds=+px', '-O', '--output-format=e-ctag
s', '-l', '/Users/yingfang/.cache/tags/Users-yingfang-Code-opensrc-qemu-.tags.log']
gutentags: In:      /Users/yingfang/Code/opensrc/qemu
gutentags: Generating tags file: /Users/yingfang/.cache/tags/Users-yingfang-Code-opensrc-qemu/GTAGS
gutentags: Running: ['gtags', '--incremental', '/Users/yingfang/.cache/tags/Users-yingfang-Code-opensrc-qemu']
gutentags: In:      /Users/yingfang/Code/opensrc/qemu
gutentags:
gutentags: [job stdout]: 'Locking tags file...'
gutentags: [job stdout]: 'Running ctags on whole project'
gutentags: [job stdout]: 'ctags -f "/Users/yingfang/.cache/tags/Users-yingfang-Code-opensrc-qemu-.tags.temp" "--options=/Users/yingfang/.vim/pl
ugged/vim-gutentags/res/ctags_recursive.options"  --fields=+niazS --extra=+q --c++-kinds=+pxI --c-kinds=+px --output-format=e-ctags "/Users/yin
gfang/Code/opensrc/qemu"'
gutentags: [job stderr]: 'ctags: Warning: --extra option is obsolete; use --extras instead'
gutentags: [job stderr]: 'ctags: Warning: Unsupported kind: ''I'' for --c++-kinds option'
gutentags: Finished gtags_cscope job.
```
原因是在M1上我们编译的ctags支持的参数命令上和X86平台上差异。
解决办法：修改-extra参数为-extras，去掉c++-kinds上的'I'。
修改后对应的配置项为:
```
let g:gutentags_ctags_extra_args = ['--fields=+niazS', '--extras=+q']           
let g:gutentags_ctags_extra_args += ['--c++-kinds=+px']                         
let g:gutentags_ctags_extra_args += ['--c-kinds=+px']  
```
改完之后应该就没有E433错误了。
到这里就可以在Apple M1上愉快的使用vim8来看代码了。

Peace.