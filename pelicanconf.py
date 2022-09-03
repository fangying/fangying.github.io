AUTHOR = 'YoriFang'
SITENAME = 'kernel.love'
SITEURL = 'https://kernel.love'
TIMEZONE = 'Asia/Shanghai'


PATH = 'content'
DEFAULT_LANG = u'en'
DATE_FORMATS = {'zh':'%Y-%m-%d %H:%M'}

# Feed generation is usually not desired when developing
FEED_ALL_ATOM = None
CATEGORY_FEED_ATOM = None
TRANSLATION_FEED_ATOM = None
AUTHOR_FEED_ATOM = None
AUTHOR_FEED_RSS = None

# Blogroll
LINKS = (('kernel', 'https://kernel.org/'),
        ('qemu.org', 'https://qemu.org/'),
        ('zhihu', 'https://www.zhihu.com/people/fangying712'),
        ('You can modify those links in your config file', '#'),)

# Social widget
SOCIAL = (('github', 'https://github.com/fangying'),
         ('Another social link', '#'),)

# defaults
DEFAULT_PAGINATION = False
USE_FOLDER_AS_CATEGORY = True
DELETE_OUTPUT_DIRECTORY = False

# markdown extensions
md_extensions = [
        "extra",
        "toc",
        "headerid",
        "meta",
        "sane_list",
        "smarty",
        "wikilinks",
        "admonition",
        "codehilite(pygments_style=emacs)"
        ]

# themes and plugins
THEME = 'pelican-themes/elegant'
PLUGIN_PATHS = ['pelican-plugins']
PLUGINS = [
        'assets',
        'extract_toc',
        'neighbors',
        'render_math',
        'related_posts',
        'share_post',
        'series'
        ]

MENUITEMS = (
        ('Home', '/'),
        ('Categories', '/categories.html'),
        ('Tags', '/tags.html'),
        ('Archives', '/archives.html'),
        ('About', '/pages/about.html')
        )

SITEMAP = {
        "format": "xml",
        "priorities": {"articles": 0.5, "indexes": 0.5, "pages": 0.5},
        "changefreqs": {"articles": "monthly", "indexes": "daily", "pages": "monthly"},
        }

# do not generate draft docs
IGNORE_FILES=['drafts/*']

# SEO
GOOGLE_ANALYTICS = 'G-946NSPLZFL'

SITE_DESCRIPTION = (
        "Happy Coding",
        "Kernel & Love"
        )

# show site license
SITE_LICENSE = u'<span xmlns:dct="http://purl.org/dc/terms/" property="dct:title"> kernel.love"</span> by <a xmlns:cc="http://creativecommons.org/ns#" href="https://kernel.love" property="cc:attributionName" rel="cc:attributionURL">Yori Fang</a> is licensed under a <a rel="license" href="http://creativecommons.org/licenses/by-sa/3.0/deed.en_US">Creative Commons Attribution-ShareAlike 3.0 Unported License</a>.'
