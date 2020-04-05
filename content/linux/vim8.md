Title:  VIM8 Customized Configuration
Date: 2019-3-8 23:00
Modified: 2019-3-8 23:00
Tags: virtualization
Category: utils
Slug: vim8
Status: published
Authors: Yori Fang
Summary: vim8

### 是时候秀一下我的VIM8自定义配置了！
我个人是位忠实的vim用户，在浏览开源软件源代码的时候和在写作代码的时候我大部分时间都在使用vim，
它的很多优点使我很享受软件开发的乐趣，我很喜欢折腾一个自己喜欢的vim配置文件然后用它来工作．

VIM8已经发布一两年了，已逐渐趋于稳定，所以是时候舍弃VIM7转投功能强大的VIM8了.
VIM8最强大的地方是给我们带来了期待已久的异步任务机制．
异步任务机制的强大之处在于它允许各种插件创建异步任务而不会阻塞当前的编辑，
例如:允许ctags再后台为我们生成和更新符号表，允许ale再后台自动给我们编辑的文件做语法校验。
由于这些过程是异步的，用户感知不到。
折腾了一天之后我终于配置好了一个我心仪的版本，是时候秀一下我的VIM8配置文件了!

![vfio-pci-bar](../images/vim8.svg)

### 1.安装vim8

我们选择从源码安装vim8，因为我们需要让vim8支持python解释器和ruby解释器．
```bash
git clone https://github.com/vim/vim.git 
cd vim
./configure --with-features=huge \
            --enable-multibyte \
            --enable-rubyinterp=yes \
            --enable-pythoninterp=yes \
            --with-python-config-dir=/usr/lib/python2.7/config \
            --enable-python3interp=yes \
            --with-python3-config-dir=/usr/lib/python3.5/config \
            --enable-luainterp=yes \
            --enable-gui=gtk2 \
	    --with-ruby-command=$(which ruby) \
            --enable-cscope
make -j && sudo make install
```

### 2.配置vim8前的准备工作

配置VIM8之前，我们需要先安装一下新的插件管理器`plug.vim`．
```bash
curl -fLo ~/.vim/autoload/plug.vim --create-dirs \
    https://raw.githubusercontent.com/junegunn/vim-plug/master/plug.vim
```
或者
```bash
mkdir -pv ~/.vim/autoload
wget https://raw.githubusercontent.com/junegunn/vim-plug/master/plug.vim -O ~/.vim/autoload/plug.vim
```
安装 GNU Global和 Universal ctags
```
git clone https://github.com/universal-ctags/ctags.git
cd ctags
sh autogen.sh
./configure
make -j
sudo make install

wget http://tamacom.com/global/global-6.6.3.tar.gz --no-check-certificate
tar xf global-6.6.3.tar.gz
cd global-6.6.3
sed -i "s/(int i = 0;/(i = 0;/g" gtags-cscope/find.c
sed -i "/regex_t reg;/a\int i;" gtags-cscope/find.c
./configure
make -j
sudo make install

pip install pygments  # 这个一定要安装！！！
```

### 3.配置vim8的插件系统

先配置一下`plug.vim`，然后让`plug.vim`帮助我们自动管理插件，编辑~/.vimrc文件．
```
" Specify a directory for plugins
" - For Neovim: ~/.local/share/nvim/plugged
" - Avoid using standard Vim directory names like 'plugin'
call plug#begin('~/.vim/plugged')

" All of your Plugs must be added before the following line
call plug#end()              " required
```
plug#begin到plug#end之间的内容是受`plug.vim`管理的，我们大部分的配置文件都放在这里．
下面开始安装插件：
```
if exists('&colorcolumn')
    set colorcolumn=80
endif
set paste
syntax on		      " syntax highlight
set nu
set nocompatible              " be iMproved, required
filetype off                  " required
set t_Co=256
set backspace=indent,eol,start

call plug#begin('~/.vim/plugged')

" basic plug
Plug 'tpope/vim-fugitive'             " git support
Plug 'vim-scripts/L9'
Plug 'rstacruz/sparkup', {'rtp': 'vim/'}

" utils
Plug 'vim-scripts/DrawIt'
Plug 'mbriggs/mark.vim'
Plug 'vim-scripts/tabbar'
Plug 'wesleyche/Trinity'
Plug 'vim-scripts/Smart-Tabs'
Plug 'nvie/vim-togglemouse'
Plug 'tpope/vim-unimpaired'
Plug 'scrooloose/syntastic'
Plug 'bronson/vim-trailing-whitespace'
Plug 'tpope/vim-surround'
Plug 'junegunn/vim-easy-align'
Plug 'Lokaltog/vim-easymotion'
Plug 'Yggdroot/indentLine'
Plug 'itchyny/lightline.vim'

" YCM
Plug 'Valloric/YouCompleteMe'

" file lookup
Plug 'vim-scripts/command-t'
Plug 'Yggdroot/LeaderF', { 'do': './install.sh' }

" async grama check
"Plug 'w0rp/ale'
Plug 'skywind3000/asyncrun.vim'

" language specific enhance
Plug 'vim-scripts/c.vim'
Plug 'vim-scripts/a.vim'
Plug 'octol/vim-cpp-enhanced-highlight'
Plug 'jnwhiteh/vim-golang'
Plug 'rust-lang/rust.vim'
Plug 'pangloss/vim-javascript'

" color
"Plug 'sunuslee/vim-plugin-random-colorscheme-picker'
Plug 'altercation/vim-colors-solarized'
Plug 'crusoexia/vim-monokai'
Plug 'flazz/vim-colorschemes'         " vim colorschemes
Plug 'rafi/awesome-vim-colorschemes'  " vim colorschemes
Plug 'lifepillar/vim-solarized8'      " solarized8

" gtags and gnu global support
Plug 'vim-scripts/gtags.vim'
Plug 'vim-scripts/autopreview'
Plug 'vim-scripts/genutils'
Plug 'ludovicchabant/vim-gutentags'
Plug 'skywind3000/gutentags_plus'

" gutentags config
set cscopeprg='gtags-cscope'
set tags=./.tags;.tags
let $GTAGSLABEL = 'native'
let $GTAGSCONF = '/usr/local/share/gtags/gtags.conf'
let g:gutentags_project_root = ['.git','.root','.svn','.hg','.project']
let g:gutentags_ctags_tagfile = '.tags'
let g:gutentags_modules = []
if executable('gtags-cscope') && executable('gtags')
	let g:gutentags_modules += ['gtags_cscope']
endif
if executable('ctags')
	let g:gutentags_modules += ['ctags']
endif
let g:gutentags_cache_dir = expand('~/.cache/tags')
let g:gutentags_ctags_extra_args = []
let g:gutentags_ctags_extra_args = ['--fields=+niazS', '--extra=+q']
let g:gutentags_ctags_extra_args += ['--c++-kinds=+px']
let g:gutentags_ctags_extra_args += ['--c-kinds=+px']

let g:gutentags_ctags_extra_args += ['--output-format=e-ctags']
let g:gutentags_auto_add_gtags_cscope = 0
let g:gutentags_plus_switch = 1
let g:asyncrun_bell = 1
let g:gutentags_define_advanced_commands = 1
let g:gutentags_generate_on_empty_buffer = 1	" open database

"let g:gutentags_trace = 1

Plug 'skywind3000/vim-preview'
"press shift + p to Preview, press p to close 
autocmd FileType qf nnoremap <silent><buffer> p :PreviewQuickfix<cr>
autocmd FileType qf nnoremap <silent><buffer> P :PreviewClose<cr>
noremap <Leader>u :PreviewScroll -1<cr> 	" pageup 
noremap <leader>d :PreviewScroll +1<cr> 	" pagedown
noremap <silent> <leader>gs :GscopeFind s <C-R><C-W><cr>
noremap <silent> <leader>gg :GscopeFind g <C-R><C-W><cr>
noremap <silent> <leader>gc :GscopeFind c <C-R><C-W><cr>
noremap <silent> <leader>gt :GscopeFind t <C-R><C-W><cr>
noremap <silent> <leader>ge :GscopeFind e <C-R><C-W><cr>
noremap <silent> <leader>gf :GscopeFind f <C-R>=expand("<cfile>")<cr><cr>
noremap <silent> <leader>gi :GscopeFind i <C-R>=expand("<cfile>")<cr><cr>
noremap <silent> <leader>gd :GscopeFind d <C-R><C-W><cr>
noremap <silent> <leader>ga :GscopeFind a <C-R><C-W><cr>

" LeaderF
let g:Lf_ShortcutF = '<c-p>'
noremap <Leader>ff :LeaderfFunction<cr>
noremap <Leader>fb :LeaderfBuffer<cr>
noremap <Leader>ft :LeaderfTag<cr>
noremap <Leader>fm :LeaderfMru<cr>
noremap <Leader>fl :LeaderfLine<cr>

let g:Lf_StlSeparator = { 'left': '', 'right': '', 'font': '' }
let g:Lf_RootMarkers = ['.project', '.root', '.svn', '.git']
let g:Lf_WorkingDirectoryMode = 'Ac'
let g:Lf_WindowHeight = 0.30
let g:Lf_CacheDirectory = expand('~/.vim/cache')
let g:Lf_ShowRelativePath = 0
let g:Lf_HideHelp = 1
let g:Lf_StlColorscheme = 'powerline'
let g:Lf_PreviewResult = {'Function':0, 'BufTag':0}

let g:Lf_NormalMap = {
	\ "File":   [["<ESC>", ':exec g:Lf_py "fileExplManager.quit()"<CR>']],
	\ "Buffer": [["<ESC>", ':exec g:Lf_py "bufExplManager.quit()"<CR>']],
	\ "Mru":    [["<ESC>", ':exec g:Lf_py "mruExplManager.quit()"<CR>']],
	\ "Tag":    [["<ESC>", ':exec g:Lf_py "tagExplManager.quit()"<CR>']],
	\ "Function":    [["<ESC>", ':exec g:Lf_py "functionExplManager.quit()"<CR>']],
	\ "Colorscheme":    [["<ESC>", ':exec g:Lf_py "colorschemeExplManager.quit()"<CR>']],
	\ }
" latex support
Plug 'lervag/vimtex'
let g:tex_flavor='latex'
let g:vimtex_view_method='zathura'
let g:vimtex_quickfix_mode=0
set conceallevel=1
let g:tex_conceal='abdmg'

" UltiSnips
Plug 'sirver/ultisnips'
let g:UltiSnipsExpandTrigger = '<tab>'
let g:UltiSnipsJumpForwardTrigger = '<tab>'
let g:UltiSnipsJumpBackwardTrigger = '<s-tab>'

" All of your Plugs must be added before the following line
call plug#end()              " required


filetype plugin indent on    " required
" To ignore plugin indent changes, instead use:
"filetype plugin on

" Put your non-Plug stuff after this line
set tabstop=8
set softtabstop=8
set shiftwidth=4
"set expandtab
set hls
set encoding=utf-8
set listchars=tab:>-,trail:-

" set F5, F6 to find function and symbol
nnoremap <F5> :GscopeFind gs 
nnoremap <F9> :GscopeFind gg 
nnoremap <F4> :ccl <CR>
nnoremap <F2> :let g:gutentags_trace = 1 <CR>
nnoremap <F3> :let g:gutentags_trace = 0 <CR>

" color desert
color Tomorrow-Night-Bright
```
更新配置文件之后调用 vim +PlugInstall +qall 安装全部插件，执行这个命令Plug会自动下载全部的插件到vim插件目录下。
```bash
vim +PlugInstall +qall
```

这里最重要的一组插件是`vim-gutentags.vim`和`gutentags_plus.vim`，
通过这两个插件配合安装GNU Global和 universal ctags工具，
可以为我们自动异步生成项目的符号表，
可以很方便地查找符号定义和调用关系，
再也不用我们去手动生成和维护tags更新了．
具体配置方式参考:

<https://zhuanlan.zhihu.com/p/36279445>

YCM插件需要自己去编译一下，具体步骤见：

<https://github.com/ycm-core/YouCompleteMe#installation>

其他插件的搭配也非常合理和高效，具体的使用方式参考该插件的help doc.


不早了，洗洗睡了！
