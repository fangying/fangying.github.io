---
author: Yori Fang
title: my-notes
date: 2020-04-11 23:00
status: draft
slug: my-notes
tags: notes
---

```
$ vim --version
VIM - Vi IMproved 8.1 (2018 May 18, compiled Dec 10 2018 12:00:45)
包含补丁: 1-575
修改者 <bugzilla@redhat.com>
编译者 <bugzilla@redhat.com>
巨型版本 无图形界面。  可使用(+)与不可使用(-)的功能:
+acl               +extra_search      +mouse_netterm     +tag_old_static
+arabic            +farsi             +mouse_sgr         -tag_any_white
+autocmd           +file_in_path      -mouse_sysmouse    -tcl
+autochdir         +find_in_path      +mouse_urxvt       +termguicolors
-autoservername    +float             +mouse_xterm       +terminal
-balloon_eval      +folding           +multi_byte        +terminfo
+balloon_eval_term -footer            +multi_lang        +termresponse
-browse            +fork()            -mzscheme          +textobjects
++builtin_terms    +gettext           +netbeans_intg     +timers
+byte_offset       -hangul_input      +num64             +title
+channel           +iconv             +packages          -toolbar
+cindent           +insert_expand     +path_extra        +user_commands
-clientserver      +job               +perl/dyn          +vartabs
-clipboard         +jumplist          +persistent_undo   +vertsplit
+cmdline_compl     +keymap            +postscript        +virtualedit
+cmdline_hist      +lambda            +printer           +visual
+cmdline_info      +langmap           +profile           +visualextra
+comments          +libcall           +python/dyn        +viminfo
+conceal           +linebreak         +python3/dyn       +vreplace
+cryptv            +lispindent        +quickfix          +wildignore
+cscope            +listcmds          +reltime           +wildmenu
+cursorbind        +localmap          +rightleft         +windows
+cursorshape       +lua/dyn           +ruby/dyn          +writebackup
+dialog_con        +menu              +scrollbind        -X11
+diff              +mksession         +signs             -xfontset
+digraphs          +modify_fname      +smartindent       -xim
-dnd               +mouse             +startuptime       -xpm
-ebcdic            -mouseshape        +statusline        -xsmp
+emacs_tags        +mouse_dec         -sun_workshop      -xterm_clipboard
+eval              +mouse_gpm         +syntax            -xterm_save
+ex_extra          -mouse_jsbterm     +tag_binary        
     系统 vimrc 文件: "/etc/vimrc"
     用户 vimrc 文件: "$HOME/.vimrc"
 第二用户 vimrc 文件: "~/.vim/vimrc"
      用户 exrc 文件: "$HOME/.exrc"
       defaults file: "$VIMRUNTIME/defaults.vim"
         $VIM 预设值: "/etc"
  $VIMRUNTIME 预设值: "/usr/share/vim/vim81"
编译方式: gcc -c -I. -Iproto -DHAVE_CONFIG_H     -O2 -g -pipe -Wall -Werror=format-security -Wp,-D_GLIBCXX_ASSERTIONS -fexceptions -fstack-protector-strong -grecord-gcc-switches -specs=/usr/lib/rpm/redhat/redhat-hardened-cc1 -specs=/usr/lib/rpm/redhat/redhat-annobin-cc1 -m64 -mtune=generic -fasynchronous-unwind-tables -fstack-clash-protection -fcf-protection -D_GNU_SOURCE -D_FILE_OFFSET_BITS=64 -I/usr/include/python3.6m -U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=1       
链接方式: gcc   -L. -Wl,-z,relro   -Wl,-z,now -specs=/usr/lib/rpm/redhat/redhat-hardened-ld -fstack-protector -rdynamic -Wl,-export-dynamic -Wl,--enable-new-dtags -Wl,-z,relro -Wl,-z,now -specs=/usr/lib/rpm/redhat/redhat-hardened-ld  -Wl,-z,relro   -Wl,-z,now -specs=/usr/lib/rpm/redhat/redhat-hardened-ld -L/usr/local/lib -Wl,--as-needed -o vim        -lm  -lselinux   -lncurses -lacl -lattr -lgpm -ldl   -Wl,--enable-new-dtags -Wl,-z,relro -Wl,-z,now -specs=/usr/lib/rpm/redhat/redhat-hardened-ld -Wl,-z,relro -Wl,-z,now -specs=/usr/lib/rpm/redhat/redhat-hardened-ld -fstack-protector-strong -L/usr/local/lib  -L/usr/lib64/perl5/CORE -lperl -lpthread -lresolv -ldl -lm -lcrypt -lutil -lc        

```

 ```
 http://blog.chinaunix.net/uid-29634482-id-5175302.html

 https://www.bottomupcs.com/
 ```

Device Passthrough live migration 
```
SRIOV network bonding
https://www.fujitsu.com/jp/documents/products/software/os/linux/catalog/LinuxConJapan2015-Izumi.pdf
SRIOV failover
https://www.kernel.org/doc/html/latest/networking/net_failover.html

GPU live migration
* 等待GPU的workload结束，完全拷贝FB，这样不用CareDMA。关键是要Stop vGPU Scheduling Here
```
