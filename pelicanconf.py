#!/usr/bin/env python
# -*- coding: utf-8 -*- #
from __future__ import unicode_literals

AUTHOR = u'Yori Fang'
SITENAME = u'kernelgo'
SITEURL = 'https://kernelgo.org'
TIMEZONE = 'Asia/Shanghai'

PATH = 'content'
DATE_FORMATS = {'zh':'%Y-%m-%d %H:%M'}
DEFAULT_LANG = u'en'


# Feed generation is usually not desired when developing
FEED_ALL_ATOM = None
CATEGORY_FEED_ATOM = None
TRANSLATION_FEED_ATOM = None
AUTHOR_FEED_ATOM = None
AUTHOR_FEED_RSS = None

# Blogroll
GITHUB_URL = 'http://github.com/fangying/'
LINKS = (('kernel', 'https://kernel.org/'),
        ('qemu', 'https://qemu.org/'),
        ('Jinja2', 'http://jinja.pocoo.org/'),
        ('You can modify those links in your config file', '#'),)

# Social widget
SOCIAL = (('github', 'https://github.com/fangying'),
        ('Another social link', '#'),)

# SEO
GOOGLE_ANALYTICS = 'UA-107392039-1'
DISQUS_SITENAME = u'kernelgo'
DISQUS_FILTER = True

# defaults
DEFAULT_PAGINATION = False
USE_FOLDER_AS_CATEGORY = True
DELETE_OUTPUT_DIRECTORY = False

# themes and plugins
THEME = 'pelican-themes/elegant'

PLUGIN_PATHS = ['pelican-plugins']
PLUGINS = [
        'assets',
        'extract_toc',
        'tipue_search',
        'liquid_tags.img',
        'neighbors',
        'render_math',
        'related_posts',
        'share_post',
        'series',
        "liquid_tags.include_code",
        ]

# landing page about
# LANDING_PAGE_TITLE = "Happy Coding"

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
SITE_DESCRIPTION = (
        "Happy Coding"
        )

# show site license
SITE_LICENSE = u'<span xmlns:dct="http://purl.org/dc/terms/" property="dct:title"> kernelgo"</span> by <a xmlns:cc="http://creativecommons.org/ns#" href="https://kernelgo.org" property="cc:attributionName" rel="cc:attributionURL">Yori Fang</a> is licensed under a <a rel="license" href="http://creativecommons.org/licenses/by-sa/3.0/deed.en_US">Creative Commons Attribution-ShareAlike 3.0 Unported License</a>.'
