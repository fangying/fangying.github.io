Title: Use NeoVim on Apple M1 MacOS bigSur
Date: 2021-2-22 23:00
Modified: 2021-2-22 23:00
Tags: neovim
Slug: neovim-bigSur-apple-m1
Status: published
Authors: Yori Fang
Summary: Use neovim on Apple M1 MacOS bigSur

最近开始切换到neovim了，毕竟neovim的设计理念相对vim8要超前很多。
经过一番配置折腾，我成功在bigSur Apple M1的MBP上配置好了neovim，
这里强烈推荐coc.nvim，这个插件能帮助我们实现类似vscode的强大功能，
它提供了LSP的支持，并且支持多种编程语言，用起来如丝般顺滑，个人体验感觉甩掉YCM几条街。
终于可以一个插件搞定函数定义跳转，引用查找，自动提示等一系列功能了。

## 安装neovim

在Apple M1 bigSur上现在已经支持通过`homebrew`方式安装neovim了。

```bash
xcode-select --install
brew install --HEAD tree-sitter
brew install --HEAD luajit
brew install --HEAD neovim
```
安装好后nvim的默认路径是：/opt/homebrew/bin/nvim，
可以将/opt/homebrew/bin添加的PATH环境变量中。

```bash
nvim -v

NVIM v0.5.0-dev+nightly
Build type: Release
LuaJIT 2.1.0-beta3
Compilation: /usr/bin/clang -U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=1 -DNDEBUG -Wall -Wextra -pedantic -Wno-unused-parameter -Wstrict-prototypes -std=gnu99 -Wshadow -Wconversion -Wmissing-prototypes -Wimplicit-fallthrough -Wvla -fstack-protector-strong -fno-common -fdiagnostics-color=auto -DINCLUDE_GENERATED_DECLARATIONS -D_GNU_SOURCE -DNVIM_MSGPACK_HAS_FLOAT32 -DNVIM_UNIBI_HAS_VAR_FROM -DMIN_LOG_LEVEL=3 -I/tmp/neovim-20210222-25344-s2v8tf/build/config -I/tmp/neovim-20210222-25344-s2v8tf/src -I/opt/homebrew/include -I/tmp/neovim-20210222-25344-s2v8tf/deps-build/include -I/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/include -I/opt/homebrew/opt/gettext/include -I/tmp/neovim-20210222-25344-s2v8tf/build/src/nvim/auto -I/tmp/neovim-20210222-25344-s2v8tf/build/include
编译者 yingfang@fang

Features: +acl +iconv +tui
See ":help feature-compile"

     系统 vimrc 文件: "$VIM/sysinit.vim"
         $VIM 预设值: "/opt/homebrew/Cellar/neovim/HEAD-595f6e4/share/nvim"

Run :checkhealth for more info
```

## 安装coc.nvim

nvim的默认配置文件路径是：~/.config/nvim/init.vim，这里自己创建一下就好了。
```bash
mkdir -pv ~/.config/nvim
touch ~/.config/nvim/init.vim
```

coc.nvim的安装很简单，使用`vim-plug`插件管理器即可：
```bash
" Use release branch (recommend)
Plug 'neoclide/coc.nvim', {'branch': 'release'}
```
执行nvim +PlugInstall +qall来安装插件。

coc.nvim依赖于nodejs，所以这里要安装一下nodejs。
另外安装一下几个常见的coc插件。
```bash
brew install nodejs
# vim执行命令
:CocInstall coc-json coc-snippets coc-toml coc-clangd coc-clangd coc-rust-analyzer
:CocIntsall coc-marketplace # 这个插件帮助我们查看全部的插件列表，很实用
```

这里直接使用coc.nvim推荐的默认配置，
从[coc.nvim](https://github.com/neoclide/coc.nvim)直接拷贝就行了，追加到init.vim。

```
" TextEdit might fail if hidden is not set.
set hidden

" Some servers have issues with backup files, see #649.
set nobackup
set nowritebackup

" Give more space for displaying messages.
set cmdheight=2

" Having longer updatetime (default is 4000 ms = 4 s) leads to noticeable
" delays and poor user experience.
set updatetime=300

" Don't pass messages to |ins-completion-menu|.
set shortmess+=c

" Always show the signcolumn, otherwise it would shift the text each time
" diagnostics appear/become resolved.
if has("patch-8.1.1564")
  " Recently vim can merge signcolumn and number column into one
  set signcolumn=number
else
  set signcolumn=yes
endif

" Use tab for trigger completion with characters ahead and navigate.
" NOTE: Use command ':verbose imap <tab>' to make sure tab is not mapped by
" other plugin before putting this into your config.
inoremap <silent><expr> <TAB>
      \ pumvisible() ? "\<C-n>" :
      \ <SID>check_back_space() ? "\<TAB>" :
      \ coc#refresh()
inoremap <expr><S-TAB> pumvisible() ? "\<C-p>" : "\<C-h>"

function! s:check_back_space() abort
  let col = col('.') - 1
  return !col || getline('.')[col - 1]  =~# '\s'
endfunction

" Use <c-space> to trigger completion.
if has('nvim')
  inoremap <silent><expr> <c-space> coc#refresh()
else
  inoremap <silent><expr> <c-@> coc#refresh()
endif

" Make <CR> auto-select the first completion item and notify coc.nvim to
" format on enter, <cr> could be remapped by other vim plugin
inoremap <silent><expr> <cr> pumvisible() ? coc#_select_confirm()
                              \: "\<C-g>u\<CR>\<c-r>=coc#on_enter()\<CR>"

" Use `[g` and `]g` to navigate diagnostics
" Use `:CocDiagnostics` to get all diagnostics of current buffer in location list.
nmap <silent> [g <Plug>(coc-diagnostic-prev)
nmap <silent> ]g <Plug>(coc-diagnostic-next)

" GoTo code navigation.
nmap <silent> gd <Plug>(coc-definition)
nmap <silent> gy <Plug>(coc-type-definition)
nmap <silent> gi <Plug>(coc-implementation)
nmap <silent> gr <Plug>(coc-references)

" Use K to show documentation in preview window.
nnoremap <silent> K :call <SID>show_documentation()<CR>

function! s:show_documentation()
  if (index(['vim','help'], &filetype) >= 0)
    execute 'h '.expand('<cword>')
  elseif (coc#rpc#ready())
    call CocActionAsync('doHover')
  else
    execute '!' . &keywordprg . " " . expand('<cword>')
  endif
endfunction

" Highlight the symbol and its references when holding the cursor.
autocmd CursorHold * silent call CocActionAsync('highlight')

" Symbol renaming.
nmap <leader>rn <Plug>(coc-rename)

" Formatting selected code.
xmap <leader>f  <Plug>(coc-format-selected)
nmap <leader>f  <Plug>(coc-format-selected)

augroup mygroup
  autocmd!
  " Setup formatexpr specified filetype(s).
  autocmd FileType typescript,json setl formatexpr=CocAction('formatSelected')
  " Update signature help on jump placeholder.
  autocmd User CocJumpPlaceholder call CocActionAsync('showSignatureHelp')
augroup end

" Applying codeAction to the selected region.
" Example: `<leader>aap` for current paragraph
xmap <leader>a  <Plug>(coc-codeaction-selected)
nmap <leader>a  <Plug>(coc-codeaction-selected)

" Remap keys for applying codeAction to the current buffer.
nmap <leader>ac  <Plug>(coc-codeaction)
" Apply AutoFix to problem on the current line.
nmap <leader>qf  <Plug>(coc-fix-current)

" Map function and class text objects
" NOTE: Requires 'textDocument.documentSymbol' support from the language server.
xmap if <Plug>(coc-funcobj-i)
omap if <Plug>(coc-funcobj-i)
xmap af <Plug>(coc-funcobj-a)
omap af <Plug>(coc-funcobj-a)
xmap ic <Plug>(coc-classobj-i)
omap ic <Plug>(coc-classobj-i)
xmap ac <Plug>(coc-classobj-a)
omap ac <Plug>(coc-classobj-a)

" Remap <C-f> and <C-b> for scroll float windows/popups.
if has('nvim-0.4.0') || has('patch-8.2.0750')
  nnoremap <silent><nowait><expr> <C-f> coc#float#has_scroll() ? coc#float#scroll(1) : "\<C-f>"
  nnoremap <silent><nowait><expr> <C-b> coc#float#has_scroll() ? coc#float#scroll(0) : "\<C-b>"
  inoremap <silent><nowait><expr> <C-f> coc#float#has_scroll() ? "\<c-r>=coc#float#scroll(1)\<cr>" : "\<Right>"
  inoremap <silent><nowait><expr> <C-b> coc#float#has_scroll() ? "\<c-r>=coc#float#scroll(0)\<cr>" : "\<Left>"
  vnoremap <silent><nowait><expr> <C-f> coc#float#has_scroll() ? coc#float#scroll(1) : "\<C-f>"
  vnoremap <silent><nowait><expr> <C-b> coc#float#has_scroll() ? coc#float#scroll(0) : "\<C-b>"
endif

" Use CTRL-S for selections ranges.
" Requires 'textDocument/selectionRange' support of language server.
nmap <silent> <C-s> <Plug>(coc-range-select)
xmap <silent> <C-s> <Plug>(coc-range-select)

" Add `:Format` command to format current buffer.
command! -nargs=0 Format :call CocAction('format')

" Add `:Fold` command to fold current buffer.
command! -nargs=? Fold :call     CocAction('fold', <f-args>)

" Add `:OR` command for organize imports of the current buffer.
command! -nargs=0 OR   :call     CocAction('runCommand', 'editor.action.organizeImport')

" Add (Neo)Vim's native statusline support.
" NOTE: Please see `:h coc-status` for integrations with external plugins that
" provide custom statusline: lightline.vim, vim-airline.
set statusline^=%{coc#status()}%{get(b:,'coc_current_function','')}

" Mappings for CoCList
" Show all diagnostics.
nnoremap <silent><nowait> <space>a  :<C-u>CocList diagnostics<cr>
" Manage extensions.
nnoremap <silent><nowait> <space>e  :<C-u>CocList extensions<cr>
" Show commands.
nnoremap <silent><nowait> <space>c  :<C-u>CocList commands<cr>
" Find symbol of current document.
nnoremap <silent><nowait> <space>o  :<C-u>CocList outline<cr>
" Search workspace symbols.
nnoremap <silent><nowait> <space>s  :<C-u>CocList -I symbols<cr>
" Do default action for next item.
nnoremap <silent><nowait> <space>j  :<C-u>CocNext<CR>
" Do default action for previous item.
nnoremap <silent><nowait> <space>k  :<C-u>CocPrev<CR>
" Resume latest coc list.
nnoremap <silent><nowait> <space>p  :<C-u>CocListResume<CR>
```
可以参考我的neovim配置文件：
https://github.com/fangying/vim/blob/master/init.vim

## 配置rust-analyzer的支持

使用:CocConfig命令，新增配置文件，开启对rust-analyzer的支持。
记得提前下载rust-analyzer二进制，放到~/.cargo/bin目录下，不然会提升找不到。

```
{                                                                                                                                              
  "coc.preferences.formatOnSaveFiletypes": [                                    
    "rust"                                                                      
  ],                                                                            
  "diagnostic.errorSign": "✘",                                                  
  "diagnostic.infoSign": "i",                                                   
  "languageserver": {                                                           
    "rust": {                                                                   
      "command": "rust-analyzer",                                               
      "filetypes": ["rust"],                                                    
      "rootPatterns": ["Cargo.toml"]                                            
    },                                                                          
    "ccls": {                                                                   
      "command": "ccls",                                                        
      "args": ["--log-file=/tmp/ccls.log", "-v=1"],                             
      "filetypes": ["c", "cc", "cpp", "c++", "objc", "objcpp"],                 
      "rootPatterns": [".ccls", "compile_commands.json", ".git/", ".hg/"],      
      "initializationOptions": {                                                
        " cache": {                                                             
          "directory": ".ccls-cache"                                            
        },                                                                      
        "client": {                                                             
          "snippetSupport": true                                                
        },                                                                      
        "clang": {                                                              
            "extraArgs": [                                                      
            "-isystem",                                                         
            "/opt/homebrew/Cellar/llvm/11.0.1/include/c++/v1"                   
            ],                                                                  
            "resourceDir": "/Library/Developer/CommandLineTools/usr/lib/clang/12.0.0/"
        }                                                                       
      }                                                                         
    }                                                                           
  },                                                                            
  "rust-analyzer.server.path": "~/.cargo/bin/rust-analyzer",                    
  "rust-analyzer.diagnostics.enable": true,                                     
  "rust-analyzer.inlayHints.chainingHints": true,                               
  "rust-analyzer.inlayHints.typeHints": true                                    
}             
```

