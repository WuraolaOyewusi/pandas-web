#!/usr/bin/env python
import argparse
import datetime
import operator
import os
import shutil
import sys
import time
import typing

import feedparser
import markdown
import jinja2
import requests
import yaml


class Preprocessors:
    @staticmethod
    def navbar_add_info(context):
        for i, item in enumerate(context['navbar']):
            context['navbar'][i] = dict(item,
                                        has_subitems=isinstance(item['target'],
                                                                list),
                                        slug=(item['name'].replace(' ', '-')
                                                          .lower()))
        return context

    @staticmethod
    def blog_add_posts(context):
        posts = []
        for feed_url in context['blog']['feed']:
            feed_data = feedparser.parse(feed_url)
            for entry in feed_data.entries:
                published = datetime.datetime.fromtimestamp(
                    time.mktime(entry.published_parsed))
                posts.append({'title': entry.title,
                              'author': entry.author,
                              'published': published,
                              'feed': feed_data['feed']['title'],
                              'link': entry.link,
                              'description': entry.description,
                              'summary': entry.summary})
        posts.sort(key=operator.itemgetter('published'), reverse=True)
        context['blog']['posts'] = posts[:context['blog']['num_posts']]
        return context

    @staticmethod
    def maintainers_add_info(context):
        context['maintainers']['people'] = []
        for user in context['maintainers']['active']:
            resp = requests.get(f'https://api.github.com/users/{user}')
            # FIXME GitHub quota limit reached, failing silently for now
            if resp.status_code == 403:
                return context
            resp.raise_for_status()
            context['maintainers']['people'].append(resp.json())
        return context

    @staticmethod
    def home_add_releases(context):
        context['releases'] = []

        resp = requests.get(
            'https://api.github.com/repos/pandas-dev/pandas/releases')
        # FIXME GitHub quota limit reached, failing silently for now
        if resp.status_code == 403:
            return context
        resp.raise_for_status()

        for release in resp.json():
            if release['prerelease']:
                continue
            published = datetime.datetime.strptime(release['published_at'],
                                                   '%Y-%m-%dT%H:%M:%SZ')
            context['releases'].append({
                'name': release['tag_name'].lstrip('v'),
                'tag': release['tag_name'],
                'published': published,
                'url': (release['assets'][0]['browser_download_url']
                        if release['assets'] else '')})
        return context


def get_context(config_fname: str, preprocessors=[], **kwargs):
    with open(config_fname) as f:
        context = yaml.safe_load(f)

    context.update(kwargs)

    for preprocessor in preprocessors:
        context = preprocessor(context)
        msg = f'{preprocessor.__name__} is missing the return statement'
        assert context is not None, msg

    return context


def get_source_files(source_path: str) -> typing.Generator[str, None, None]:
    for root, dirs, fnames in os.walk(source_path):
        root = os.path.relpath(root, source_path)
        for fname in fnames:
            yield os.path.join(root, fname)


def main(config_fname: str,
         source_path: str,
         theme_path: str,
         target_path: str,
         base_url: str) -> int:
    shutil.rmtree(target_path, ignore_errors=True)
    os.makedirs(target_path, exist_ok=True)
    shutil.copytree(os.path.join(theme_path, 'static/'),
                    os.path.join(target_path, 'static'))

    jinja_env = jinja2.Environment(loader=jinja2.FileSystemLoader(theme_path))
    sys.stderr.write('Generating context...\n')
    context = get_context(config_fname,
                          preprocessors=[Preprocessors.navbar_add_info,
                                         Preprocessors.blog_add_posts,
                                         Preprocessors.maintainers_add_info,
                                         Preprocessors.home_add_releases],
                          base_url=base_url)
    sys.stderr.write('Context generated\n')

    for fname in get_source_files(source_path):
        sys.stderr.write(f'Processing {fname}\n')
        dirname = os.path.dirname(fname)
        os.makedirs(os.path.join(target_path, dirname), exist_ok=True)

        extension = os.path.splitext(fname)[-1]
        if extension in ('.html', '.md'):
            with open(os.path.join(source_path, fname)) as f:
                content = f.read()
            if extension == '.md':
                body = markdown.markdown(content,
                                         extensions=['toc',
                                                     'tables',
                                                     'fenced_code'])
                content = '{% extends "layout.html" %}'
                content += '{% block body %}'
                content += body
                content += '{% endblock %}'
            content = (jinja_env.from_string(content).render(**context))
            fname = os.path.splitext(fname)[0] + '.html'
            with open(os.path.join(target_path, fname), 'w') as f:
                f.write(content)
        else:
            shutil.copy(os.path.join(source_path, fname),
                        os.path.join(target_path, dirname))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Documentation builder.')
    parser.add_argument('config_fname',
                        help='path to the yaml config file')
    parser.add_argument('--sources-path', default='source',
                        help='path to the directory with the markdown pages')
    parser.add_argument('--theme-path', default='theme',
                        help='path to the directory with the static files')
    parser.add_argument('--target-path', default='build',
                        help='directory where to write the output')
    parser.add_argument('--base-url', default='',
                        help='base url where the website is served from')
    args = parser.parse_args()
    sys.exit(main(args.config_fname,
                  args.sources_path,
                  args.theme_path,
                  args.target_path,
                  args.base_url))
